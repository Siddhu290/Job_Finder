"""LinkedIn Jobs and Naukri.com discovery through Google search (SerpApi), within the platforms' access limits.

Neither platform offers a public job-search API, and both forbid scraping. So nothing here fetches a
LinkedIn or Naukri page (http_client refuses job-board URLs anyway). We run a Google search restricted to
the platform's public job pages ("site:linkedin.com/jobs/view ...") and read only what Google returns:
the result title, link and snippet. The user is linked to the original posting on the platform.

Limits, stated plainly:
- Coverage is whatever Google has indexed; it is not the platform's full inventory.
- Titles/snippets are short. A result whose employer or job title can't be read from Google's title is
  skipped, never guessed. Experience is only known when the title/snippet states it.
- A platform listing is discovery evidence only. It never makes a job Verified; verification needs the
  employer's own system (verification/pipeline.py).
Each query costs one SerpApi search, counted like every other search."""
import re

from discovery import sources
from filters import parse_posted
from models import Job

PLATFORMS = {
    "linkedin": {"site": "site:linkedin.com/jobs/view", "domain": "linkedin.com", "label": "LinkedIn"},
    "naukri": {"site": "site:naukri.com/job-listings", "domain": "naukri.com", "label": "Naukri"},
}
LEVEL_WORDS = '(fresher OR "entry level" OR graduate OR trainee OR junior)'

_LINKEDIN = [re.compile(r"^(?P<company>.+?) hiring (?P<title>.+?) in (?P<loc>.+?)\s*(?:\||-|–)\s*LinkedIn\s*$", re.I),
             re.compile(r"^(?P<title>.+?)\s+[-–]\s+(?P<company>.+?)\s+[-–]\s+LinkedIn\s*$", re.I)]
_NAUKRI = [re.compile(r"^(?P<title>.+?)\s+[-–]\s+(?P<company>.+?)\s+[-–]\s+(?P<exp>\d{1,2}\s*(?:to|-)\s*\d{1,2}\s*years?)"
                      r"(?:\s+of\s+experience)?\s+[-–]\s+(?P<loc>.+?)\s*(?:[-–|]\s*Naukri(?:\.com)?)?\s*$", re.I),
           re.compile(r"^(?P<title>.+?)\s+Job\s+in\s+(?P<company>.+?)\s+at\s+(?P<loc>.+?)\s*(?:[-–|]\s*Naukri(?:\.com)?)?\s*$", re.I)]
_EXP = re.compile(r"\b\d{1,2}\s*(?:to|-)\s*\d{1,2}\s*(?:years?|yrs)\b|\bfreshers?\b", re.I)
_AGO = re.compile(r"\b(\d{1,2})\s+(day|week|hour|minute)s?\s+ago\b", re.I)


def tbs_for(max_age_days) -> str:
    """Google's own date restriction, so stale postings don't use up results."""
    if not max_age_days:
        return ""
    return "qdr:d" if max_age_days <= 1 else "qdr:w" if max_age_days <= 7 else "qdr:m"


def queries(platform: str, roles, locations, mode="any", limit=2) -> list:
    """[(platform, query, wfh)] - one per role and place, most important first, at most `limit`."""
    site = PLATFORMS[platform]["site"]
    places = ([] if mode == "wfh" else list(locations)) + ([] if mode == "onsite" else ["remote"])
    out = []
    for i in range(max(len(roles), len(places))):
        role, place = roles[i % len(roles)], places[i % len(places)] if places else "India"
        out.append((platform, f'{site} "{role}" {place} {LEVEL_WORDS}', place == "remote"))
    return list(dict.fromkeys(out))[:limit]


def parse_result(platform: str, r: dict):
    """Job from one Google organic result, or None when it isn't a parseable posting on that platform."""
    link, title = r.get("link") or "", (r.get("title") or "").strip()
    if sources.label(link) != PLATFORMS[platform]["label"] or not sources.source_id(link):
        return None                                        # not a job posting page on this platform
    m = next((rx.match(title) for rx in (_LINKEDIN if platform == "linkedin" else _NAUKRI) if rx.match(title)), None)
    if not m or not m.group("company").strip() or not m.group("title").strip():
        return None
    g = m.groupdict()
    snippet = (r.get("snippet") or "").strip()
    exp = g.get("exp") or (_EXP.search(f"{title} {snippet}") or [None])[0]
    desc = " ".join(filter(None, [f"Experience: {exp}." if exp else "", f"Search snippet: {snippet}" if snippet else ""]))
    loc = (g.get("loc") or "").strip()
    ago = _AGO.search(r.get("date") or snippet)
    return Job(title=g["title"].strip(), company=g["company"].strip(), location=loc, description=desc,
               listing_url=sources.canonical_url(link), links=[sources.canonical_url(link)],
               posted_date=parse_posted(ago.group(0)) if ago else None,
               remote=bool(re.search(r"\bremote\b", loc, re.I)), source=f"{PLATFORMS[platform]['label']} (via Google search)")


def search(serp, platform: str, query: str, wfh: bool = False, max_age_days=None) -> list:
    params = dict(engine="google", q=query, google_domain="google.co.in", gl="in", hl="en", num=20)
    t = tbs_for(max_age_days)
    if t:
        params["tbs"] = t
    data = serp.search(**params)
    jobs = [j for j in (parse_result(platform, r) for r in data.get("organic_results") or []) if j]
    for j in jobs:
        j.remote = j.remote or wfh
        j.ev(f"discovered in Google results for {query!r} (title and snippet only; the {platform} page was not fetched)")
    return jobs
