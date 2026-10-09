"""Identify the employer and establish its official website.

Evidence accepted: Google's Knowledge Graph panel for an entity whose name matches the employer,
which lists the website. A domain that merely contains the company name is never accepted.
Results are cached on disk to save SerpApi credits.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from urllib.parse import quote, unquote, urlparse

import http_client
from http_client import is_job_board, registered_domain

log = logging.getLogger(__name__)

_LEGAL = re.compile(r"\b(private|pvt|limited|ltd|inc|incorporated|llc|llp|corp|corporation|co|company|plc|gmbh|"
                    r"ag|sa|bv|pte|india|hq|headquarters)\b\.?", re.I)
POSITIVE_TTL, NEGATIVE_TTL = 30, 7


def normalize_company(name: str) -> str:
    s = re.sub(r"\(.*?\)", " ", (name or "").lower().replace(".", "")).replace("&", " and ")
    s = _LEGAL.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _name_variants(name: str) -> set:
    """'Indian Hotels Company (Taj Hotels)' -> {'indian hotels', 'taj hotels'}: the bracketed brand also counts."""
    return {normalize_company(name)} | {normalize_company(b) for b in re.findall(r"\((.*?)\)", name or "")} - {""}


@dataclass
class OfficialSite:
    company: str
    website: str
    domain: str
    evidence: str


class CompanyCache:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, today, ttl=None):
        e = self.data.get(key)
        if not e:
            return None
        ttl = ttl or (POSITIVE_TTL if e.get("domain") else NEGATIVE_TTL)
        return e if date.fromisoformat(e["checked"]) + timedelta(days=ttl) >= today else None

    def put(self, key, entry):
        self.data[key] = entry

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
        tmp.replace(self.path)


def resolve_official_site(company: str, serp, cache: CompanyCache, today: date | None = None):
    """(OfficialSite, '') or (None, reason). Raises SerpApi errors so the caller can count them."""
    today = today or date.today()
    key = normalize_company(company)
    if not key:
        return None, "employer name missing"
    hit = cache.get(key, today)
    if hit is None:
        data = serp.search(engine="google", q=company, google_domain="google.co.in", gl="in", hl="en")
        hit = _judge(company, data.get("knowledge_graph") or {})
        hit["checked"] = today.isoformat()
        cache.put(key, hit)
    if not hit.get("domain"):
        return None, hit.get("reason", "no official website evidence")
    return OfficialSite(company, hit["website"], hit["domain"], hit["evidence"]), ""


def _judge(company, kg):
    title = kg.get("title", "")
    if not title:
        return {"reason": "no Google Knowledge Graph entry for this employer"}
    if normalize_company(title) not in _name_variants(company):
        return {"reason": f"Knowledge Graph entry '{title}' does not match employer name '{company}'"}
    website, how = kg.get("website", ""), f"Google Knowledge Graph entry '{title}' lists official website"
    if not website:
        # Google's panel rarely shows the website any more; follow its own Wikipedia source to Wikidata P856.
        wiki = (kg.get("source") or {}).get("link", "")
        website = _wikidata_website(wiki) if "wikipedia.org/wiki/" in wiki else ""
        how = f"Google Knowledge Graph entry '{title}' cites {wiki}; its Wikidata item lists official website"
    if not website:
        return {"reason": f"Knowledge Graph entry '{title}' has no website and no Wikipedia/Wikidata official website"}
    if is_job_board(website):
        return {"reason": f"official website candidate {website} is a job board/social site"}
    return {"website": website, "domain": registered_domain(website), "evidence": f"{how} {website}"}


def _wikidata_website(wiki_url: str) -> str:
    """Official website (Wikidata P856, preferred rank first) for a Wikipedia article. Raises on network errors."""
    p = urlparse(wiki_url)
    title = unquote(p.path.split("/wiki/", 1)[1])
    d = http_client.get_json(f"https://{p.hostname}/w/api.php?action=query&prop=pageprops&redirects=1&format=json"
                             f"&titles={quote(title)}") or {}
    qid = next((pg.get("pageprops", {}).get("wikibase_item") for pg in d.get("query", {}).get("pages", {}).values()), None)
    if not qid:
        return ""
    e = http_client.get_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json") or {}
    claims = e.get("entities", {}).get(qid, {}).get("claims", {}).get("P856", [])
    claims = sorted((c for c in claims if c.get("rank") != "deprecated"), key=lambda c: c.get("rank") != "preferred")
    return next((c["mainsnak"]["datavalue"]["value"] for c in claims if "datavalue" in c.get("mainsnak", {})), "")
