"""Decide whether a matched vacancy is open, closed or uncertain. HTTP 200 alone never means open."""
import requests

import http_client
from verification.ats_clients import CLOSED_MARKERS
from verification.vacancy_matcher import norm_id

OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"


def check(posting) -> tuple:
    """(state, evidence). OPEN requires: the employer system lists the vacancy as active AND the
    apply page is reachable without redirecting away from the vacancy or stating it is closed."""
    if posting.active is False:
        return CLOSED, "; ".join(posting.evidence) or "employer system reports the vacancy inactive"
    if posting.active is None:
        return UNKNOWN, "; ".join(posting.evidence) or "employer system does not confirm the vacancy is open"
    if not posting.url or http_client.is_job_board(posting.url):
        return UNKNOWN, "no direct employer application URL"
    try:
        r = http_client.get_page(posting.url)
    except PermissionError as e:
        return UNKNOWN, f"apply page not checked: {e}"
    except requests.RequestException as e:
        return UNKNOWN, f"apply page unreachable: {type(e).__name__}"
    if r.status_code in (404, 410):
        return CLOSED, f"apply page returns HTTP {r.status_code}"
    if r.status_code != 200:
        return UNKNOWN, f"apply page returns HTTP {r.status_code}"
    if posting.ats != "official-site" and posting.req_id and norm_id(posting.req_id) not in norm_id(r.url):
        return UNKNOWN, f"apply page redirected away from the vacancy (to {r.url})"
    if posting.ats != "official-site" and CLOSED_MARKERS.search(http_client.html_to_text(r.text)):
        return UNKNOWN, "ATS lists the vacancy but its page text suggests it is closed"
    return OPEN, "; ".join(posting.evidence + [f"apply page reachable at {r.url}"])
