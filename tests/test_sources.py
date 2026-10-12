"""Source-priority discovery: providers, normalisation, caching, dedupe across sources, evidence rules, cron.
All HTTP and SerpApi traffic is faked (tests/conftest.py also blocks the network)."""
import json
import threading
import time
from datetime import date, timedelta

import pytest

import filters
import http_client
import main
from discovery import ats_boards, company_pages, platform_search, sources
from models import NEEDS_REVIEW, VERIFIED, Job
from storage.deduplication import dedupe
from tests.test_verification import FakeSerp, FakeWeb
from verification import ats_clients, company_resolver, pipeline
from verification.ats_verifier import AtsRef

TODAY = date(2026, 10, 12)
SITE = company_resolver.OfficialSite("Acme Analytics", "https://www.acmeanalytics.com/", "acmeanalytics.com",
                                     "Google Knowledge Graph entry 'Acme Analytics' lists official website https://www.acmeanalytics.com/")
HOME, CAREERS = "https://www.acmeanalytics.com/", "https://www.acmeanalytics.com/careers"
GH_BOARD_API = "https://boards-api.greenhouse.io/v1/boards/acmeanalytics/jobs?content=true"


def gh(id_, title, loc="Pune, India"):
    return {"id": id_, "title": title, "location": {"name": loc}, "content": "Freshers welcome, 0-1 years.",
            "absolute_url": f"https://boards.greenhouse.io/acmeanalytics/jobs/{id_}", "updated_at": "2026-10-10"}


def ld(*postings):
    return "".join(f'<script type="application/ld+json">{json.dumps(p)}</script>' for p in postings)


def jp(title, url, valid="2026-12-31", city="Pune"):
    return {"@type": "JobPosting", "title": title, "url": url, "validThrough": valid, "datePosted": "2026-10-09",
            "description": "Fresher graduates welcome", "hiringOrganization": {"name": "Acme Analytics"},
            "jobLocation": {"address": {"addressLocality": city, "addressCountry": "IN"}}}


@pytest.fixture(autouse=True)
def profile():
    saved = filters.PROFILE
    filters.set_profile(["Pune"], "any", ["Data Analyst"])
    yield
    filters.PROFILE = saved


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
    return company_resolver.CompanyCache(tmp_path / "c.json")


# ---------- company career pages ----------
def test_careers_page_links_employer_ats_board_and_is_cached(web, cache):
    web.pages = {HOME: (200, '<a href="/careers">Careers</a>'),
                 CAREERS: (200, '<a href="https://boards.greenhouse.io/acmeanalytics">Open roles</a>')}
    web.api = {GH_BOARD_API: {"jobs": [gh(1, "Data Analyst"), gh(2, "Senior Data Engineer"), gh(3, "Data Analyst", "Austin, US")]}}
    stats = {"errors": []}
    [j] = company_pages.company_jobs(SITE, cache, stats, ["Data Analyst"], TODAY)
    assert (j.title, j.listing_url) == ("Data Analyst", "https://boards.greenhouse.io/acmeanalytics/jobs/1")
    assert j.source == "Greenhouse via official careers page (acmeanalytics.com)"
    assert "official careers page of acmeanalytics.com" in j.evidence[0] and "Knowledge Graph" in j.evidence[0]
    entry = cache.data["careers|acmeanalytics.com"]
    assert entry["careers_url"] == CAREERS and entry["boards"][0]["board"] == "acmeanalytics"
    assert set(entry) == {"careers_url", "boards", "evidence", "checked"}        # public company data only
    # cache hit: the careers page isn't crawled again
    hits = len(web.page_hits)
    company_pages.company_jobs(SITE, cache, stats, ["Data Analyst"], TODAY + timedelta(days=3))
    assert len(web.page_hits) == hits
    # expired (CAREERS_TTL_DAYS, default 7): crawled again
    company_pages.company_jobs(SITE, cache, stats, ["Data Analyst"], TODAY + timedelta(days=8))
    assert len(web.page_hits) > hits and stats["errors"] == []


