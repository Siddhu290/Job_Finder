"""SerpApi client and Google Jobs discovery."""
import logging

import requests

import http_client
from filters import parse_posted
from models import Job

log = logging.getLogger(__name__)
SERPAPI_URL = "https://serpapi.com/search.json"


class SerpApiError(Exception):
    pass


class SerpApiAuthError(SerpApiError):
    pass


class BudgetExhausted(SerpApiError):
    pass


class SerpApi:
    def __init__(self, api_key: str, max_calls: int):
        self.api_key, self.max_calls, self.calls = api_key, max_calls, 0
        http_client.register_secret(api_key)

    def search(self, **params) -> dict:
        if self.calls >= self.max_calls:
            raise BudgetExhausted(f"SerpApi call budget ({self.max_calls}) used up for this run")
        self.calls += 1
        try:
            r = http_client.request("GET", SERPAPI_URL, params={**params, "api_key": self.api_key})
        except requests.RequestException as e:
            raise SerpApiError(http_client.redact(f"SerpApi request failed: {e}")) from None
        if r.status_code == 401:
            raise SerpApiAuthError("SerpApi rejected the API key (HTTP 401). Check SERPAPI_KEY in .env.")
        try:
            data = r.json()
        except ValueError:
            raise SerpApiError(f"SerpApi returned non-JSON (HTTP {r.status_code})") from None
        err = data.get("error", "")
        if err and "hasn't returned any results" in err:
            return {}
        if err or r.status_code >= 400:
            raise SerpApiError(http_client.redact(f"SerpApi error (HTTP {r.status_code}): {err}"))
        return data


def google_jobs(serp: SerpApi, query: str, location: str = "India", wfh_only: bool = False) -> list:
    params = dict(engine="google_jobs", q=query, location=location, google_domain="google.co.in", gl="in", hl="en")
    if wfh_only:
        params["ltype"] = "1"  # Google Jobs "work from home" filter
    data = serp.search(**params)
    jobs = []
    for r in data.get("jobs_results") or []:
        ext = r.get("detected_extensions") or {}
        links = [o["link"] for o in r.get("apply_options") or [] if o.get("link")]
        company = (r.get("company_name") or "").replace("u0026", "&").strip()
        links = [u for u in links if http_client.is_trusted_source(u, company)]  # drop low-quality aggregators
        if not links:
            continue
        board_links = [u for u in links if http_client.is_job_board(u)]
        on_company_site = len(board_links) < len(links)  # Google lists an apply link on the employer's own site/ATS
        via = (r.get("via") or "").removeprefix("via ").strip()
        jobs.append(Job(
            title=r.get("title", "").strip(),
            company=company,
            location=(r.get("location") or "").strip(),
            employment_type=ext.get("schedule_type", ""),
            description=r.get("description", ""),
            # prefer the employer's own job page (where you actually apply) over a portal copy
            listing_url=([u for u in links if u not in board_links] or board_links or [r.get("share_link", "")])[0],
            posted_date=parse_posted(ext.get("posted_at")),
            source=("Company career page" if on_company_site else "") + (" + " if on_company_site else "")
                   + (f"Google Jobs ({via})" if via else "Google Jobs"),
            remote=wfh_only or bool(ext.get("work_from_home")),
            links=links,
        ))
    return jobs
