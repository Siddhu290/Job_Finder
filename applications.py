"""Application lifecycle (user-managed; job refreshes never touch it). Stored in the Applications tab,
every change logged to History (old -> new) so it can be undone and audited."""
import re
from datetime import date, datetime

STAGES = ["Discovered", "Saved", "Ready to Apply", "Applied", "Online Assessment", "Recruiter Screening",
          "Technical Interview", "HR Interview", "Offer", "Rejected", "Withdrawn", "Not Interested"]
ACTIVE = {"Saved", "Ready to Apply", "Applied", "Online Assessment", "Recruiter Screening", "Technical Interview", "HR Interview"}
IN_PROGRESS = {"Applied", "Online Assessment", "Recruiter Screening", "Technical Interview", "HR Interview"}
TERMINAL = {"Offer", "Rejected", "Withdrawn", "Not Interested"}
DATE_FIELDS = {"Saved Date", "Applied Date", "Deadline", "Follow-up Date", "Assessment Date", "Interview Date", "Follow-up Done"}
TEXT_FIELDS = {"Offer Details": 500, "Recruiter": 300, "Resume Version": 120, "Notes": 2000}
FIELDS = {"Stage"} | DATE_FIELDS | set(TEXT_FIELDS)
LEGACY = {"Applied": "Applied", "Not interested": "Not Interested"}   # values the old version wrote into the Jobs sheet

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean_fields(fields: dict) -> dict:
    """Validate user input. Raises ValueError with a readable message."""
    out = {}
    for k, v in (fields or {}).items():
        if k not in FIELDS:
            raise ValueError(f"Unknown field: {k}")
        v = "" if v is None else str(v).strip()
        if k == "Stage" and v not in STAGES:
            raise ValueError(f"Unknown stage: {v}")
        if k in DATE_FIELDS and v:
            if not _DATE.match(v):
                raise ValueError(f"{k} must be a date (YYYY-MM-DD)")
            datetime.strptime(v, "%Y-%m-%d")
        if k in TEXT_FIELDS:
            v = v[:TEXT_FIELDS[k]]
        out[k] = v
    return out


def stage_of(app: dict | None, legacy_status: str = "") -> str:
    if app and app.get("Stage"):
        return app["Stage"]
    return LEGACY.get(legacy_status, "Discovered")


def apply_change(st, job_id: str, fields: dict, action_id: str, today: date | None = None, source="dashboard") -> dict:
    """Upsert the application record and log each changed field. Idempotent per action_id."""
    today = (today or date.today()).isoformat()
    fields = clean_fields(fields)
    if st.seen_action(action_id):
        return {"ok": True, "duplicate": True}
    current = next((a for a in st.read("Applications")["Applications"] if a.get("Job ID") == job_id), {})
    stage = fields.get("Stage")
    if stage == "Saved" and not current.get("Saved Date") and "Saved Date" not in fields:
        fields["Saved Date"] = today
    if stage == "Applied" and not current.get("Applied Date") and "Applied Date" not in fields:
        fields["Applied Date"] = today
    changed = {k: v for k, v in fields.items() if current.get(k, "") != v}
    if not changed:
        return {"ok": True, "changed": {}}
    st.upsert("Applications", [{"Job ID": job_id, **changed, "Updated At": datetime.now().strftime("%Y-%m-%d %H:%M")}])
    for i, (k, v) in enumerate(changed.items()):
        st.record(job_id, k, current.get(k, ""), v, source=source, action_id=f"{action_id}#{i}" if i else action_id)
    return {"ok": True, "changed": changed}


def undo(st, job_id: str, action_id: str) -> dict:
    """Revert the most recent change made to this job's application (all fields changed by that action)."""
    hist = [h for h in st.read("History")["History"] if h.get("Job ID") == job_id and h.get("Field") in FIELDS]
    if not hist:
        return {"ok": False, "error": "Nothing to undo"}
    last = hist[-1]["Action ID"].split("#")[0]
    batch = [h for h in hist if h.get("Action ID", "").split("#")[0] == last]
    return apply_change(st, job_id, {h["Field"]: h.get("Old", "") for h in batch}, action_id, source="undo")


def history(st, job_id: str) -> list:
    return [{k: h.get(k, "") for k in ("Timestamp", "Field", "Old", "New", "Source")}
            for h in st.read("History")["History"] if h.get("Job ID") == job_id]