def test_official_jsonld_vacancies_pagination_and_closed(web, cache):
    page2 = CAREERS + "?page=2"
    web.pages = {HOME: (200, '<a href="/careers">Careers</a>'),
                 CAREERS: (200, ld(jp("Data Analyst", HOME + "jobs/da-pune-101"), jp("Data Analyst Trainee", HOME + "jobs/old-1", valid="2026-01-01"))
                           + f'<link rel="next" href="{page2}"><a href="/jobs/data-analyst-intern-2026">Intern</a>'),
                 page2: (200, ld(jp("Junior Data Analyst", HOME + "jobs/jda-77"))),
                 HOME + "jobs/data-analyst-intern-2026": (200, ld(jp("Data Analyst", "https://evil.example/x", city="Pune")))}
    stats = {"errors": []}
    jobs = company_pages.company_jobs(SITE, cache, stats, ["Data Analyst"], TODAY)
    urls = sorted(j.listing_url for j in jobs)
    assert HOME + "jobs/da-pune-101" in urls and HOME + "jobs/jda-77" in urls                 # rel=next page followed
    assert not any("old-1" in u for u in urls) and stats["closed_skipped"] >= 1                # expired: not a candidate
    assert not any("evil.example" in u for u in urls)          # a posting URL off the official domain isn't trusted
    assert all(j.source.startswith("Company website via official careers page") for j in jobs)


def test_careers_page_redirecting_off_the_official_domain_is_not_used(web, cache):
    web.pages = {HOME: (200, '<a href="/careers">Careers</a>'),
                 CAREERS: (200, ld(jp("Data Analyst", "https://other.example/1")), "https://other.example/careers")}
    assert company_pages.company_jobs(SITE, cache, {"errors": []}, ["Data Analyst"], TODAY) == []


def test_seeds_from_cache_and_preferred_companies(cache):
    cache.put("acme analytics", {"website": HOME, "domain": "acmeanalytics.com", "checked": TODAY.isoformat(), "evidence": SITE.evidence})
    cache.put("beta", {"website": "https://beta.io/", "domain": "beta.io", "checked": TODAY.isoformat(), "evidence": "x"})
    cache.put("careers|beta.io", {"careers_url": "", "boards": [], "checked": TODAY.isoformat()})
    cache.put("nowebsite", {"reason": "no Google Knowledge Graph entry", "checked": TODAY.isoformat()})
    serp = FakeSerp(kg={"title": "Gamma Corp", "website": "https://gamma.com/"})
    sites = company_pages.seeds(cache, ["Gamma Corp", "Delta Ltd"], serp, {"errors": []}, TODAY, resolve_limit=1)
    names = [s.domain for s in sites]
    assert names == ["gamma.com", "acmeanalytics.com", "beta.io"]   # preferred first, then never-crawled, then oldest crawl
    assert sites[1].company == "Acme Analytics" and serp.calls == 1   # resolve limit: Delta not looked up this run
    serp2 = FakeSerp()
    company_pages.seeds(cache, [], serp2, {"errors": []}, TODAY)
    assert serp2.calls == 0                                            # cached employers never cost a search


# ---------- LinkedIn / Naukri (Google results only) ----------
def test_linkedin_result_normalisation():
    r = {"title": "Acme Analytics hiring Data Analyst in Pune, Maharashtra, India | LinkedIn",
         "link": "https://in.linkedin.com/jobs/view/data-analyst-at-acme-analytics-3912345678?trk=public_jobs&refId=abc",
         "snippet": "Freshers can apply. 0-1 years.", "date": "2 days ago"}
    j = platform_search.parse_result("linkedin", r)
    assert (j.title, j.company, j.location) == ("Data Analyst", "Acme Analytics", "Pune, Maharashtra, India")
    assert j.listing_url == "https://www.linkedin.com/jobs/view/data-analyst-at-acme-analytics-3912345678"
    assert j.source == "LinkedIn (via Google search)" and j.posted_date is not None
    assert sources.source_id(j.listing_url) == "linkedin:3912345678" and "Search snippet:" in j.description
    # a profile page or an unparseable title is skipped, never guessed
    assert platform_search.parse_result("linkedin", {"title": "Asha - Recruiter - LinkedIn", "link": "https://in.linkedin.com/in/asha"}) is None
    assert platform_search.parse_result("linkedin", {"title": "Jobs in Pune", "link": "https://www.linkedin.com/jobs/view/123456789"}) is None


