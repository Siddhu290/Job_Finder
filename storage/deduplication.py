"""Deduplication keys. Employer + requisition ID when known, otherwise employer + title + location + official URL."""
import hashlib

from models import CLOSED, NEEDS_REVIEW, REJECTED, VERIFIED
from verification.company_resolver import normalize_company
from verification.vacancy_matcher import cities, norm_id, norm_title

_RANK = {VERIFIED: 4, CLOSED: 3, NEEDS_REVIEW: 2, REJECTED: 1, "": 0}


def norm_location(loc: str) -> str:
    c = sorted(cities(loc))
    return ",".join(c) if c else " ".join((loc or "").lower().split())


def loose_key(company, title, location) -> str:
    """Same vacancy seen on several boards (before verification or in existing sheet rows)."""
    return f"{normalize_company(company)}|{norm_title(title)}|{norm_location(location)}"


def job_key(job) -> str:
    if job.req_id:
        return f"{normalize_company(job.company)}|req|{norm_id(job.req_id)}"
    return f"{loose_key(job.company, job.title, job.location)}|{job.apply_url}"


def job_id(job) -> str:
    return "J" + hashlib.sha1(job_key(job).encode()).hexdigest()[:10].upper()


def _merge(keep, other):
    for u in other.links:
        if u not in keep.links:
            keep.links.append(u)
    if other.source and other.source not in keep.source:
        keep.source = f"{keep.source}; {other.source}" if keep.source else other.source
    keep.description = keep.description if len(keep.description) >= len(other.description) else other.description
    keep.req_id = keep.req_id or other.req_id
    keep.posted_date = keep.posted_date or other.posted_date


def dedupe(jobs, key=lambda j: loose_key(j.company, j.title, j.location)):
    """(unique_jobs, duplicates_merged). The better-verified copy wins; links/sources are merged."""
    seen = {}
    for j in jobs:
        k = key(j)
        if k not in seen:
            seen[k] = j
            continue
        keep, other = (j, seen[k]) if _RANK.get(j.status, 0) > _RANK.get(seen[k].status, 0) else (seen[k], j)
        _merge(keep, other)
        seen[k] = keep
    return list(seen.values()), len(jobs) - len(seen)
