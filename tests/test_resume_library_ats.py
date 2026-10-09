"""Named resume collection (encrypted), ATS scoring, per-user API keys (SerpApi + Groq)."""
import json

import pytest

import ats
import resumes
import user_secrets
from storage.store import Store
from tests.test_store_budget import FakeClient
from tests.test_vercel import call, post

FERNET = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="
RESUME = """Siddharth M | sid@example.com | +91 98765 43210 | linkedin.com/in/sid
Summary: Aspiring Data Analyst
Education: B.Tech Computer Science 2025
Skills: Python, SQL, Excel, Power BI
Projects
- Built a sales dashboard in Power BI covering 3 regions and 12,000 orders
- Cleaned 50,000 rows of retail data with Pandas, cutting report time by 40%
- Analyzed churn with SQL window functions
Experience
- Prepared weekly Excel reports for 5 store managers (internship)"""
JD = "Junior Data Analyst. Requirements: SQL, Python, Excel and Tableau. Nice to have: Airflow. Build dashboards."


@pytest.fixture
def st(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", FERNET)
    return Store(FakeClient())


def test_resume_versions_named_encrypted_and_selectable(st):
    a = resumes.save(st, "Data Analyst – Oct", RESUME, "upload")
    b = resumes.save(st, "Data Analyst – Oct", RESUME + "\n- Extra bullet for the second version", "tailored", "DA · Acme")
    assert b["name"].startswith("Data Analyst – Oct (")                      # duplicate names get a timestamp
    assert {v["id"] for v in resumes.list_versions(st)} == {a["id"], b["id"]}
    assert resumes.get_text(st, a["id"]) == RESUME and "Extra bullet" in resumes.get_text(st, b["id"])
    raw = json.dumps(st.get_json(f"_resume_{a['id']}"))
    assert "Siddharth" not in raw and "Power BI" not in raw                   # encrypted at rest
    resumes.rename(st, a["id"], "Base resume")
    assert resumes.list_versions(st)[-1]["name"] in ("Base resume", b["name"])
    resumes.delete(st, a["id"])
    assert [v["id"] for v in resumes.list_versions(st)] == [b["id"]] and st.get_json(f"_resume_{a['id']}") == {}
    with pytest.raises(KeyError):
        resumes.get_text(st, a["id"])
    with pytest.raises(resumes.ResumeError):
        resumes.save(st, "<script>", RESUME)
    with pytest.raises(resumes.ResumeError):
        resumes.save(st, "Tiny", "too short")


def test_ats_score_explains_and_suggests():
    r = ats.score(RESUME, JD, "Junior Data Analyst")
    assert 60 <= r["score"] <= 95
    assert r["missing_required"] == ["Tableau"] and "SQL" in r["matched_keywords"] and r["missing_preferred"] == ["Airflow"]
    assert r["sections"]["Skills"] and r["sections"]["Projects"] and r["bullets_with_numbers"] >= 2
    tips = " ".join(t["text"] for t in r["suggestions"])
    assert "Tableau" in tips and "Don't add them if you haven't" in tips        # never pushes untrue claims
    weak = ats.score("Data person. I know things." * 3, JD, "Junior Data Analyst")
    assert weak["score"] < r["score"] and any(t["priority"] == "high" for t in weak["suggestions"])


def test_ats_and_resumes_endpoints(st, monkeypatch):
    import webapi
    from routes import ats as ats_route, resumes as resumes_route
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    monkeypatch.setattr(webapi, "store", lambda *a: st)
    key = {"X-Dashboard-Key": "pw"}
    code, v = post(resumes_route.handler, key, {"action": "save", "name": "CV", "text": RESUME, "source": "upload"})
    assert code == 200 and call(resumes_route.handler, key)[1]["versions"][0]["name"] == "CV"
    code, r = post(ats_route.handler, key, {"resume_id": v["id"], "job_text": JD, "job_title": "Junior Data Analyst"})
    assert code == 200 and r["missing_required"] == ["Tableau"]
    assert post(ats_route.handler, key, {"resume_id": "nope", "job_text": JD})[0] == 404
    assert post(ats_route.handler, key, {"resume_id": v["id"], "job_text": "short"})[0] == 400
    assert post(resumes_route.handler, {}, {"action": "get", "id": v["id"]})[0] == 401


def test_api_keys_saved_tested_and_never_returned(st, monkeypatch):
    import budget
    import llm
    import webapi
    from routes import keys
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    monkeypatch.setattr(webapi, "store", lambda *a: st)
    monkeypatch.setattr(budget, "account", lambda k: {"total_searches_left": 77} if k == "serpkey0123456789abcdef" else {})
    monkeypatch.setattr(llm, "test_key", lambda k: k == "gsk_" + "a" * 40)
    key = {"X-Dashboard-Key": "pw"}
    assert post(keys.handler, key, {"kind": "groq", "key": "not-a-groq-key"})[0] == 400                 # format check
    assert post(keys.handler, key, {"kind": "groq", "key": "gsk_" + "b" * 40})[0] == 400                 # rejected by Groq
    code, out = post(keys.handler, key, {"kind": "groq", "key": "gsk_" + "a" * 40})
    assert code == 200 and out == {"source": "own", "hint": "…aaaa"}
    code, out = post(keys.handler, key, {"kind": "serpapi", "key": "serpkey0123456789abcdef"})
    assert code == 200 and out["searches_left"] == 77
    status = call(keys.handler, key)[1]
    assert "gsk_aaaa" not in json.dumps(status) and "serpkey0123" not in json.dumps(status)
    assert user_secrets.get_key(st, "groq") == "gsk_" + "a" * 40
    assert post(keys.handler, key, {"kind": "groq", "action": "remove"})[1]["source"] == "none"
    assert post(keys.handler, key, {"kind": "other", "key": "x"})[0] == 400


def test_ai_calls_use_the_users_own_groq_key(st, monkeypatch):
    import llm
    import webapi
    from routes import tailor as tailor_route
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    monkeypatch.setattr(webapi, "store", lambda *a: st)
    user_secrets.save_key(st, "groq", "gsk_" + "u" * 40)
    v = resumes.save(st, "CV", RESUME)
    used = []
    monkeypatch.setattr(llm, "chat_json", lambda s, u, key=None: used.append(key) or {"summary": "ok", "draft": RESUME})
    code, out = post(tailor_route.handler, {"X-Dashboard-Key": "pw"}, {"resume_id": v["id"], "job_text": JD * 2, "job_title": "DA"})
    assert code == 200 and used == ["gsk_" + "u" * 40]
