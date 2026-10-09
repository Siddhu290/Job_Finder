"""Job-search analytics computed only from stored data. Missing data is reported as None ("n/a"), never guessed."""
from collections import Counter
from datetime import date, timedelta

import applications
import filters

RANGES = {"7": 7, "30": 30, "90": 90, "all": None}
INTERVIEW_STAGES = {"Recruiter Screening", "Technical Interview", "HR Interview"}


def _d(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _role(title):
    t = (title or "").lower()
    return "Data Engineer" if "engineer" in t and "data" in t else "Data Analyst" if "analyst" in t and "data" in t else \
        "Analytics / BI" if any(w in t for w in ("analytics", " bi ", "business intelligence")) else "Other"


def _where(row):
    if "work from home" in (row.get("Employment Type", "") or "").lower() or filters.is_remote_job(row.get("Location", "")):
        return "Work from home"
    loc = (row.get("Location", "") or "").split(",")[0].strip()
    return loc or "Not stated"


def _ratio(a, b):
    return round(100 * a / b) if b else None


def compute(jobs, archive, apps, history, runs, match_scores, today: date, range_key="30", confirmed_used=None) -> dict:
    days = RANGES.get(range_key, 30)
    since = today - timedelta(days=days - 1) if days else date.min
    in_range = lambda s: (_d(s) or date.min) >= since
    all_jobs = jobs + archive
    found = [r for r in all_jobs if in_range(r.get("Date Found"))]
    last_run = max((r.get("Started", "") for r in runs), default="")
    status = Counter(r.get("Verification Status", "") for r in found)
    weeks = Counter()
    for r in found:
        p = _d(r.get("Job Posted Date"))
        if p:
            weeks[(p - timedelta(days=p.weekday())).isoformat()] += 1
    buckets = Counter()
    for v in match_scores:
        buckets["0-24" if v < 25 else "25-49" if v < 50 else "50-74" if v < 75 else "75-100"] += 1
    # application funnel from History (stage changes in range) + Applied Date
    stage_events = [h for h in history if h.get("Field") == "Stage" and in_range(h.get("Timestamp"))]
    reached = lambda stages: {h.get("Job ID") for h in stage_events if h.get("New") in stages}
    applied = {a.get("Job ID") for a in apps if in_range(a.get("Applied Date"))} | reached({"Applied"})
    assessed, interviewed = reached({"Online Assessment"}), reached(INTERVIEW_STAGES)
    offers, rejections = reached({"Offer"}), reached({"Rejected"})
    run_rows = [r for r in runs if in_range(r.get("Started"))]
    used_est = sum(int(r.get("SerpApi Calls") or 0) for r in run_rows if str(r.get("SerpApi Calls", "")).isdigit())
    return {
        "range": range_key,
        "total_discovered": len(found),
        "new_since_last_search": sum(1 for r in jobs if last_run and (r.get("Date Found", "") >= last_run[:16])) if last_run else None,
        "by_status": {k: status.get(k, 0) for k in ("Verified", "Needs Review", "Rejected", "Closed")},
        "by_role": dict(Counter(_role(r.get("Job Title")) for r in found).most_common()),
        "by_location": dict(Counter(_where(r) for r in found).most_common(12)),
        "by_employment": dict(Counter((r.get("Employment Type") or "Not stated").split(",")[0] for r in found).most_common(8)),
        "by_source": dict(Counter(((r.get("Source Platform") or "Unknown").split(" + ")[-1]) for r in found).most_common(10)),
        "by_posted_week": dict(sorted(weeks.items())),
        "match_distribution": dict(buckets) if match_scores else None,
        "applications": len(applied), "assessments": len(assessed), "interviews": len(interviewed),
        "offers": len(offers), "rejections": len(rejections),
        "application_to_interview_pct": _ratio(len(interviewed & applied) or len(interviewed), len(applied)),
        "interview_to_offer_pct": _ratio(len(offers), len(interviewed)),
        "current_stages": dict(Counter(applications.stage_of(a) for a in apps).most_common()),
        "searches": {"runs": len(run_rows), "serpapi_used_estimated": used_est,
                     "serpapi_used_confirmed_this_month": confirmed_used},
    }
