"""Verification tests. All HTTP and SerpApi traffic is faked; nothing here touches the network."""
import json
from datetime import date

import pytest

import http_client
from models import CLOSED, NEEDS_REVIEW, REJECTED, VERIFIED, Job, Posting
from verification import application_status, ats_clients, company_resolver, pipeline, vacancy_matcher
from verification.ats_verifier import AtsRef, find_board_refs, parse_ats_url, relationship

GH_JOB = "https://boards.greenhouse.io/acmeanalytics/jobs/4001"
GH_API = "https://boards-api.greenhouse.io/v1/boards/acmeanalytics/jobs/4001"
HOME, CAREERS = "https://www.acmeanalytics.com/", "https://www.acmeanalytics.com/careers"


class Resp:
    def __init__(self, status=200, text="", url=""):
        self.status_code, self.text, self.url = status, text, url


class FakeWeb:
    """pages: url -> (status, html[, final_url]); api: url -> json (None = 404)."""
    def __init__(self, pages=None, api=None):
        self.pages, self.api, self.page_hits = pages or {}, api or {}, []

    def get_page(self, url):
        self.page_hits.append(url)
        status, text, *final = self.pages.get(url, (404, ""))
        return Resp(status, text, final[0] if final else url)

    def get_json(self, url, **kw):
        return self.api.get(url)

    def post_json(self, url, payload, **kw):
        return self.api.get(url)


class FakeSerp:
    def __init__(self, kg=None):
        self.kg, self.calls = kg, 0

    def search(self, **params):
        self.calls += 1
        return {"knowledge_graph": self.kg} if self.kg else {}


@pytest.fixture
def web(monkeypatch):
    w = FakeWeb()
    monkeypatch.setattr(http_client, "get_page", w.get_page)
    monkeypatch.setattr(http_client, "get_json", w.get_json)
    monkeypatch.setattr(http_client, "post_json", w.post_json)
    ats_clients.fetch_posting.cache_clear()
    return w


@pytest.fixture
def cache(tmp_path):
    return company_resolver.CompanyCache(tmp_path / "companies.json")


def stats():
    return {"careers_pages": 0, "errors": []}


def acme_job(**kw):
    d = dict(title="Data Analyst", company="Acme Analytics Pvt Ltd", location="Pune, Maharashtra, India",
             description="Freshers welcome.", listing_url="https://www.linkedin.com/jobs/view/1",
             links=["https://www.linkedin.com/jobs/view/1", GH_JOB], source="Google Jobs (LinkedIn)")
    d.update(kw)
    return Job(**d)


GH_POSTING = {"id": 4001, "title": "Data Analyst", "location": {"name": "Pune, India"},
              "content": "&lt;p&gt;We hire freshers: 0-1 years of experience.&lt;/p&gt;",
              "absolute_url": GH_JOB, "first_published": "2026-10-07T10:00:00Z"}
ACME_KG = {"title": "Acme Analytics", "website": HOME}


def acme_site(web, careers_html='<a href="https://boards.greenhouse.io/acmeanalytics">Open roles</a>'):
    web.pages[HOME] = (200, '<a href="/careers">Careers</a>')
    web.pages[CAREERS] = (200, careers_html)


# ---------- URL recognition ----------
def test_parse_ats_urls():
    assert parse_ats_url(GH_JOB) == AtsRef("greenhouse", "acmeanalytics", "4001", url=GH_JOB)
    assert parse_ats_url("https://jobs.lever.co/acme/1a2b-3c/apply").job_id == "1a2b-3c"
    assert parse_ats_url("https://jobs.ashbyhq.com/acme/uuid-1").ats == "ashby"
    sr = parse_ats_url("https://jobs.smartrecruiters.com/AcmeCorp/743999912345-data-analyst")
    assert (sr.board, sr.job_id) == ("acmecorp", "743999912345")
    wd = parse_ats_url("https://acme.wd5.myworkdayjobs.com/en-US/External/job/Pune/Data-Analyst_R12345")
    assert (wd.board, wd.site, wd.job_id, wd.path) == ("acme", "External", "R12345", "job/Pune/Data-Analyst_R12345")
    assert parse_ats_url("https://www.acme.com/careers?gh_jid=555").job_id == "555"
    assert parse_ats_url("https://www.linkedin.com/jobs/view/123") is None
    assert parse_ats_url("https://acme-greenhouse.io.example.com/jobs/1") is None


