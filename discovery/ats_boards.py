"""Poll employer ATS boards listed in boards.json via their public job APIs (no SerpApi credits).
Being on this list grants no trust: each board is still verified against the employer's official site."""
import json
import logging

import requests

import filters
from models import Job
from verification import ats_clients
from verification.ats_verifier import AtsRef

log = logging.getLogger(__name__)
SEARCH_TERMS = ("Data Analyst", "Data Engineer", "Analytics")  # for boards searched by keyword (Workday, SmartRecruiters)


def load_boards(path) -> list:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from None


def board_jobs(entry, stats) -> list:
    ref = AtsRef(entry["ats"], entry["board"].lower(), site=entry.get("site", ""), host=entry.get("host", ""))
    keyword_search = ref.ats in ("workday", "smartrecruiters")
    postings = {}
    try:
        for term in SEARCH_TERMS if keyword_search else ("",):
            for p in ats_clients.list_board(ref, term):
                postings[p.url] = p
    except (requests.RequestException, PermissionError, ValueError) as e:
        stats["errors"].append(f"{entry['company']} {ref.ats} board: {type(e).__name__}: {e}")
        return []
    jobs = []
    for p in postings.values():
        if not filters.title_check(p.title)[0] or not filters.location_check(p.location, p.description, p.remote)[0]:
            continue
        jobs.append(Job(title=p.title, company=entry["company"], location=p.location, employment_type=p.employment_type,
                        description=p.description, listing_url=p.url, posted_date=p.posted_date, req_id=p.req_id,
                        remote=p.remote, source=f"{ref.ats.title()} board ({entry['board']})", links=[p.url]))
    log.info("board %s/%s: %d postings, %d relevant", ref.ats, ref.board, len(postings), len(jobs))
    return jobs
