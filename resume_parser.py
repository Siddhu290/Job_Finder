"""Resume file -> plain text, in memory only (the file is never written to disk or stored).

Accepts PDF and DOCX only, checked by file signature as well as extension. Limits: 3 MB (Vercel's request
body limit is 4.5 MB and the file arrives base64-encoded), 10 PDF pages, and a cap on the uncompressed size of
a DOCX to stop zip bombs. DOCX text is pulled out with a regex instead of an XML parser (no entity expansion)."""
import html
import io
import re
import zipfile

MAX_BYTES = 3_000_000
MAX_PAGES = 10
MAX_DOCX_XML = 20_000_000


class ResumeFileError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if not data:
        raise ResumeFileError("The file is empty")
    if len(data) > MAX_BYTES:
        raise ResumeFileError("The file is larger than 3 MB")
    if name.endswith(".pdf") and data.startswith(b"%PDF"):
        return _pdf(data)
    if name.endswith(".docx") and data.startswith(b"PK"):
        return _docx(data)
    if name.endswith(".tex"):
        import latex_resume
        try:
            tex = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ResumeFileError("The .tex file isn't UTF-8 text") from None
        if not latex_resume.is_latex(tex):
            raise ResumeFileError("This .tex file has no \\documentclass / \\begin{document}")
        return tex.replace("\r\n", "\n")     # kept as LaTeX source, exactly as written
    raise ResumeFileError("Upload a PDF, DOCX or .tex file")


def _pdf(data):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ResumeFileError("The PDF is password-protected")
        pages = reader.pages[:MAX_PAGES]
        try:          # layout mode keeps the big gap of right-aligned text ("Odoo Developer      Alligator Infosoft")
            text = "\n".join(_split_gaps(p.extract_text(extraction_mode="layout") or "") for p in pages)
        except Exception:  # noqa: BLE001 - layout mode is best-effort; plain extraction always works
            text = ""
        if len(text.strip()) < 50:
            text = "\n".join((p.extract_text() or "") for p in pages)
    except (PdfReadError, ValueError, KeyError, TypeError) as e:
        if isinstance(e, ResumeFileError):
            raise
        raise ResumeFileError("Could not read this PDF") from None
    return _tidy(text)


_RUN = re.compile(r" {2,}")
_PAGE_NO = re.compile(r"^\s*(?:page\s*)?\d{1,2}(?:\s*(?:/|of)\s*\d{1,2})?\s*$", re.I)


def _split_gaps(page_text: str) -> str:
    """One line per text line. A right-aligned part (date, place, company) is separated by the single gap that is far
    wider than every other gap on the line; it becomes " | " (not when the right part holds a "label: value", and
    headings are matched with " | " ignored). All other spacing collapses to one space. Page numbers are dropped."""
    out = []
    for line in page_text.splitlines():
        line = line.strip()
        if not line or _PAGE_NO.match(line):
            continue
        runs = sorted(((len(m.group()), m.start(), m.end()) for m in _RUN.finditer(line)), reverse=True)
        if runs and runs[0][0] >= 15 and (len(runs) == 1 or runs[0][0] >= 2.5 * runs[1][0]):
            _, a, b = runs[0]
            if ":" not in line[b:]:          # "Aggregate   CGPA: 7.60" is a bold label, not a right-aligned part
                line = line[:a] + " | " + line[b:]
        out.append(re.sub(r" {2,}", " ", line))
    return "\n".join(out)
def _docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML:
                raise ResumeFileError("The DOCX is too large")
            xml = z.read(info).decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError):
        raise ResumeFileError("Could not read this DOCX") from None
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    lines = ["".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p)) for p in paras]
    return _tidy(html.unescape("\n".join(lines)))


def _tidy(text):
    text = re.sub(r"[ \t ]+", " ", text or "")
    return re.sub(r"\n\s*\n+", "\n", text).strip()