def test_find_board_refs_in_careers_html():
    html = """<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>
              <a href="https://jobs.lever.co/acme-labs">Lever</a>
              <iframe src="https://acme.wd3.myworkdayjobs.com/en-US/AcmeCareers"></iframe>"""
    keys = {r.board_key for r in find_board_refs(html)}
    assert keys == {("greenhouse", "acme"), ("lever", "acme-labs"), ("workday", "acme")}


def test_job_board_urls_are_never_official():
    assert http_client.is_job_board("https://in.linkedin.com/jobs/view/1")
    assert http_client.is_job_board("https://www.naukri.com/job-listings-x")
    assert not http_client.is_job_board("https://careers.acme.co.in/job/1")
    with pytest.raises(PermissionError):
        http_client.request("GET", "https://www.indeed.co.in/viewjob?jk=1")


def test_known_ats_is_not_trusted_without_employer_link():
    ref = parse_ats_url(GH_JOB)
    ok, ev = relationship(ref, GH_JOB, "acmeanalytics.com", linked_boards=set())
    assert not ok and "unverified" in ev
    ok, _ = relationship(ref, GH_JOB, "acmeanalytics.com", {AtsRef("greenhouse", "acmeanalytics")})
    assert ok
    # Same ATS, different board: an impostor board with a similar name is rejected
    ok, _ = relationship(ref, GH_JOB, "acmeanalytics.com", {AtsRef("greenhouse", "acme-analytics-careers")})
    assert not ok


def test_company_name_in_url_is_not_ownership():
    ok, _ = relationship(None, "https://acmeanalytics-jobs.com/apply/1", "acmeanalytics.com", set())
    assert not ok


# ---------- employer identification ----------
def test_knowledge_graph_must_match_employer(tmp_path):
    cache = lambda: company_resolver.CompanyCache(tmp_path / "none.json")  # fresh: negative results are cached
    site, why = company_resolver.resolve_official_site("Acme Analytics", FakeSerp({"title": "Acme Corp", "website": "https://acme.com"}), cache())
    assert site is None and "does not match" in why
    site, why = company_resolver.resolve_official_site("Beta Data", FakeSerp({"title": "Beta Data", "website": "https://www.linkedin.com/company/beta"}), cache())
    assert site is None and "job board" in why
    site, _ = company_resolver.resolve_official_site("Acme Analytics Pvt. Ltd.", FakeSerp(ACME_KG), cache())
    assert site.domain == "acmeanalytics.com"


def test_website_via_knowledge_graph_wikipedia_source(web, cache):
    web.api["https://en.wikipedia.org/w/api.php?action=query&prop=pageprops&redirects=1&format=json&titles=Nike%2C_Inc."] = {
        "query": {"pages": {"1": {"pageprops": {"wikibase_item": "Q483915"}}}}}
    web.api["https://www.wikidata.org/wiki/Special:EntityData/Q483915.json"] = {"entities": {"Q483915": {"claims": {"P856": [
        {"rank": "normal", "mainsnak": {"datavalue": {"value": "https://www.nike.com.cn/"}}},
        {"rank": "preferred", "mainsnak": {"datavalue": {"value": "https://www.nike.com/"}}}]}}}}
    kg = {"title": "Nike", "source": {"name": "Wikipedia", "link": "https://en.wikipedia.org/wiki/Nike,_Inc."}}
    site, _ = company_resolver.resolve_official_site("Nike", FakeSerp(kg), cache)
    assert site.domain == "nike.com" and "Wikidata" in site.evidence
    # entity matched by name but no website anywhere -> not established
    site, why = company_resolver.resolve_official_site("Vedantu", FakeSerp({"title": "Vedantu"}), cache)
    assert site is None


def test_bracketed_brand_name_matches(cache):
    kg = {"title": "Taj Hotels", "website": "https://www.tajhotels.com/"}
    site, _ = company_resolver.resolve_official_site("Indian Hotels Company (Taj Hotels)", FakeSerp(kg), cache)
    assert site.domain == "tajhotels.com"


def test_company_cache_avoids_repeat_searches(cache):
    serp = FakeSerp(ACME_KG)
    company_resolver.resolve_official_site("Acme Analytics", serp, cache)
    company_resolver.resolve_official_site("ACME ANALYTICS LIMITED", serp, cache)
    assert serp.calls == 1


