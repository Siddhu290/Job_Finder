"""Structured storage in extra tabs of the same spreadsheet (single source of truth; no second database).

Tabs are addressed by header name, so user-added columns or reordering do not break anything.
Rows are keyed by Job ID where it applies. Large text is truncated to stay under the 50k-character cell limit.

Why not PostgreSQL (yet): one user, hundreds-to-thousands of rows, and Vercel has no bundled database. A second
store would create two sources of truth and extra cost/ops. If this becomes multi-user, move these tabs to
Postgres tables with the same names/columns (+ user_id, unique(user_id, job_id)) and keep Sheets as an export."""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import gspread

log = logging.getLogger(__name__)

TABS = {
    "Details": ["Job ID", "Updated", "Description", "Required Skills", "Preferred Skills", "Min Years", "Education",
                "Closes", "Contacts"],
    "Verification": ["Timestamp", "Job ID", "Run ID", "Status", "Req ID", "Reason", "Checks", "Last Open Check",
                     "Retry", "Attempts", "Next Check"],
    "Applications": ["Job ID", "Stage", "Saved Date", "Applied Date", "Deadline", "Follow-up Date", "Assessment Date",
                     "Interview Date", "Offer Details", "Recruiter", "Resume Version", "Notes", "Follow-up Done", "Updated At"],
    "History": ["Timestamp", "Job ID", "Field", "Old", "New", "Action ID", "Source"],
    "Runs": ["Run ID", "Started", "Finished", "Trigger", "Profile", "Allowed Searches", "SerpApi Calls", "Discovered",
             "Unique", "New Rows", "Verified", "Needs Review", "Errors", "Status"],
}
CELL_LIMIT = 45_000
LOCK_CELL_TAB = "_lock"


def _now():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _clip(v):
    s = v if isinstance(v, str) else json.dumps(v) if isinstance(v, (list, dict)) else ("" if v is None else str(v))
    return s[:CELL_LIMIT]


