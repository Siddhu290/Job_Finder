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
    raise ResumeFileError("Upload a PDF or DOCX file")


def _pdf(data):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ResumeFileError("The PDF is password-protected")
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:MAX_PAGES])
    except (PdfReadError, ValueError, KeyError, TypeError) as e:
        if isinstance(e, ResumeFileError):
            raise
        raise ResumeFileError("Could not read this PDF") from None
    return _tidy(text)


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