def test_naukri_result_normalisation_and_experience():
    r = {"title": "Graduate Engineer Trainee - Beta Systems - 0 to 1 years - Pune - Naukri.com",
         "link": "https://www.naukri.com/job-listings-graduate-engineer-trainee-beta-systems-pune-0-to-1-years-101024012345?src=jobsearchDesk"}
    j = platform_search.parse_result("naukri", r)
    assert (j.title, j.company, j.location) == ("Graduate Engineer Trainee", "Beta Systems", "Pune")
    assert "?src" not in j.listing_url and sources.source_id(j.listing_url) == "naukri:101024012345"
    assert filters.experience_check(j.description)[0] == filters.ELIGIBLE
    senior = platform_search.parse_result("naukri", {**r, "title": "Data Analyst - Beta Systems - 3 to 5 years - Pune - Naukri.com"})
    assert filters.experience_check(senior.description)[0] == filters.TOO_SENIOR     # fresher filter applies
    assert platform_search.parse_result("naukri", {"title": "Data Analyst Jobs", "link": "https://www.naukri.com/data-analyst-jobs"}) is None


def test_platform_queries_follow_user_settings_and_limits():
    q = platform_search.queries("linkedin", ["Python Developer", "Data Analyst"], ["Nashik", "Pune"], "any", limit=3)
    assert len(q) == 3 and all(x[1].startswith("site:linkedin.com/jobs/view") for x in q)
    assert '"Python Developer" Nashik' in q[0][1] and q[-1][2] is True              # remote lane included
    assert all(not wfh for _, _, wfh in platform_search.queries("naukri", ["QA Engineer"], ["Pune"], "onsite", 5))
    serp = FakeSerp()
    serp.search = lambda **p: (setattr(serp, "params", p), {"organic_results": []})[1]
    platform_search.search(serp, "naukri", "q", max_age_days=7)
    assert serp.params["tbs"] == "qdr:w" and serp.params["engine"] == "google"


# ---------- ATS adapters ----------
def test_each_ats_adapter_normalises_and_paginates(monkeypatch):
    calls = []
    sr_pages = {0: {"content": [{"id": str(i), "name": "Data Analyst", "location": {"city": "Pune"}} for i in range(100)], "totalFound": 130},
                100: {"content": [{"id": str(i), "name": "Data Analyst", "location": {"city": "Pune"}} for i in range(100, 130)], "totalFound": 130}}

    def get_json(url, **kw):
        calls.append(url)
        if "greenhouse" in url:
            return {"jobs": [gh(9, "Data Analyst")]}
        if "lever.co" in url:
            return [{"id": "lv1", "text": "Data Analyst", "hostedUrl": "https://jobs.lever.co/acme/lv1", "categories": {"location": "Pune"}}]
        if "ashbyhq" in url:
            return {"jobs": [{"id": "ab1", "title": "Data Analyst", "jobUrl": "https://jobs.ashbyhq.com/acme/ab1", "location": "Pune", "isListed": False}]}
        if "smartrecruiters" in url:
            return sr_pages[int(url.split("offset=")[1].split("&")[0])]
        return None

    def post_json(url, payload, **kw):
        calls.append(payload["offset"])
        n = 20 if payload["offset"] == 0 else 5
        return {"total": 25, "jobPostings": [{"title": "Data Analyst", "externalPath": f"/job/Pune/DA_R{payload['offset'] + i}", "locationsText": "Pune"} for i in range(n)]}
    monkeypatch.setattr(http_client, "get_json", get_json)
    monkeypatch.setattr(http_client, "post_json", post_json)
    assert ats_clients.list_board(AtsRef("greenhouse", "acme"))[0].req_id == "9"
    assert ats_clients.list_board(AtsRef("lever", "acme"))[0].url == "https://jobs.lever.co/acme/lv1"
    assert ats_clients.list_board(AtsRef("ashby", "acme"))[0].active is False                       # unlisted = closed
    assert len(ats_clients.list_board(AtsRef("smartrecruiters", "acme"), "Data Analyst")) == 130   # 2 pages
    wd = ats_clients.list_board(AtsRef("workday", "acme", site="Ext", host="acme.wd5.myworkdayjobs.com"), "Data Analyst")
    assert len(wd) == 25 and wd[-1].req_id == "R24" and calls[-2:] == [0, 20]
    with pytest.raises(ats_clients.UnsupportedBoard):
        ats_clients.list_board(AtsRef("jobvite", "acme"))