# ---------- exact matching ----------
def test_exact_vacancy_matching():
    job = Job("Data Analyst", "Acme", "Bangalore")
    assert vacancy_matcher.match(job, Posting("greenhouse", "u", "Data Analyst - Bengaluru", "Bengaluru, India"))[0]
    assert not vacancy_matcher.match(job, Posting("greenhouse", "u", "Senior Data Analyst", "Bengaluru"))[0]
    assert not vacancy_matcher.match(job, Posting("greenhouse", "u", "Data Analyst, Marketing", "Bengaluru"))[0]
    assert not vacancy_matcher.match(job, Posting("greenhouse", "u", "Data Analyst", "Pune"))[0]
    job.req_id = "R1"
    assert not vacancy_matcher.match(job, Posting("greenhouse", "u", "Data Analyst", "Bengaluru", req_id="R2"))[0]


def test_ambiguous_board_match_is_not_resolved():
    job = Job("Data Analyst", "Acme", "Bengaluru")
    ps = [Posting("lever", "u1", "Data Analyst", "Bengaluru"), Posting("lever", "u2", "Data Analyst", "Bengaluru")]
    p, why = vacancy_matcher.find_in_board(job, ps)
    assert p is None and "ambiguous" in why


# ---------- application status ----------
def test_http_200_alone_never_means_open(web):
    web.pages["https://acme.com/job/1"] = (200, "<h1>Data Analyst</h1>")
    state, _ = application_status.check(Posting("official-site", "https://acme.com/job/1", "Data Analyst", active=None))
    assert state == application_status.UNKNOWN


def test_redirect_to_generic_board_is_not_open(web):
    web.pages[GH_JOB] = (200, "All jobs", "https://boards.greenhouse.io/acmeanalytics?error=true")
    state, ev = application_status.check(Posting("greenhouse", GH_JOB, "Data Analyst", req_id="4001", active=True))
    assert state == application_status.UNKNOWN and "redirected" in ev


def test_expired_jsonld_is_closed():
    html = '<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "JobPosting", "title": "Data Analyst",
        "validThrough": "2026-09-01", "hiringOrganization": {"name": "Acme"}}) + "</script>"
    p = ats_clients.parse_jsonld_posting(html, "https://acme.com/job/1", today=date(2026, 10, 9))
    assert p.active is False
    assert application_status.check(p)[0] == application_status.CLOSED


# ---------- full pipeline ----------
def run(job, web, cache, kg=ACME_KG):
    s = stats()
    pipeline.verify_job(job, FakeSerp(kg), cache, s)
    return job, s


def test_fully_evidenced_vacancy_is_verified(web, cache):
    acme_site(web)
    web.api[GH_API] = GH_POSTING
    web.pages[GH_JOB] = (200, "<h1>Data Analyst</h1><form>Apply</form>")
    job, s = run(acme_job(), web, cache)
    assert job.status == VERIFIED, job.notes
    assert job.apply_url == GH_JOB and job.careers_url == CAREERS
    assert job.req_id == "4001" and s["careers_pages"] == 1
    assert any("linked from the official site" in e for e in job.evidence)


def test_unlinked_ats_board_needs_review(web, cache):
    acme_site(web, careers_html="<p>We are hiring! Email us.</p>")
    web.api[GH_API] = GH_POSTING
    web.pages[GH_JOB] = (200, "<h1>Data Analyst</h1>")
    job, _ = run(acme_job(), web, cache)
    assert job.status == NEEDS_REVIEW and job.apply_url == ""


def test_withdrawn_posting_is_closed(web, cache):
    acme_site(web)
    web.api[GH_API] = None
    job, _ = run(acme_job(), web, cache)
    assert job.status == CLOSED and job.apply_url == ""


def test_no_knowledge_graph_needs_review(web, cache):
    job, _ = run(acme_job(), web, cache, kg=None)
    assert job.status == NEEDS_REVIEW and "official website not established" in job.notes[0]


def test_unknown_employer_needs_review(web, cache):
    job, _ = run(acme_job(company=""), web, cache)
    assert job.status == NEEDS_REVIEW


def test_mocked_200_everywhere_without_evidence_is_never_verified(web, cache):
    page = (200, "<html><h1>Data Analyst</h1><a href='/careers'>Careers</a> Apply now</html>")
    for u in (HOME, CAREERS, "https://www.acmeanalytics.com/jobs/123", "https://careers.acmeanalytics.com/"):
        web.pages[u] = page
    job, _ = run(acme_job(links=["https://www.acmeanalytics.com/jobs/123"]), web, cache)
    assert job.status == NEEDS_REVIEW and job.apply_url == ""


def test_experience_found_in_employer_posting_rejects(web, cache):
    acme_site(web)
    web.api[GH_API] = {**GH_POSTING, "content": "Requires 3+ years of experience with SQL."}
    web.pages[GH_JOB] = (200, "Data Analyst")
    job, _ = run(acme_job(description="Great role"), web, cache)
    assert job.status == REJECTED and job.apply_url == ""


