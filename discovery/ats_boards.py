"""Poll employer ATS boards listed in boards.json via their public job APIs (no SerpApi credits).
Being on this list grants no trust: each board is still verified against the employer's official site."""
import json
import logging

import requests

import filters
from discovery import sources
from models import Job
from verification import ats_clients
from verification.ats_verifier import AtsRef

log = logging.getLogger(__name__)
DEFAULT_TERMS = ("Data Analyst", "Data Engineer", "Analytics")  # keyword-searched boards (Workday, SmartRecruiters) without resume roles


def load_boards(path) -> list:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from None


def board_jobs(entry, stats, terms=None) -> list:
    ref = AtsRef(entry["ats"], entry["board"].lower(), site=entry.get("site", ""), host=entry.get("host", ""))
    keyword_search = ref.ats in ("workday", "smartrecruiters")
    terms = terms or list(filters.PROFILE.roles) or DEFAULT_TERMS      # the user's roles, not a global default
    postings = {}
    try:
        for term in terms if keyword_search else ("",):
            for p in ats_clients.list_board(ref, term):
                postings[p.url] = p
    except ats_clients.UnsupportedBoard as e:          # permanent: no public API - not an error to retry
        stats.setdefault("unsupported", []).append(f"{entry['company']}: {e}")
        return []
    except (requests.RequestException, PermissionError, ValueError) as e:
        stats["errors"].append(f"{entry['company']} {ref.ats} board (temporary?): {type(e).__name__}: {e}")
        return []
    jobs = []
    for p in postings.values():
        if p.active is False:
            continue
        if not filters.title_check(p.title)[0] or not filters.location_check(p.location, p.description, p.remote)[0]:
            continue
        jobs.append(Job(title=p.title, company=entry["company"], location=p.location, employment_type=p.employment_type,
                        description=p.description, listing_url=p.url, posted_date=p.posted_date, req_id=p.req_id,
                        remote=p.remote, source=f"{sources.ATS_LABELS.get(ref.ats, ref.ats.title())} board ({entry['board']})", links=[p.url]))
    log.info("board %s/%s: %d postings, %d relevant", ref.ats, ref.board, len(postings), len(jobs))
    return jobs
