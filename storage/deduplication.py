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


def _tier(job) -> int:
    from discovery.sources import tier
    return tier(job.listing_url) if job.listing_url else 9


def _merge(keep, other):
    """Fold `other` into `keep`. Weaker evidence never replaces stronger: keep's status/checks stay, and the
    canonical listing URL becomes the best-tier one (employer site/ATS over LinkedIn/Naukri over the rest)."""
    from discovery.sources import canonical_url
    have = {canonical_url(u) for u in keep.links}
    for u in other.links + [other.listing_url]:
        if u and canonical_url(u) not in have:
            keep.links.append(u)
            have.add(canonical_url(u))
    if other.listing_url and _tier(other) < _tier(keep):
        if keep.listing_url and canonical_url(keep.listing_url) not in have:
            keep.links.append(keep.listing_url)
        keep.listing_url = other.listing_url
    if other.source and other.source not in keep.source:
        keep.source = f"{keep.source}; {other.source}" if keep.source else other.source
    keep.description = keep.description if len(keep.description) >= len(other.description) else other.description
    keep.req_id = keep.req_id or other.req_id
    keep.posted_date = keep.posted_date or other.posted_date


def _better(a, b) -> bool:
    """Is a the stronger copy? Verification status first, then source tier."""
    return (_RANK.get(a.status, 0), -_tier(a)) > (_RANK.get(b.status, 0), -_tier(b))


def dedupe(jobs, key=lambda j: loose_key(j.company, j.title, j.location)):
    """(unique_jobs, duplicates_merged). The better-verified (then better-sourced) copy wins; links/sources merge.
    Two postings with different employer requisition IDs are different vacancies, even with the same title."""
    seen, out = {}, []
    for j in jobs:
        group = seen.setdefault(key(j), [])
        same = next((g for g in group if not (g.req_id and j.req_id and norm_id(g.req_id) != norm_id(j.req_id))), None)
        if same is None:
            group.append(j)
            out.append(j)
            continue
        keep, other = (j, same) if _better(j, same) else (same, j)
        _merge(keep, other)
        if keep is j:                                   # replace by identity (dataclass == compares values)
            for lst in (group, out):
                lst[next(i for i, x in enumerate(lst) if x is same)] = j
    return out, len(jobs) - len(out)