def test_verified_open_but_eligibility_unstated_needs_review(web, cache):
    acme_site(web)
    web.api[GH_API] = {**GH_POSTING, "content": "Work with SQL and Python."}
    web.pages[GH_JOB] = (200, "Data Analyst")
    job, _ = run(acme_job(description="Junior role"), web, cache)
    assert job.status == NEEDS_REVIEW and job.apply_url == ""


def test_vacancy_found_by_searching_linked_board(web, cache):
    acme_site(web, careers_html='<a href="https://jobs.lever.co/acme">Jobs</a>')
    lever_post = {"id": "abc-1", "text": "Data Analyst", "categories": {"location": "Pune"},
                  "descriptionPlain": "Entry-level role for freshers.", "hostedUrl": "https://jobs.lever.co/acme/abc-1"}
    web.api["https://api.lever.co/v0/postings/acme?mode=json"] = [
        lever_post, {**lever_post, "id": "abc-2", "text": "Senior Data Analyst", "hostedUrl": "https://jobs.lever.co/acme/abc-2"}]
    web.pages["https://jobs.lever.co/acme/abc-1"] = (200, "Data Analyst - Apply")
    job, _ = run(acme_job(links=["https://www.linkedin.com/jobs/view/1"]), web, cache)
    assert job.status == VERIFIED and job.apply_url == "https://jobs.lever.co/acme/abc-1"


def test_official_page_with_valid_jsonld_is_verified(web, cache):
    url = "https://www.acmeanalytics.com/careers/data-analyst-bengaluru"
    acme_site(web, careers_html="<p>Careers at Acme</p>")
    web.pages[url] = (200, '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "title": "Data Analyst", "validThrough": "2099-01-01",
        "description": "Open to freshers (0-1 years).", "hiringOrganization": {"name": "Acme Analytics"},
        "jobLocation": {"address": {"addressLocality": "Pune", "addressCountry": "IN"}}}) + "</script>")
    job, _ = run(acme_job(links=[url]), web, cache)
    assert job.status == VERIFIED and job.apply_url == url


def test_verification_errors_are_contained(web, cache, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(pipeline.careers_search, "find_careers", boom)
    job, s = run(acme_job(), web, cache)
    assert job.status == NEEDS_REVIEW and s["errors"]


def test_recheck_detects_closed_and_open(web):
    web.api[GH_API] = None
    assert pipeline.recheck(GH_JOB)[0] == application_status.CLOSED
    ats_clients.fetch_posting.cache_clear()
    web.api[GH_API] = GH_POSTING
    web.pages[GH_JOB] = (200, "Data Analyst")
    assert pipeline.recheck(GH_JOB)[0] == application_status.OPEN


# ---------- transparent verification breakdown ----------
def test_verified_job_has_passing_breakdown(web, cache):
    acme_site(web)
    web.api[GH_API] = GH_POSTING
    web.pages[GH_JOB] = (200, "Data Analyst")
    job, _ = run(acme_job(), web, cache)
    assert job.status == VERIFIED
    for name in ("employer", "official_site", "careers_page", "ats_link", "vacancy_match", "requisition_id",
                 "open_status", "apply_url", "experience", "location"):
        assert job.checks[name]["status"] == "pass", (name, job.checks[name])
    assert job.checks["apply_url"]["url"] == GH_JOB and job.checks["official_site"]["url"] == HOME


def test_breakdown_explains_failures(web, cache):
    acme_site(web, careers_html="<p>We are hiring!</p>")
    web.api[GH_API] = GH_POSTING
    job, _ = run(acme_job(), web, cache)
    assert job.checks["ats_link"]["status"] == "fail" and "not linked" in job.checks["ats_link"]["detail"]
    assert "open_status" not in job.checks                  # never reached: not claimed either way
    ats_clients.fetch_posting.cache_clear()
    acme_site(web)
    web.api[GH_API] = None
    job, _ = run(acme_job(), web, cache)
    assert job.status == CLOSED and job.checks["open_status"]["status"] == "fail"


def test_transient_failures_are_queued_for_retry(web, cache, monkeypatch):
    monkeypatch.setattr(pipeline.careers_search, "find_careers", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    job, _ = run(acme_job(), web, cache)
    assert job.retry and job.status == NEEDS_REVIEW
    job, _ = run(acme_job(company=""), web, cache)
    assert not job.retry                                      # a real failure, not worth retrying