def test_unsupported_board_is_not_an_error_and_board_terms_follow_user_roles(monkeypatch):
    stats = {"errors": []}
    assert ats_boards.board_jobs({"company": "J", "ats": "jobvite", "board": "j"}, stats) == []
    assert stats["errors"] == [] and "no public job-board API" in stats["unsupported"][0]
    seen = []
    monkeypatch.setattr(ats_boards.ats_clients, "list_board", lambda ref, term: (seen.append(term), [])[1])
    filters.set_profile(["Pune"], "any", ["Python Developer"])
    ats_boards.board_jobs({"company": "N", "ats": "workday", "board": "n", "host": "n.wd1.myworkdayjobs.com", "site": "x"}, stats)
    assert seen == ["Python Developer"]                     # the user's role, not the global data-role default


# ---------- orchestration: priority, budget, concurrency, failures, time limit ----------
@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setattr(main, "STOP", False)
    monkeypatch.setenv("RUN_TIME_LIMIT", "0")
    monkeypatch.setattr(main.ats_boards, "load_boards", lambda path: [])
    monkeypatch.setattr(main.query_builder, "build", lambda *a: [(f"g{i}", "India", False) for i in range(10)])
    monkeypatch.setattr(main, "google_jobs", lambda serp, q, where, wfh: [q])
    monkeypatch.setattr(main.platform_search, "search", lambda serp, plat, q, wfh, age: [f"{plat}:{q[:4]}"])
    return monkeypatch


def test_paid_budget_is_shared_round_robin_and_order_is_priority(providers):
    providers.setenv("DISCOVERY_PROVIDERS", "google_jobs,linkedin,naukri")
    stats = {"errors": []}
    raw = main.discover(None, stats, budget=4)
    assert raw == ["g0", "linkedin:site", "naukri:site", "g1"]      # every paid source gets an early slot
    assert stats["providers"]["google_jobs"]["tasks"] == 2 and stats["providers"]["linkedin"]["tasks"] == 1
    providers.setenv("DISCOVERY_PROVIDERS", "naukri,google_jobs,bogus")
    assert main.discover(None, {"errors": []}, budget=2) == ["naukri:site", "g0"]   # configurable order; unknown ignored


def test_one_failing_provider_does_not_lose_the_others(providers):
    providers.setenv("DISCOVERY_PROVIDERS", "google_jobs,linkedin")
    providers.setattr(main.platform_search, "search", lambda *a: 1 / 0)
    stats = {"errors": []}
    raw = main.discover(None, stats, budget=3)
    assert raw == ["g0", "g1"] and stats["providers"]["linkedin"]["errors"] == 1
    assert any("linkedin: ZeroDivisionError" in e for e in stats["errors"])


def test_bounded_concurrency_and_partial_results_on_time_limit(providers):
    providers.setenv("DISCOVERY_PROVIDERS", "google_jobs")
    providers.setenv("DISCOVERY_CONCURRENCY", "2")
    live, peak, lock = [0], [0], threading.Lock()

    def slow(serp, q, where, wfh):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05 if q != "g3" else 2)
        with lock:
            live[0] -= 1
        return [q]
    providers.setattr(main, "google_jobs", slow)
    assert len(main.discover(None, {"errors": []}, budget=6)) == 6 and peak[0] == 2
    providers.setenv("RUN_TIME_LIMIT", "2")           # discovery share = 0.8 s: g3 can't finish
    providers.setattr(main, "RUN_STARTED", time.monotonic())
    stats = {"errors": []}
    raw = main.discover(None, stats, budget=6)
    assert "g3" not in raw and raw and stats["discovery_truncated"] is True
    assert main.run_status(stats) == "partial (search time limit)"


