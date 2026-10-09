"""Verification of one candidate: employer -> official site -> careers/ATS -> exact vacancy -> open status.
Anything uncertain ends as Needs Review; only fully evidenced vacancies become Verified."""
import logging
import re
from dataclasses import replace

import requests

import filters
from discovery.serpapi_search import BudgetExhausted, SerpApiAuthError, SerpApiError
from http_client import is_job_board, redact, registered_domain
from models import BUDGET_NOTE, CLOSED, FAIL, NEEDS_REVIEW, PASS, REJECTED, UNKNOWN, VERIFIED, Posting
from verification import application_status, ats_clients, careers_search, company_resolver, vacancy_matcher
from verification.ats_verifier import parse_ats_url, relationship, AtsRef

log = logging.getLogger(__name__)
_REF_NOTE = re.compile(r"\[ats (\w+):([\w.-]+):([\w-]+)\]")


def _set(job, status, reason):
    job.status = status
    job.notes.insert(0, reason)


def verify_job(job, serp, cache, stats) -> None:
    try:
        _verify(job, serp, cache, stats)
    except SerpApiAuthError:
        raise
    except BudgetExhausted:
        stats["budget_skipped"] = stats.get("budget_skipped", 0) + 1
        job.retry = True
        _set(job, NEEDS_REVIEW, BUDGET_NOTE)
    except SerpApiError as e:
        stats["errors"].append(f"{job.company}: {e}")
        job.retry = True
        _set(job, NEEDS_REVIEW, f"verification incomplete: {e}")
    except Exception as e:  # one bad candidate must not abort the run
        log.exception("verification error for %s / %s", job.company, job.title)
        stats["errors"].append(redact(f"{job.company} / {job.title}: {type(e).__name__}: {e}"))
        job.retry = True
        _set(job, NEEDS_REVIEW, f"verification error ({type(e).__name__}); check manually")


def _verify(job, serp, cache, stats):
    if not job.company:
        job.check("employer", FAIL, "employer could not be identified from the listing")
        return _set(job, NEEDS_REVIEW, "employer could not be identified from the listing")
    job.check("employer", PASS, f"named in listing: {job.company}", job.listing_url)
    site, why = company_resolver.resolve_official_site(job.company, serp, cache)
    if not site:
        job.check("official_site", FAIL, why)
        return _set(job, NEEDS_REVIEW, f"official website not established: {why}")
    job.ev(site.evidence)
    job.check("official_site", PASS, site.evidence, site.website)

    links = [u for u in dict.fromkeys(job.links + [job.listing_url]) if u and not is_job_board(u)]
    careers = careers_search.find_careers(site, links)
    job.evidence += careers.evidence
    job.careers_url = careers.careers_url
    if job.careers_url:
        stats["careers_pages"] += 1
        job.check("careers_page", PASS, "careers page on the official domain", job.careers_url)
    else:
        job.check("careers_page", FAIL, f"no careers page found on {site.domain}")
    if careers.boards:
        job.check("ats_link", PASS, "; ".join(f"{b.ats} board '{b.board}' linked from official site" for b in sorted(careers.boards, key=str)),
                  job.careers_url)

    posting, why = _locate(job, site, careers, links)
    if posting is None:
        job.checks.setdefault("ats_link", {"status": UNKNOWN, "detail": "no employer-linked ATS board or vacancy page", "url": ""})
        job.check("vacancy_match", FAIL if "not found" in why or "no vacancy" in why or "ambiguous" in why else UNKNOWN, why)
        return _set(job, NEEDS_REVIEW, why)
    job.ev(why)
    job.check("vacancy_match", PASS, why, posting.url)
    had_req = job.req_id
    if had_req and posting.req_id:
        job.check("requisition_id", PASS, f"listing and employer system agree: {posting.req_id}", posting.url)
    elif posting.req_id:
        job.check("requisition_id", PASS, f"from employer system: {posting.req_id}", posting.url)
    else:
        job.check("requisition_id", UNKNOWN, "no requisition ID published")
    job.closes = posting.valid_through or job.closes
    job.req_id = posting.req_id or job.req_id
    job.location = job.location or posting.location
    job.employment_type = job.employment_type or posting.employment_type
    job.posted_date = posting.posted_date or job.posted_date

    state, ev = application_status.check(posting)
    job.ev(ev)
    job.check("open_status", {application_status.OPEN: PASS, application_status.CLOSED: FAIL}.get(state, UNKNOWN), ev, posting.url)
    if state == application_status.CLOSED:
        return _set(job, CLOSED, f"vacancy closed per employer system: {ev}")
    if state == application_status.UNKNOWN:
        job.retry = "unreachable" in ev or "HTTP 5" in ev  # transient: try again in a later run
        return _set(job, NEEDS_REVIEW, f"could not confirm vacancy is open: {ev}")

    apply_ref = parse_ats_url(posting.url)
    employer_url = (registered_domain(posting.url) == site.domain
                    or bool(apply_ref and any(b.board_key == apply_ref.board_key for b in careers.boards)))
    if not employer_url or is_job_board(posting.url):
        job.check("apply_url", FAIL, "apply URL is not on a verified employer domain/board", posting.url)
        return _set(job, NEEDS_REVIEW, f"apply URL {posting.url} is not on a verified employer domain/board")
    job.check("apply_url", PASS, "direct vacancy URL on the employer's domain or verified ATS board", posting.url)

    if posting.description and posting.description not in job.description:
        job.description = f"{posting.description}\n{job.description}"
    desc = job.description
    verdict, summary = filters.experience_check(desc)
    job.experience = summary
    job.check("experience", {filters.ELIGIBLE: PASS, filters.TOO_SENIOR: FAIL}.get(verdict, UNKNOWN), summary)
    if verdict == filters.TOO_SENIOR:
        return _set(job, REJECTED, filters.contradiction(job.title, verdict, summary) or f"experience: {summary}")
    loc_ok, loc_why = filters.location_check(posting.location or job.location, desc, posting.remote or job.remote)
    job.check("location", PASS if loc_ok else FAIL, loc_why)
    if not loc_ok:
        return _set(job, REJECTED, f"location: {loc_why}")
    if verdict != filters.ELIGIBLE:
        return _set(job, NEEDS_REVIEW, f"employer posting verified open at {posting.url}, but {summary}; confirm eligibility manually")

    job.apply_url = posting.url
    if apply_ref and not apply_ref.board:
        job.note(f"[ats {posting.ats}:{_board_for(apply_ref, careers)}:{posting.req_id}]")
    _set(job, VERIFIED, "employer, vacancy and open status verified")


