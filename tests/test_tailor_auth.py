import io
import json
import zipfile

import pytest

import llm
import tailor
import webapi
from tests.test_vercel import post

RESUME = """Siddharth M — B.Tech Computer Science 2025
Projects
- Built a sales dashboard in Power BI from 3 Excel sources
- Cleaned 50,000 rows of retail data with Python and Pandas
Skills: Python, SQL, Excel, Power BI""" + " " * 120
JOB = "Junior Data Analyst. Requirements: SQL, Python, Tableau, Snowflake. Build dashboards for sales teams. " * 3


def test_guard_drops_invented_content():
    out = tailor.guard({
        "summary": "Data analyst graduate",
        "bullet_suggestions": [
            {"original": "Built a sales dashboard in Power BI from 3 Excel sources", "suggested": "Built a Power BI sales dashboard combining 3 Excel sources", "reason": "clearer"},
            {"original": "Cleaned 50,000 rows of retail data with Python and Pandas", "suggested": "Cleaned 50,000 rows, cutting errors by 40%", "reason": "impact"},   # invented 40%
            {"original": "Led a team of 10 engineers at Google", "suggested": "Led 10 engineers", "reason": "x"},                                                   # not in resume
        ],
        "keywords": ["SQL", "Tableau", "Snowflake", "sql"],
        "draft": "Data analyst. Increased revenue by 25%. Skills: Python, SQL, Tableau."}, RESUME)
    assert [b["suggested"] for b in out["bullet_suggestions"]] == ["Built a Power BI sales dashboard combining 3 Excel sources"]
    assert out["keywords"] == [{"keyword": "SQL", "in_resume": True}, {"keyword": "Tableau", "in_resume": False},
                               {"keyword": "Snowflake", "in_resume": False}]
    w = " ".join(out["warnings"])
    assert "25%" in w and "Tableau" in w and "2 suggested bullet change(s) were removed" in w


def test_tailor_requires_resume_and_job_text(monkeypatch):
    with pytest.raises(llm.LLMError, match="Resume text"):
        tailor.tailor("short", "DA", "Acme", JOB)
    with pytest.raises(llm.LLMError, match="no stored description"):
        tailor.tailor(RESUME, "DA", "Acme", "")
    monkeypatch.setattr(llm, "chat_json", lambda system, user: {"summary": "ok", "draft": RESUME})
    assert tailor.tailor(RESUME, "DA", "Acme", JOB)["warnings"] == []


def test_docx_is_valid_zip_with_text():
    data = tailor.to_docx("Line one\nA & B <tag>")
    z = zipfile.ZipFile(io.BytesIO(data))
    doc = z.read("word/document.xml").decode()
    assert "Line one" in doc and "A &amp; B &lt;tag&gt;" in doc and "[Content_Types].xml" in z.namelist()


# ---------- sessions, login throttling, rate limits ----------
def test_session_tokens(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw1")
    t = webapi.issue_token(now=1000)
    assert webapi.token_ok(t, now=1001)
    assert not webapi.token_ok(t, now=1000 + webapi.SESSION_HOURS * 3600 + 1)     # expired
    assert not webapi.token_ok(t.split(".")[0] + ".deadbeef", now=1001)            # forged
    assert not webapi.token_ok("garbage", now=1001)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw2")
    assert not webapi.token_ok(t, now=1001)                                        # password change signs out


def test_login_and_throttle(monkeypatch):
    from api import login
    from api import jobs
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    webapi._hits.clear()
    hdr = {"X-Forwarded-For": "1.2.3.4"}
    for _ in range(5):
        assert post(login.handler, hdr, {"password": "wrong"})[0] == 401
    assert post(login.handler, hdr, {"password": "pw"})[0] == 429               # blocked after 5 failures
    code, body = post(login.handler, {"X-Forwarded-For": "5.6.7.8"}, {"password": "pw"})
    assert code == 200 and webapi.token_ok(body["token"])
    h = type("H", (), {"headers": {"Authorization": "Bearer " + body["token"]}})()
    assert webapi.authorized(h)
    webapi._hits.clear()


def test_rate_limit():
    webapi._hits.clear()
    h = type("H", (), {"headers": {"X-Forwarded-For": "9.9.9.9"}})()
    assert all(webapi.rate_ok(h, "t", 3) for _ in range(3)) and not webapi.rate_ok(h, "t", 3)
    webapi._hits.clear()


def test_tailor_api(monkeypatch):
    from api import tailor as tailor_api
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    st = type("S", (), {"read": lambda self, *t: {"Jobs": [{"Job ID": "J1", "Job Title": "Junior Data Analyst", "Company": "Acme"}],
                                                   "Details": [{"Job ID": "J1", "Description": JOB}]}})()
    monkeypatch.setattr(webapi, "store", lambda *a: st)
    monkeypatch.setattr(llm, "chat_json", lambda s, u: {"summary": "Fresher analyst", "draft": RESUME, "keywords": ["Tableau"]})
    key = {"X-Dashboard-Key": "pw"}
    assert post(tailor_api.handler, {}, {"job_id": "J1"})[0] == 401
    assert post(tailor_api.handler, key, {"job_id": "J9", "resume_text": RESUME})[0] == 404
    code, out = post(tailor_api.handler, key, {"job_id": "J1", "resume_text": RESUME})
    assert code == 200 and out["keywords"] == [{"keyword": "Tableau", "in_resume": False}]