def test_polite_throttle_spaces_requests_per_host_across_threads(monkeypatch):
    monkeypatch.setattr(http_client, "POLITE_SECONDS", 0.1)
    monkeypatch.setattr(http_client, "_last_hit", {})
    stamps = []
    ts = [threading.Thread(target=lambda: (http_client._polite("a.com"), stamps.append(time.monotonic()))) for _ in range(3)]
    t0 = time.monotonic()
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert max(stamps) - t0 >= 0.19                          # 3 requests to one host: at least 2 gaps
    t1 = time.monotonic()
    http_client._polite("b.com")
    assert time.monotonic() - t1 < 0.05                      # another host isn't held up


# ---------- canonical URLs, provenance, dedupe ----------
def test_canonical_url_drops_tracking_but_keeps_vacancy_parameters():
    assert sources.canonical_url("HTTPS://Acme.com/careers/job/?gh_jid=4001&utm_source=x&token=abc#apply") == \
        "https://acme.com/careers/job?gh_jid=4001&token=abc"
    assert sources.canonical_url("https://in.linkedin.com/jobs/view/123456789/?trk=x") == "https://www.linkedin.com/jobs/view/123456789"
    assert sources.source_id("https://boards.greenhouse.io/acme/jobs/77") == "greenhouse:acme:77"
    assert sources.source_id("https://www.linkedin.com/jobs/search?currentJobId=3912345678") == "linkedin:3912345678"
    assert sources.source_id("https://acme.com/about") == ""


def test_source_labels_and_configurable_tiers(monkeypatch):
    assert [sources.label(u) for u in ("https://jobs.lever.co/a/1", "https://www.naukri.com/job-listings-x-123456789012",
                                       "https://acme.com/jobs/1", "https://jooble.org/x")] == ["Lever", "Naukri", sources.COMPANY, "Other job site"]
    assert [sources.tier(u) for u in ("https://acme.com/j", "https://www.linkedin.com/jobs/view/1", "https://jooble.org/x")] == [1, 2, 3]
    monkeypatch.setenv("SOURCE_TIERS", '{"Naukri": 3}')
    assert sources.tier("https://www.naukri.com/job-listings-x-123456789012") == 3
    monkeypatch.setenv("SOURCE_TIERS", "not json")
    assert sources.tier("https://www.naukri.com/job-listings-x-123456789012") == 2          # bad override: defaults


def test_same_vacancy_across_sources_becomes_one_job_with_official_url():
    li = Job("Data Analyst", "Acme Analytics", "Pune", listing_url="https://www.linkedin.com/jobs/view/3912345678",
             links=["https://www.linkedin.com/jobs/view/3912345678"], source="LinkedIn (via Google search)")
    nk = Job("Data Analyst", "Acme Analytics Pvt Ltd", "Pune, Maharashtra", listing_url="https://www.naukri.com/job-listings-da-101024012345",
             links=["https://www.naukri.com/job-listings-da-101024012345"], source="Naukri (via Google search)")
    co = Job("Data Analyst", "Acme Analytics", "Pune", listing_url="https://boards.greenhouse.io/acme/jobs/1", req_id="1",
             links=["https://boards.greenhouse.io/acme/jobs/1"], source="Greenhouse via official careers page (acme.com)")
    [one], merged = dedupe([li, nk, co])
    assert merged == 2 and one.listing_url == "https://boards.greenhouse.io/acme/jobs/1"       # official URL is canonical
    assert {s["label"] for s in sources.provenance(one)} == {"Greenhouse", "LinkedIn", "Naukri"}
    assert sources.provenance(one)[0]["label"] == "Greenhouse"


