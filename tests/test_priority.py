import json
from datetime import date

from http_client import is_trusted_source
from integrations.google_sheets import HEADERS
from priority import published_emails, score

TODAY = date(2026, 10, 9)


def r(**kw):
    d = dict.fromkeys(HEADERS, "")
    d.update({k.replace("_", " "): v for k, v in kw.items()})
    return d


def test_trusted_sources():
    assert is_trusted_source("https://in.linkedin.com/jobs/view/1")
    assert is_trusted_source("https://www.naukri.com/job-listings-x")
    assert is_trusted_source("https://jobs.lever.co/acme/1")
    assert is_trusted_source("https://careers.acmeanalytics.com/job/1", "Acme Analytics Pvt Ltd")
    assert not is_trusted_source("https://bebee.com/in/jobs/x")
    assert not is_trusted_source("https://myinternships.in/jobs/x", "Acme")
    assert not is_trusted_source("https://randomjobs.xyz/acme", "Zeta")


def test_published_emails_only():
    text = "Send CV to HR@AcmeAnalytics.com or careers@acme.in. Logo: logo@2x.png. noreply@acme.com"
    assert published_emails(text) == ["hr@acmeanalytics.com", "careers@acme.in"]
    assert published_emails("No contact given") == []


def test_priority_order():
    verified_pune = r(Verification_Status="Verified", Official_Apply_URL="https://jobs.lever.co/a/1",
                      Official_Careers_URL="https://a.com/careers", Location="Pune, Maharashtra",
                      Experience_Requirement="0-1 years", Job_Posted_Date="2026-10-08", Source_Platform="Lever board (a)")
    review_wfh_company = r(Verification_Status="Needs Review", Official_Careers_URL="https://b.com/careers", Job_Posted_Date="2026-10-08",
                           Location="Chennai", Employment_Type="Full-time, Work from home",
                           Experience_Requirement="Fresher/entry-level", Notes="HR email (published in listing): hr@b.com")
    portal_only = r(Verification_Status="Needs Review", Location="Pune", Source_Platform="Google Jobs (LinkedIn)",
                    Experience_Requirement="Not stated")
    s = [score(x, TODAY) for x in (verified_pune, review_wfh_company, portal_only)]
    assert s[0][1] == "High" and s[1][1] == "Medium" and s[2][1] == "Low"
    assert s[0][0] > s[1][0] > s[2][0]
    assert "HR email published" in s[1][2] and "only seen on job portals" in s[2][2]
    assert score(r(Verification_Status="Rejected"))[1] == "Hidden"


def _bundle():
    H = HEADERS
    row = lambda **kw: {h: kw.get(h.replace(" ", "_"), "") for h in H}
    return {
        "Jobs": [row(Job_ID="J1", Job_Title="Data Analyst", Company="Portal Co", Location="Pune", Experience_Requirement="Not stated",
                     Source_Platform="Google Jobs (LinkedIn)", Verification_Status="Needs Review",
                     Original_Listing_URL="https://www.linkedin.com/jobs/view/1", Official_Apply_URL="https://sneaky.example/apply"),
                 row(Job_ID="J2", Job_Title="Data Analyst", Company="Acme", Location="Pune", Experience_Requirement="0-1 years",
                     Source_Platform="Lever board (acme)", Official_Careers_URL="https://acme.com/careers",
                     Official_Apply_URL="https://jobs.lever.co/acme/1", Verification_Status="Verified",
                     Notes="HR email (published in listing): hr@acme.com"),
                 row(Job_ID="J3", Job_Title="Data Analyst", Company="Gamma", Location="Pune", Verification_Status="Applied")],
        "Details": [{"Job ID": "J2", "Description": "SQL, Python, Power BI. 0-1 years.", "Required Skills": "SQL, Python, Power BI",
                     "Contacts": json.dumps([{"type": "published", "value": "talent@acme.com", "evidence": "https://jobs.lever.co/acme/1"}])}],
        "Verification": [{"Job ID": "J2", "Checks": json.dumps({"open_status": {"status": "pass", "detail": "listed", "url": ""}}),
                          "Last Open Check": "2026-10-09 08:00", "Status": "Verified", "Timestamp": "2026-10-09 08:00"}],
        "Applications": [], "Runs": [{"Run ID": "r1", "Started": "2026-10-09 08:00", "SerpApi Calls": "12"}],
        "_settings": {"prefer": ["Acme"]},
        "_profile": {"use_in_search": True, "active": "p1", "profiles": [{"id": "p1", "name": "CV", "roles": ["Data Analyst"], "skills": ["SQL", "Python"]}]},
    }


