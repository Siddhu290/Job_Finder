"""Find the employer's careers page on its official domain and the ATS boards it links to."""
import logging
import re
from dataclasses import dataclass, field, replace
from urllib.parse import urljoin, urlparse

import requests

import http_client
from http_client import registered_domain
from verification.ats_verifier import find_board_refs, parse_ats_url

log = logging.getLogger(__name__)
_HREF = re.compile(r"""<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_CAREERISH = re.compile(r"career|jobs?\b|join[\s-]?us|work[\s-]with[\s-]us|openings|vacanc|hiring", re.I)
MAX_FETCHES = 6


@dataclass
class Careers:
    careers_url: str = ""
    boards: set = field(default_factory=set)
    evidence: list = field(default_factory=list)


def find_careers(site, vacancy_links=()) -> Careers:
    out = Careers()
    d = site.domain
    queue = [u for u in vacancy_links if registered_domain(u) == d and not parse_ats_url(u)]
    queue += [site.website, f"https://{d}/careers", f"https://www.{d}/careers", f"https://careers.{d}/",
              f"https://{d}/jobs", f"https://jobs.{d}/"]
    seen, fetches = set(), 0
    while queue and fetches < MAX_FETCHES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        fetches += 1
        try:
            r = http_client.get_page(url)
        except PermissionError as e:
            out.evidence.append(f"skipped {url}: {e}")
            continue
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        final = r.url
        redirected_ats = parse_ats_url(final)
        if registered_domain(final) != d:
            if redirected_ats and registered_domain(url) == d:
                out.boards.add(replace(redirected_ats, job_id="", path="", url=""))
                out.careers_url = out.careers_url or url
                out.evidence.append(f"official {url} redirects to {redirected_ats.ats} board '{redirected_ats.board}'")
            continue
        careerish = bool(_CAREERISH.search(urlparse(final).netloc.split(".")[0] + urlparse(final).path))
        boards = find_board_refs(r.text)
        if boards:
            out.boards |= boards
            out.evidence += [f"{final} (official domain) links to {b.ats} board '{b.board}'" for b in sorted(boards, key=str)]
        if careerish and not out.careers_url:
            out.careers_url = final
            out.evidence.append(f"official careers page: {final}")
        if out.boards and out.careers_url:
            break
        # follow careers links from the homepage / careers hub
        for href, text in _HREF.findall(r.text):
            link = urljoin(final, href.strip())
            if not link.startswith("http") or link in seen:
                continue
            if registered_domain(link) == d and (_CAREERISH.search(urlparse(link).path) or _CAREERISH.search(re.sub("<[^>]+>", "", text))):
                queue.insert(0, link)
    if out.boards and not out.careers_url:
        out.careers_url = site.website
    return out
