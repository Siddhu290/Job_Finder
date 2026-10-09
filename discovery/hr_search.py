"""Find HR / recruiter profiles for an employer from Google search results (via SerpApi).

LinkedIn itself is never fetched: only the public titles Google shows are read. A profile is kept only if
its headline names the employer and an HR role. Results are labelled unverified and cached 30 days.
Contacting anyone is left entirely to the user."""
import re
from datetime import date

from verification.company_resolver import normalize_company

HR_ROLE = re.compile(r"\b(hr|human\s+resources?|talent\s+acquisition|recruit\w*|hiring|people\s+(partner|operations|team)|"
                     r"campus\s+(hiring|relations))\b", re.I)
PROFILE = re.compile(r"^https://([a-z]{2,3}\.)?(www\.)?linkedin\.com/in/[A-Za-z0-9_%-]+/?$")
NOTE_PREFIX = "HR on LinkedIn (Google results, unverified)"
TTL_DAYS = 30


def parse_results(company: str, results: list, limit=3) -> list:
    """[(name, headline, url)] from Google organic results."""
    key = normalize_company(company)
    out = []
    for r in results:
        url, title = r.get("link", ""), r.get("title", "")
        if not PROFILE.match(url) or " - " not in title:
            continue
        name, headline = title.split(" - ", 1)
        headline = re.sub(r"\s*\|\s*LinkedIn\s*$", "", headline).strip()
        if key and key in normalize_company(headline) and HR_ROLE.search(headline):
            out.append((name.strip(), headline, url))
        if len(out) == limit:
            break
    return out


def find_hr(company: str, serp, cache, today: date | None = None) -> list:
    today = today or date.today()
    key = f"hr|{normalize_company(company)}"
    hit = cache.get(key, today, ttl=TTL_DAYS)
    if hit is None:
        data = serp.search(engine="google", q=f'"{company}" HR recruiter talent acquisition LinkedIn',
                           google_domain="google.co.in", gl="in", hl="en")
        hit = {"hr": parse_results(company, data.get("organic_results") or []), "checked": today.isoformat()}
        cache.put(key, hit)
    return [tuple(x) for x in hit["hr"]]


def note(profiles) -> str:
    return f"{NOTE_PREFIX}: " + " | ".join(f"{n} – {h} – {u}" for n, h, u in profiles)


_NOTE_ITEM = re.compile(r"([^|:;]+?) – ([^|;]+?) – (https://[a-z.]*linkedin\.com/in/[^\s|;]+)")


def from_notes(notes: str) -> list:
    """Profiles previously written into a sheet Notes cell."""
    if NOTE_PREFIX not in (notes or ""):
        return []
    part = notes.split(NOTE_PREFIX, 1)[1]
    return [{"name": n.strip(), "headline": h.strip(), "url": u} for n, h, u in _NOTE_ITEM.findall(part)]