def test_different_requisitions_are_not_merged_and_verified_copy_wins():
    a = Job("Data Analyst", "Acme", "Pune", req_id="R1", listing_url="https://acme.com/j/R1")
    b = Job("Data Analyst", "Acme", "Pune", req_id="R2", listing_url="https://acme.com/j/R2")
    assert len(dedupe([a, b])[0]) == 2
    weak = Job("Data Analyst", "Acme", "Pune", status=NEEDS_REVIEW, listing_url="https://boards.greenhouse.io/acme/jobs/5")
    strong = Job("Data Analyst", "Acme", "Pune", status=VERIFIED, listing_url="https://www.linkedin.com/jobs/view/123456789",
                 apply_url="https://boards.greenhouse.io/acme/jobs/5")
    [kept], _ = dedupe([weak, strong])
    assert kept.status == VERIFIED and kept.apply_url.endswith("/5")     # weaker evidence never replaces stronger
    assert kept.listing_url == "https://boards.greenhouse.io/acme/jobs/5"


# ---------- evidence rules ----------
def test_platform_listing_alone_is_never_verified(web, cache):
    """A LinkedIn result with no employer evidence stays Needs Review: a snippet/listing is not proof."""
    j = platform_search.parse_result("linkedin", {"title": "Acme Analytics hiring Data Analyst in Pune | LinkedIn",
                                                  "link": "https://www.linkedin.com/jobs/view/3912345678"})
    stats = {"errors": [], "careers_pages": 0}
    pipeline.verify_job(j, FakeSerp(), cache, stats)                 # no Knowledge Graph entry for the employer
    assert j.status == NEEDS_REVIEW and j.apply_url == ""
    j2 = platform_search.parse_result("linkedin", {"title": "Acme Analytics hiring Data Analyst in Pune | LinkedIn",
                                                   "link": "https://www.linkedin.com/jobs/view/3912345678"})
    pipeline.verify_job(j2, FakeSerp(kg={"title": "Acme Analytics", "website": HOME}), cache, stats)
    assert j2.status == NEEDS_REVIEW                                # official site known, but no vacancy in its systems


def test_dashboard_source_info_uses_evidence_not_labels():
    from routes.jobs import source_info
    li = {"label": "LinkedIn", "url": "https://www.linkedin.com/jobs/view/1", "tier": 2, "id": "linkedin:1"}
    lookalike = {"label": sources.COMPANY, "url": "https://acme-jobs.example/1", "tier": 1, "id": ""}
    row = {"Verification Status": "Needs Review", "Original Listing URL": lookalike["url"]}
    info = source_info(row, {"sources": [lookalike, li], "official_site": {"status": "pass", "url": "https://www.acme.com/"}})
    assert info["official_posting"] is False and info["sources"][0]["label"] == "Other site (unconfirmed)"
    assert info["official_site"] == "https://www.acme.com/" and info["supplementary"] is False
    ok = source_info({"Verification Status": "Needs Review"}, {"vacancy_match": {"status": "pass"},
                                                               "sources": [{"label": "Greenhouse", "url": "https://boards.greenhouse.io/a/jobs/1", "tier": 1, "id": ""}]})
    assert ok["official_posting"] is True and ok["source_label"] == "Greenhouse"
    legacy = source_info({"Verification Status": "Needs Review", "Original Listing URL": "https://jooble.org/x"}, {})
    assert legacy["sources"][0]["label"] == "Other job site" and legacy["supplementary"] is True
    assert source_info({"Verification Status": "Needs Review"}, {"official_site": {"status": "fail", "url": "https://x.com"}})["official_site"] == ""


def test_verification_record_stores_provenance():
    j = Job("Data Analyst", "Acme", "Pune", listing_url="https://www.linkedin.com/jobs/view/123456789?trk=a",
            links=["https://boards.greenhouse.io/acme/jobs/9"], status=NEEDS_REVIEW)
    rec = main.verification_record(j, "run1", "2026-10-12 08:00")
    assert [s["label"] for s in rec["Checks"]["sources"]] == ["Greenhouse", "LinkedIn"]
    assert rec["Checks"]["sources"][1]["url"] == "https://www.linkedin.com/jobs/view/123456789"
    j.links.append("https://in.linkedin.com/jobs/view/data-analyst-at-acme-123456789")     # same posting, other URL shape
    assert len(sources.provenance(j)) == 2


