"""Company-originated discovery: vacancies published by employers on their own careers pages and on the ATS
boards those pages link to. No job board is involved.

1. Employers ("seeds"): the user's preferred companies (Settings → prefer) and every employer whose official
   website is already established in the company cache (Google Knowledge Graph / Wikidata evidence, see
   verification/company_resolver.py). The list grows by itself as searches resolve new employers.
2. Careers page: found on the official domain by verification/careers_search.py (same code verification uses),
   together with the ATS boards that page links to. Cached per domain for CAREERS_TTL_DAYS in the shared
   company cache (public company data only - never user data).
3. Vacancies: only from those employer-linked ATS board APIs, or schema.org JobPosting markup on official-domain
   pages (the careers page, up to MAX_LISTING_PAGES rel="next" pages, and up to MAX_VACANCY_PAGES linked
   vacancy pages). A link is never turned into a job by guessing.

Every job found here still goes through verification/pipeline.py like any other candidate."""
import logging
import os
import re
from dataclasses import asdict
from datetime import date
from urllib.parse import urljoin, urlparse

import requests

import filters
import http_client
from discovery import sources
from discovery.serpapi_search import SerpApiAuthError, SerpApiError
from http_client import registered_domain
from models import Job
from verification import ats_clients, careers_search, company_resolver
from verification.ats_verifier import AtsRef

log = logging.getLogger(__name__)
MAX_LISTING_PAGES = 3
MAX_VACANCY_PAGES = 10
_VACANCY_PATH = re.compile(r"/(jobs?|careers?|openings?|positions?|vacanc\w*|opportunit\w*)/[^?#]*[\w-]{6,}", re.I)
_NEXT = re.compile(r"""<(?:link|a)\b[^>]*rel=["']next["'][^>]*href=["']([^"'#]+)["']""", re.I)
_HREF = re.compile(r"""<a\b[^>]*href=["']([^"'#]+)["']""", re.I)


def ttl_days() -> int:
    return max(1, int(os.environ.get("CAREERS_TTL_DAYS", "7") or 7))


def per_run() -> int:
    return max(0, int(os.environ.get("COMPANY_PAGES_PER_RUN", "8") or 8))


def careers_key(domain: str) -> str:
    return f"careers|{domain}"


def seeds(cache, prefer, serp, stats, today: date | None = None, resolve_limit=3) -> list:
    """Employers with an established official website, least recently crawled first (so successive runs
    continue where the previous one stopped). Preferred companies first; resolving one that isn't cached
    costs one SerpApi search (at most resolve_limit per run)."""
    today = today or date.today()
    sites, resolved = {}, 0
    for name in prefer:
        key = company_resolver.normalize_company(name)
        if not key or key in sites:
            continue
        if cache.get(key, today) is None:
            if resolved >= resolve_limit or serp is None:
                continue
            resolved += 1
        try:
            site, _ = company_resolver.resolve_official_site(name, serp, cache, today)
        except SerpApiAuthError:
            raise
        except SerpApiError as e:
            stats["errors"].append(f"company lookup {name}: {e}")
            continue
        if site:
            sites[key] = (0, "", site)
    for key, e in list(cache.data.items()):
        if "|" in key or key in sites or not e.get("domain") or cache.get(key, today) is None:
            continue
        crawled = (cache.data.get(careers_key(e["domain"])) or {}).get("checked", "")
        name = re.search(r"entry '([^']+)'", e.get("evidence", ""))      # the employer's name as Google shows it
        sites[key] = (1, crawled, company_resolver.OfficialSite(name.group(1) if name else key.title(), e["website"],
                                                               e["domain"], e.get("evidence", "")))
    return [t[2] for t in sorted(sites.values(), key=lambda t: t[:2])]


def careers_info(site, cache, today: date | None = None) -> dict:
    """{careers_url, boards: [AtsRef fields], evidence, checked}, cached per official domain."""
    today = today or date.today()
    key = careers_key(site.domain)
    hit = cache.get(key, today, ttl=ttl_days())
    if hit is None:
        c = careers_search.find_careers(site)
        hit = {"careers_url": c.careers_url, "boards": [asdict(b) for b in sorted(c.boards, key=str)],
               "evidence": c.evidence[:10], "checked": today.isoformat()}
        cache.put(key, hit)
    return hit


def _official_pages(site, careers_url) -> list:
    """JobPosting markup on the careers page, its rel=next pages and linked vacancy pages (official domain only)."""
    postings, pages, seen = [], [careers_url], set()
    vacancy_links = []
    while pages and len(seen) < MAX_LISTING_PAGES:
        url = pages.pop(0)
        if url in seen or registered_domain(url) != site.domain:
            continue
        seen.add(url)
        r = http_client.get_page(url)
        if r.status_code != 200 or registered_domain(r.url) != site.domain:
            continue
        postings += ats_clients.parse_jsonld_postings(r.text, r.url)
        pages += [urljoin(r.url, h) for h in _NEXT.findall(r.text)]
        for h in _HREF.findall(r.text):
            link = urljoin(r.url, h.strip())
            if registered_domain(link) == site.domain and _VACANCY_PATH.search(urlparse(link).path) and link not in vacancy_links:
                vacancy_links.append(link)
    have = {p.url for p in postings}
    for link in [u for u in vacancy_links if u not in have and u not in seen][:MAX_VACANCY_PAGES]:
        try:
            p = ats_clients.fetch_official_page_posting(link)
        except (requests.RequestException, PermissionError):
            continue
        if p and p.title:
            postings.append(p)
    return postings


def vacancies(site, info, terms) -> list:
    """Postings from the employer-linked ATS boards, else from official-domain JobPosting markup."""
    out = []
    for b in info.get("boards") or []:
        ref = AtsRef(**b)
        for term in terms if ref.ats in ("workday", "smartrecruiters") else ("",):
            out += ats_clients.list_board(ref, term)
    if not info.get("boards") and info.get("careers_url"):
        out += _official_pages(site, info["careers_url"])
    return out


def company_jobs(site, cache, stats, terms, today: date | None = None) -> list:
    """Relevant, still-listed vacancies for one employer as Job candidates (unverified)."""
    try:
        info = careers_info(site, cache, today)
        postings = vacancies(site, info, terms)
    except ats_clients.UnsupportedBoard as e:
        stats.setdefault("unsupported", []).append(f"{site.domain}: {e}")
        return []
    except (requests.RequestException, PermissionError, ValueError) as e:
        stats["errors"].append(http_client.redact(f"{site.domain} careers: {type(e).__name__}: {e}"))
        return []
    jobs, closed = [], 0
    for p in {p.url: p for p in postings}.values():
        if p.active is False:
            closed += 1        # the employer's own system says it's closed: not a candidate
            continue
        if not filters.title_check(p.title)[0] or not filters.location_check(p.location, p.description, p.remote)[0]:
            continue
        j = Job(title=p.title, company=p.company or site.company, location=p.location, employment_type=p.employment_type,
                description=p.description, listing_url=p.url, posted_date=p.posted_date, req_id=p.req_id, remote=p.remote,
                source=f"{sources.label(p.url)} via official careers page ({site.domain})", links=[p.url])
        j.ev(f"found via the official careers page of {site.domain} ({info.get('careers_url') or 'linked ATS board'}); "
             f"official website evidence: {site.evidence}")
        jobs.append(j)
    stats["closed_skipped"] = stats.get("closed_skipped", 0) + closed
    log.info("company %s: %d postings, %d relevant, %d closed", site.domain, len(postings), len(jobs), closed)
    return jobs