class Store:
    def __init__(self, client):
        self.c = client                       # integrations.google_sheets.SheetsClient (opened)
        self.sh = client.ws.spreadsheet
        self._titles = None

    # ---------- low level ----------
    def titles(self) -> set:
        if self._titles is None:
            self._titles = {ws.title for ws in self.c._call(self.sh.worksheets)}
        return self._titles

    def _ws(self, tab, create=True):
        try:
            return self.c._call(self.sh.worksheet, tab)
        except gspread.WorksheetNotFound:
            if not create:
                return None
            ws = self.c._call(self.sh.add_worksheet, title=tab, rows=200, cols=max(4, len(TABS.get(tab, [])) + 2))
            if tab in TABS:
                self.c._call(ws.update, range_name="A1", values=[TABS[tab]], value_input_option="RAW")
            if self._titles is not None:
                self._titles.add(tab)
            return ws

    def read(self, *tabs) -> dict:
        """{tab: [record dicts]} for existing tabs, in one API call."""
        have = [t for t in tabs if t in self.titles()]
        out = {t: [] for t in tabs}
        if not have:
            return out
        res = self.c._call(self.sh.values_batch_get, [f"'{t}'!A1:Z" for t in have])
        for t, vr in zip(have, res.get("valueRanges", [])):
            rows = vr.get("values", [])
            if not rows:
                continue
            head = rows[0]
            for i, r in enumerate(rows[1:], start=2):
                if any(str(c).strip() for c in r):
                    rec = {h: (r[j] if j < len(r) else "") for j, h in enumerate(head) if h}
                    rec["_row"] = i
                    out[t].append(rec)
        return out

    def bundle(self, tabs, json_tabs=()) -> dict:
        """Several tabs plus JSON cells (settings/profile) in ONE API call - what the dashboard needs per load."""
        have = [t for t in tabs if t in self.titles()]
        have_json = [t for t in json_tabs if t in self.titles()]
        out = {t: [] for t in tabs}
        out.update({t: {} for t in json_tabs})
        if not have and not have_json:
            return out
        res = self.c._call(self.sh.values_batch_get, [f"'{t}'!A1:Z" for t in have] + [f"'{t}'!A1" for t in have_json])
        ranges = res.get("valueRanges", [])
        for t, vr in zip(have, ranges):
            rows = vr.get("values", [])
            head = rows[0] if rows else []
            out[t] = [{**{h: (r[j] if j < len(r) else "") for j, h in enumerate(head) if h}, "_row": i}
                      for i, r in enumerate(rows[1:], start=2) if any(str(c).strip() for c in r)]
        for t, vr in zip(have_json, ranges[len(have):]):
            try:
                out[t] = json.loads((vr.get("values") or [[""]])[0][0] or "{}")
            except (ValueError, IndexError):
                out[t] = {}
        return out

    def _headers(self, ws, tab):
        head = self.c._call(ws.row_values, 1)
        missing = [h for h in TABS[tab] if h not in head]
        if missing:  # older layout: add our new columns at the end, never reorder the user's
            head = head + missing
            self.c._call(ws.update, range_name="A1", values=[head], value_input_option="RAW")
        return head

    def append(self, tab, records):
        if not records:
            return
        ws = self._ws(tab)
        head = self._headers(ws, tab)
        rows = [[_clip(r.get(h, "")) for h in head] for r in records]
        self.c._call(ws.append_rows, rows, value_input_option="RAW", insert_data_option="OVERWRITE", table_range="A1")

    def upsert(self, tab, records, key="Job ID"):
        """Insert or update whole records by key. Fields not given keep their current values."""
        if not records:
            return
        ws = self._ws(tab)
        head = self._headers(ws, tab)
        existing = {r.get(key): r for r in self.read(tab)[tab]}
        updates, new = [], []
        for rec in records:
            cur = existing.get(rec[key])
            if cur:
                merged = {**cur, **rec}
                end = chr(ord("A") + len(head) - 1)
                updates.append({"range": f"A{cur['_row']}:{end}{cur['_row']}", "values": [[_clip(merged.get(h, "")) for h in head]]})
            else:
                new.append(rec)
        if updates:
            self.c._call(ws.batch_update, updates, value_input_option="RAW")
        self.append(tab, new)

    # ---------- JSON cells (settings, profiles, lock) ----------
    def get_json(self, tab, default=None):
        if tab not in self.titles():
            return default if default is not None else {}
        try:
            return json.loads(self.c._call(self._ws(tab).acell, "A1").value or "null") or (default if default is not None else {})
        except ValueError:
            return default if default is not None else {}

    def put_json(self, tab, value):
        self.c._call(self._ws(tab).update, range_name="A1", values=[[json.dumps(value)[:CELL_LIMIT]]], value_input_option="RAW")

    # ---------- runs, usage and lock ----------
    def searches_used_this_month(self, now) -> int:
        month = now.strftime("%Y-%m")
        total = 0
        for r in self.read("Runs")["Runs"]:
            if r.get("Started", "").startswith(month):
                try:
                    total += int(r.get("SerpApi Calls") or 0)
                except ValueError:
                    pass
        return total

    def close_stale_runs(self, now, minutes=15):
        """Runs still marked 'running' long after they started were interrupted (crash, timeout, deploy)."""
        cutoff = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        stale = [{"Run ID": r["Run ID"], "Status": "interrupted"} for r in self.read("Runs")["Runs"]
                 if r.get("Status") == "running" and r.get("Started", "") < cutoff and r.get("Run ID")]
        self.upsert("Runs", stale, key="Run ID")
        return len(stale)

    def recent_successful_run(self, now, minutes=30) -> bool:
        cutoff = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        return any(r.get("Status") == "ok" and r.get("Started", "") >= cutoff for r in self.read("Runs")["Runs"])

    def acquire_lock(self, run_id, minutes=10) -> bool:
        """Cross-instance run lock with a lease, so a crashed run can't block forever.
        ponytail: read-then-write, not atomic; fine for one user's cron + button, not for many writers."""
        utc = lambda d=0: (datetime.now(timezone.utc) + timedelta(minutes=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self.get_json(LOCK_CELL_TAB)
        if cur and cur.get("run_id") != run_id and cur.get("expires", "") > utc():
            return False
        self.put_json(LOCK_CELL_TAB, {"run_id": run_id, "expires": utc(minutes)})
        return self.get_json(LOCK_CELL_TAB).get("run_id") == run_id

    def release_lock(self, run_id):
        if self.get_json(LOCK_CELL_TAB).get("run_id") == run_id:
            self.put_json(LOCK_CELL_TAB, {})

    # ---------- history / audit ----------
    def record(self, job_id, field, old, new, source="dashboard", action_id=None):
        self.append("History", [{"Timestamp": _now(), "Job ID": job_id, "Field": field, "Old": old, "New": new,
                                 "Action ID": action_id or uuid.uuid4().hex[:12], "Source": source}])

    def seen_action(self, action_id, recent=200) -> bool:
        """Idempotency: has this dashboard action already been applied? (retries / double clicks)"""
        if not action_id:
            return False
        return any(r.get("Action ID") == action_id for r in self.read("History")["History"][-recent:])


    # ---------- retry queue ----------
    def retry_queue(self, now_s, limit=5, max_attempts=3) -> list:
        """Needs Review jobs that failed for a transient reason and are due for another attempt.
        Uses no discovery searches; employer look-ups are usually cached."""
        from models import NEEDS_REVIEW, Job
        data = self.read("Verification", "Details", "Jobs")
        latest = {}
        for v in data["Verification"]:
            latest[v.get("Job ID")] = v
        details = {d.get("Job ID"): d for d in data["Details"]}
        out = []
        for row in data["Jobs"]:
            jid = row.get("Job ID")
            v = latest.get(jid)
            if not v or row.get("Verification Status") != NEEDS_REVIEW or v.get("Retry") != "yes":
                continue
            try:
                attempts = int(v.get("Attempts") or 0)
            except ValueError:
                attempts = max_attempts
            if attempts >= max_attempts or (v.get("Next Check") or "") > now_s:
                continue
            url = row.get("Original Listing URL", "")
            out.append(Job(title=row.get("Job Title", ""), company=row.get("Company", ""), location=row.get("Location", ""),
                           employment_type=row.get("Employment Type", ""), description=details.get(jid, {}).get("Description", ""),
                           listing_url=url, links=[url] if url else [], source=row.get("Source Platform", ""),
                           req_id=v.get("Req ID", ""), attempts=attempts))
            if len(out) == limit:
                break
        return out


def new_run_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
