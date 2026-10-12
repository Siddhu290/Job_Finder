"""Where a listing came from: platform label, configurable source tier, canonical URL and source-specific ID.

Tiers describe *source preference only*, never authenticity: a tier-1 URL is still verified by
verification/pipeline.py, and "Company website" here only means "not a known job board or ATS host".
The dashboard calls a job an official company posting only from verification evidence (routes/jobs.py).

  1 = company-originated (employer's own site, or an ATS board)      2 = trusted job platform (LinkedIn, Naukri, ...)
  3 = supplementary discovery (anything else)
Override per label with SOURCE_TIERS='{"Naukri": 3, "Indeed": 3}' (JSON, server environment)."""
import json
import os
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from http_client import JOB_BOARDS, TRUSTED_PORTALS, registered_domain
from verification.ats_verifier import parse_ats_url

ATS_LABELS = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
              "smartrecruiters": "SmartRecruiters", "jobvite": "Jobvite"}
PLATFORM_LABELS = {"linkedin.com": "LinkedIn", "naukri.com": "Naukri", "indeed.com": "Indeed", "indeed.co.in": "Indeed",
                   "glassdoor.com": "Glassdoor", "glassdoor.co.in": "Glassdoor", "foundit.in": "Foundit", "shine.com": "Shine",
                   "timesjobs.com": "TimesJobs", "instahyre.com": "Instahyre", "wellfound.com": "Wellfound",
                   "cutshort.io": "Cutshort", "hirist.tech": "Hirist", "hirist.com": "Hirist", "iimjobs.com": "iimjobs"}
COMPANY = "Company website"
EMPLOYER_LINK = "employer-site link (unconfirmed)"       # Google Jobs apply link off the job boards; not evidence
_LEGACY = {"Company career page", EMPLOYER_LINK}         # older rows used "Company career page" for the same thing
DEFAULT_TIERS = {COMPANY: 1, **{v: 1 for v in ATS_LABELS.values()}, **{v: 2 for v in PLATFORM_LABELS.values()}}

# Click/tracking parameters only. Anything else (gh_jid, token, id, jobId ...) may identify the vacancy and is kept.
_TRACKING = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|mc_cid|mc_eid|_hsenc|_hsmi|trk|trackingid|refid|lipi|"
                       r"originalsubdomain|ref_?|src)$", re.I)
_LINKEDIN_ID = re.compile(r"/jobs/view/(?:[^/?#]*?-)?(\d{6,})")
_NAUKRI_ID = re.compile(r"job-listings-[^?#]*?-(\d{9,15})(?:[/?#]|$)")


def tiers() -> dict:
    t = dict(DEFAULT_TIERS)
    try:
        t.update({k: int(v) for k, v in json.loads(os.environ.get("SOURCE_TIERS") or "{}").items() if int(v) in (1, 2, 3)})
    except (ValueError, TypeError, AttributeError):
        pass  # malformed override: keep the defaults rather than failing a search
    return t


def label(url: str) -> str:
    ref = parse_ats_url(url or "")
    if ref:
        return ATS_LABELS.get(ref.ats, ref.ats.title())
    dom = registered_domain(url or "")
    if dom in PLATFORM_LABELS:
        return PLATFORM_LABELS[dom]
    if not dom or dom in JOB_BOARDS:
        return "Other job site"
    return COMPANY


def tier(url: str) -> int:
    return tiers().get(label(url), 3)


def is_trusted_platform(url: str) -> bool:
    return registered_domain(url or "") in TRUSTED_PORTALS


def canonical_url(url: str) -> str:
    """Same vacancy, same string: lowercase scheme/host, no fragment, no tracking parameters, no trailing slash."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return url or ""
    if not p.scheme or not p.netloc:
        return url or ""
    q = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)])
    host = p.netloc.lower()
    if registered_domain(host) == "linkedin.com":          # in.linkedin.com / www.linkedin.com: same posting
        host = "www.linkedin.com"
    return urlunparse((p.scheme.lower(), host, p.path.rstrip("/") or "/", "", q, ""))


def source_id(url: str) -> str:
    """'linkedin:3912345678', 'naukri:101024012345', 'greenhouse:acme:4001' ... or '' when the URL carries no ID."""
    ref = parse_ats_url(url or "")
    if ref and ref.job_id:
        return f"{ref.ats}:{ref.board}:{ref.job_id}"
    dom = registered_domain(url or "")
    m = (_LINKEDIN_ID if dom == "linkedin.com" else _NAUKRI_ID if dom == "naukri.com" else None)
    m = m.search(url) if m else None
    if not m and dom == "linkedin.com":
        m = re.search(r"[?&]currentJobId=(\d{6,})", url)
    return f"{PLATFORM_LABELS[dom].lower()}:{m.group(1)}" if m else ""


def headline(source: str) -> str:
    """Primary platform name from a stored Source Platform string (for grouping and display)."""
    first = (source or "").split("; ")[0]
    parts = [p for p in first.split(" + ") if p and p not in _LEGACY]
    return parts[0] if parts else (first or "Unknown")


def provenance(job) -> list:
    """Every URL the job was seen at, best tier first: [{label, url, tier, id}]. Stored as verification evidence."""
    out, seen = [], set()
    for u in dict.fromkeys(canonical_url(u) for u in [job.listing_url, *job.links] if u):
        key = source_id(u) or u            # two URL shapes of one LinkedIn/Naukri/ATS posting are one source
        if key not in seen:
            seen.add(key)
            out.append({"label": label(u), "url": u, "tier": tier(u), "id": source_id(u)})
    return sorted(out, key=lambda s: s["tier"])