def _board_for(ref, careers):
    gh = [b for b in careers.boards if b.ats == ref.ats]
    return gh[0].board if len(gh) == 1 else ""


def _locate(job, site, careers, links):
    """(Posting, reason) for the exact vacancy in an employer-controlled system, or (None, reason)."""
    for url in links:
        ref = parse_ats_url(url)
        if not ref and registered_domain(url) != site.domain:
            continue
        trusted, ev = relationship(ref, url, site.domain, careers.boards)
        job.ev(ev)
        if trusted:
            job.check("ats_link", PASS, ev, url)
        elif "ats_link" not in job.checks:
            job.check("ats_link", FAIL, ev, url)
        if not trusted:
            continue
        if ref and ref.ats == "greenhouse" and not ref.board:      # ?gh_jid= embed on the official site
            board = _board_for(ref, careers)
            if not board:
                job.ev("cannot resolve which Greenhouse board serves the embedded vacancy")
                continue
            ref = replace(ref, board=board)
        if ref and ref.job_id:
            try:
                p = ats_clients.fetch_posting(ref)
            except ValueError as e:
                job.ev(str(e))
                continue
            if p is None:
                return Posting(ats=ref.ats, url=url, title=job.title, active=False,
                               evidence=[f"{ref.ats} board '{ref.board}' no longer lists vacancy {ref.job_id}"]), \
                    "listing's own employer link points at a withdrawn vacancy"
        elif not ref:
            p = ats_clients.fetch_official_page_posting(url)
            if p is None:
                job.ev(f"{url}: no schema.org JobPosting data to confirm the vacancy")
                continue
            if p.active is False and not p.title:
                return p, f"official vacancy page {url} is gone"
        else:
            continue
        ok, why = vacancy_matcher.match(job, p)
        job.ev(why)
        if ok:
            return p, why

    for board in sorted(careers.boards, key=str):
        try:
            postings = ats_clients.list_board(board, job.title)
        except (requests.RequestException, PermissionError, ValueError) as e:
            job.ev(f"{board.ats} board '{board.board}' not searchable: {e}")
            continue
        p, why = vacancy_matcher.find_in_board(job, postings)
        job.ev(f"{board.ats} board '{board.board}': {why}")
        if p and not p.description and p.req_id:
            detail = ats_clients.fetch_posting(ats_clients.detail_ref(board, p))
            if detail is None or not vacancy_matcher.match(job, detail)[0]:
                continue
            p = detail
        if p:
            return p, why

    if not careers.careers_url and not careers.boards:
        return None, f"no careers page or ATS link found on official domain {site.domain}"
    if not careers.boards:
        return None, "careers page found, but no verifiable vacancy page or linked ATS board"
    return None, "vacancy not found on the employer's verified ATS board(s)"


def recheck(apply_url: str, notes: str = "") -> tuple:
    """Re-verify a previously Verified vacancy without SerpApi. Returns (state, evidence)."""
    ref = parse_ats_url(apply_url)
    m = _REF_NOTE.search(notes or "")
    if m:
        ref = AtsRef(m.group(1), m.group(2), m.group(3), url=apply_url)
    try:
        if ref and ref.board and ref.job_id:
            p = ats_clients.fetch_posting(ref)
            if p is None:
                return application_status.CLOSED, f"{ref.ats} no longer lists vacancy {ref.job_id}"
        elif not ref:
            p = ats_clients.fetch_official_page_posting(apply_url)
            if p is None:
                return application_status.UNKNOWN, "no JobPosting data on official page"
        else:
            return application_status.UNKNOWN, "cannot identify vacancy in ATS"
        return application_status.check(p)
    except (requests.RequestException, PermissionError, ValueError) as e:
        return application_status.UNKNOWN, redact(f"recheck failed: {type(e).__name__}")