# ---------- cron ----------
def test_cron_runs_each_user_fairly_within_the_time_budget(monkeypatch):
    from routes import run
    seen, now = [], [0.0]

    def fake_run_job(argv):
        seen.append((argv[argv.index("--user-id") + 1], run.os.environ["RUN_TIME_LIMIT"]))
        now[0] += 100                                   # each search takes 100 s
        return (0 if len(seen) == 1 else 3), ""
    monkeypatch.setattr(run, "run_job", fake_run_job)
    monkeypatch.setenv("RUN_TIME_LIMIT", "240")
    out = run.cron_all_users(["u1-aaaaaaaa", "u2-bbbbbbbb", "u3-cccccccc", "u4-dddddddd"], clock=lambda: now[0])
    assert [u for u, _ in seen] == ["u1-aaaaaaaa", "u2-bbbbbbbb", "u3-cccccccc"]     # in the given (fairness) order
    assert [lim for _, lim in seen] == ["110", "110", "70"]          # own slice each; the last one gets what's left
    assert [o["status"] for o in out] == ["ok", "skipped (another run in progress)", "skipped (another run in progress)",
                                          "deferred to next slot"]                       # 270 - 300 s < 60 s: next slot
    assert all("@" not in o["user"] for o in out) and run.os.environ["RUN_TIME_LIMIT"] == "240"   # restored
    monkeypatch.setattr(run, "run_job", lambda argv: 1 / 0)
    assert run.cron_all_users(["u1"], clock=lambda: 0)[0]["status"] == "failed (ZeroDivisionError)"


def test_cron_endpoint_authorised_path_in_multi_user_mode(monkeypatch):
    from routes import run
    from storage import backend
    from tests.test_vercel import call
    monkeypatch.setenv("CRON_SECRET", "s" * 32)
    monkeypatch.setattr(backend, "is_pg", lambda: True)
    monkeypatch.setattr(run, "cron_all_users", lambda: [{"user": "u1", "status": "ok"}])
    assert call(run.handler, {"Authorization": "Bearer wrong"})[0] == 401
    code, body = call(run.handler, {"Authorization": "Bearer " + "s" * 32})
    assert code == 200 and body == {"runs": [{"user": "u1", "status": "ok"}]}


def test_listing_experience_is_shown_even_when_not_verified(monkeypatch):
    """A Needs Review job shows the experience its listing states (e.g. Naukri's '0 to 1 years'), not 'Not stated'."""
    j = platform_search.parse_result("naukri", {"title": "Junior Data Analyst - Beta - 0 to 1 years - Pune - Naukri.com",
                                                "link": "https://www.naukri.com/job-listings-jda-beta-pune-101024012345"})
    verdict, summary = filters.experience_check(j.description)
    assert verdict == filters.ELIGIBLE and summary and "not stated" not in summary.lower()


def test_rediscovery_fills_experience_placeholder_only():
    from integrations.google_sheets import C, HEADERS, plan_sync
    row = [""] * len(HEADERS)
    j = Job("Junior Data Analyst", "Beta", "Pune", listing_url="https://www.naukri.com/job-listings-x-101024012345", status=NEEDS_REVIEW)
    j.experience = "0-1 years"
    from storage.deduplication import job_id
    for current, expect in (("Not stated", True), ("2 years (edited)", False)):
        row[C["Job ID"]], row[C["Experience Requirement"]], row[C["Verification Status"]] = job_id(j), current, NEEDS_REVIEW
        _, updates, _ = plan_sync([HEADERS, list(row)], [j], {}, "2026-10-12 08:00")
        got = [u["values"][0][0] for u in updates if u["range"].startswith(chr(ord("A") + C["Experience Requirement"]))]
        assert (got == ["0-1 years"]) is expect