def test_dashboard_build_ranks_and_never_exposes_unverified_apply():
    from api.jobs import build
    body = build(_bundle(), TODAY)
    ids = [j["id"] for j in body["jobs"]]
    assert ids[0] == "J2"
    j1, j2 = (next(j for j in body["jobs"] if j["id"] == i) for i in ("J1", "J2"))
    assert j1["apply"] == "" and j1["apply_kind"] == "portal"          # Needs Review: no official apply URL shown
    assert j2["apply_kind"] == "verified" and j2["apply_link"] == "https://jobs.lever.co/acme/1"
    assert j2["preferred"] and "preferred company" in j2["why"]
    assert j2["match"]["missing_required"] == ["Power BI"] and j2["match"]["eligible"]
    assert j2["verification"]["checks"]["open_status"]["status"] == "pass" and j2["verification"]["last_open_check"]
    types = {(c["type"], c["value"]) for c in j2["contacts"]}
    assert ("published", "talent@acme.com") in types and ("listing", "hr@acme.com") in types
    j3 = next(j for j in body["jobs"] if j["id"] == "J3")
    assert j3["application"]["Stage"] == "Applied"                     # legacy status mapped to the lifecycle
    assert body["runs"][0]["Run ID"] == "r1" and body["profile"]["name"] == "CV"


def test_dashboard_api_requires_auth(monkeypatch):
    import webapi
    from api import jobs as api
    monkeypatch.setenv("DASHBOARD_PASSWORD", "s3cret")
    monkeypatch.setattr(webapi, "store", lambda *a: type("S", (), {"bundle": lambda self, t, j: _bundle()})())
    monkeypatch.setattr("budget.account", lambda key: {"total_searches_left": 190})
    from tests.test_vercel import call
    assert call(api.handler, {"X-Dashboard-Key": "wrong"})[0] == 401
    code, body = call(api.handler, {"X-Dashboard-Key": "s3cret"})
    assert code == 200 and body["searches_left"] == 190 and len(body["jobs"]) == 3


def test_hr_profiles_from_google_results():
    from discovery.hr_search import from_notes, note, parse_results
    results = [
        {"link": "https://in.linkedin.com/in/kishan-dev-b77821194", "title": "kishan dev - Human Resources Manager at Vedantu"},
        {"link": "https://www.linkedin.com/posts/x_hiring", "title": "Saurabh's Post - Vedantu HR"},          # not a profile
        {"link": "https://in.linkedin.com/in/tarun", "title": "Tarun Pandey - Talent Acquisition | HR Management"},  # no company
        {"link": "https://in.linkedin.com/in/jay", "title": "Jayanna R - Vedantu | Ex Deepcompute | SAP"},          # not HR
        {"link": "https://in.linkedin.com/in/kurnal", "title": "Kurnal Kapoor - Senior Human Resources Officer at Vedantu"},
    ]
    got = parse_results("Vedantu", results)
    assert [g[0] for g in got] == ["kishan dev", "Kurnal Kapoor"]
    back = from_notes("employer posting verified; " + note(got))
    assert back[0]["url"] == "https://in.linkedin.com/in/kishan-dev-b77821194"
    assert back[1]["headline"] == "Senior Human Resources Officer at Vedantu"


def test_company_career_page_listing_outranks_portal_only():
    base = dict(Verification_Status="Needs Review", Location="Pune", Experience_Requirement="Not stated")
    company = score(r(Source_Platform="Company career page + Google Jobs (Naukri)", **base), TODAY)
    portal = score(r(Source_Platform="Google Jobs (Naukri)", **base), TODAY)
    assert company[0] > portal[0] and "listed on company's own career page" in company[2]
