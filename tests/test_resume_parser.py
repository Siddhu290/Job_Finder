import base64
import io
import json

import pytest

import resume_parser
import tailor
from resume_parser import ResumeFileError, extract_text


def make_pdf(text="Siddharth M Data Analyst Python SQL Power BI"):
    """A real one-page PDF with a text stream (offsets computed, so it's well-formed)."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs))
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref))
    return out.getvalue()


def test_pdf_and_docx_text():
    assert "Python SQL Power BI" in extract_text("cv.pdf", make_pdf())
    docx = tailor.to_docx("Siddharth M\nSkills: Python & SQL\n\nProjects")
    assert extract_text("CV.DOCX", docx) == "Siddharth M\nSkills: Python & SQL\nProjects"


@pytest.mark.parametrize("name,data,msg", [
    ("cv.pdf", b"MZ\x90\x00 not a pdf", "PDF or DOCX"),          # renamed executable
    ("cv.exe", make_pdf(), "PDF or DOCX"),                       # right bytes, wrong type
    ("cv.docx", b"PK\x03\x04garbage", "Could not read this DOCX"),
    ("cv.pdf", b"%PDF-1.4 garbage", "Could not read this PDF"),
    ("cv.pdf", b"", "empty"),
    ("cv.pdf", b"%PDF" + b"0" * (resume_parser.MAX_BYTES + 1), "larger than 3 MB"),
])
def test_rejects_bad_files(name, data, msg):
    with pytest.raises(ResumeFileError, match=msg):
        extract_text(name, data)


def test_encrypted_pdf_and_zip_bomb_guard(monkeypatch):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(make_pdf())))
    w.encrypt("secret")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ResumeFileError, match="password-protected"):
        extract_text("cv.pdf", buf.getvalue())
    monkeypatch.setattr(resume_parser, "MAX_DOCX_XML", 10)
    with pytest.raises(ResumeFileError, match="too large"):
        extract_text("cv.docx", tailor.to_docx("x" * 100))


def test_upload_endpoint_returns_text_but_never_stores_it(monkeypatch):
    import llm
    import webapi
    from routes import resume
    from tests.test_resume import MemStore
    from tests.test_vercel import post
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    st = MemStore()
    monkeypatch.setattr(webapi, "store", lambda *a: st)
    seen = {}
    monkeypatch.setattr(llm, "extract_profile", lambda text, *a: seen.setdefault("t", text) and llm.clean_profile({"roles": ["Data Analyst"]}))
    body = {"file": base64.b64encode(make_pdf("Fresher Data Analyst with Python SQL " * 3)).decode(), "filename": "cv.pdf", "name": "CV"}
    code, out = post(resume.handler, {"X-Dashboard-Key": "pw"}, body)
    assert code == 200 and "Python SQL" in out["text"] and "Python SQL" in seen["t"]
    assert "Python SQL" not in json.dumps(st.json)                   # not persisted server-side
    code, out = post(resume.handler, {"X-Dashboard-Key": "pw"}, {"file": "%%%not-base64", "filename": "cv.pdf"})
    assert code == 400
    code, out = post(resume.handler, {"X-Dashboard-Key": "pw"}, {"file": base64.b64encode(b"MZ").decode(), "filename": "cv.pdf"})
    assert code == 400 and "PDF or DOCX" in out["error"]
