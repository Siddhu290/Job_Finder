"""Follow-up reminders computed from stored dates (nothing is ever sent to employers or recruiters).

A reminder is (job, kind, due date). Kinds: follow-up (custom date, or N days after applying), assessment,
interview, deadline (your recorded deadline), closing (employer-published closing date of a Verified job you
haven't applied to). Marking a follow-up done stores "Follow-up Done", which suppresses it (no duplicates)."""
from datetime import date, timedelta

import applications

UPCOMING_DAYS = 7
CLOSING_SOON_DAYS = 3


def _d(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def reminders(jobs: list, apps: dict, details: dict, today: date, follow_up_days: int = 5) -> dict:
    """jobs: Jobs rows; apps/details: {job_id: record}. Returns {"overdue", "today", "upcoming"} lists."""
    items = {}
    for j in jobs:
        jid = j.get("Job ID")
        app = apps.get(jid, {})
        stage = applications.stage_of(app, j.get("Verification Status", ""))
        if stage in applications.TERMINAL:
            continue
        base = {"job_id": jid, "title": j.get("Job Title", ""), "company": j.get("Company", ""), "stage": stage}
        if stage in applications.IN_PROGRESS:
            due = _d(app.get("Follow-up Date"))
            if not due and _d(app.get("Applied Date")):
                due = _d(app.get("Applied Date")) + timedelta(days=follow_up_days)
            done = _d(app.get("Follow-up Done"))
            if due and not (done and done >= due - timedelta(days=follow_up_days)):
                items[(jid, "follow-up")] = {**base, "kind": "follow-up", "due": due}
        for field, kind in (("Assessment Date", "assessment"), ("Interview Date", "interview"), ("Deadline", "deadline")):
            d = _d(app.get(field))
            if d and d >= today - timedelta(days=1):
                items[(jid, kind)] = {**base, "kind": kind, "due": d}
        closes = _d(details.get(jid, {}).get("Closes"))
        if closes and j.get("Verification Status") == "Verified" and stage not in applications.IN_PROGRESS \
                and today <= closes <= today + timedelta(days=CLOSING_SOON_DAYS):
            items[(jid, "closing")] = {**base, "kind": "closing", "due": closes}
    out = {"overdue": [], "today": [], "upcoming": []}
    for it in sorted(items.values(), key=lambda x: x["due"]):
        bucket = "overdue" if it["due"] < today else "today" if it["due"] == today else \
            "upcoming" if it["due"] <= today + timedelta(days=UPCOMING_DAYS) else None
        if bucket:
            out[bucket].append({**it, "due": it["due"].isoformat()})
    return out
