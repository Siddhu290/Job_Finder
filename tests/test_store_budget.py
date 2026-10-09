"""Budget controller and the spreadsheet-backed store (Sheets API faked in memory)."""
import json
from datetime import datetime

import gspread
import pytest

import budget
from storage.store import TABS, Store


# ---------- budget ----------
def test_budget_rules():
    b = budget.plan(30, 250, {}, None)
    assert b.allowed == 30 and b.confirmed_left is None                     # nothing known: per-run cap only
    b = budget.plan(30, 250, {}, 240)
    assert b.allowed == 10 and "estimated used 240" in b.reason             # monthly safety limit, estimated
    b = budget.plan(30, 250, {"this_month_usage": 245, "total_searches_left": 100}, 10)
    assert b.allowed == 5 and "confirmed used 245" in b.reason              # provider data wins over estimate
    b = budget.plan(30, 1000, {"total_searches_left": 4}, 0)
    assert b.allowed == 2 and "only 4 searches left" in b.reason            # keep a safety margin
    assert budget.plan(30, 250, {"total_searches_left": 1}, 0).allowed == 0  # exhausted: run must not search


# ---------- fake spreadsheet ----------
class FakeWS:
    def __init__(self, title, rows=None):
        self.title, self.rows = title, rows or []

    def _set(self, r, c, v):
        while len(self.rows) < r:
            self.rows.append([])
        row = self.rows[r - 1]
        while len(row) < c:
            row.append("")
        row[c - 1] = v

    def update(self, range_name, values, value_input_option=None):
        col, row = ord(range_name[0]) - 64, int("".join(ch for ch in range_name.split(":")[0] if ch.isdigit()))
        for i, vals in enumerate(values):
            for j, v in enumerate(vals):
                self._set(row + i, col + j, v)

    def batch_update(self, updates, value_input_option=None):
        for u in updates:
            self.update(u["range"], u["values"])

    def append_rows(self, rows, **kw):
        self.rows += [list(r) for r in rows]

    def row_values(self, n):
        return list(self.rows[n - 1]) if len(self.rows) >= n else []

    def acell(self, a1):
        return type("C", (), {"value": self.rows[0][0] if self.rows and self.rows[0] else None})()


class FakeSheet:
    def __init__(self):
        self.tabs = {}

    def worksheets(self):
        return list(self.tabs.values())

    def worksheet(self, t):
        if t not in self.tabs:
            raise gspread.WorksheetNotFound(t)
        return self.tabs[t]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWS(title)
        return self.tabs[title]

    def values_batch_get(self, ranges):
        return {"valueRanges": [{"values": self.tabs[r.split("'")[1]].rows} for r in ranges]}


class FakeClient:
    def __init__(self):
        self.ws = type("W", (), {"spreadsheet": FakeSheet()})()

    def _call(self, fn, *a, **k):
        return fn(*a, **k)


@pytest.fixture
def st():
    return Store(FakeClient())


def test_upsert_append_and_header_mapping(st):
    st.upsert("Applications", [{"Job ID": "J1", "Stage": "Saved"}])
    st.upsert("Applications", [{"Job ID": "J1", "Stage": "Applied", "Applied Date": "2026-10-09"}, {"Job ID": "J2", "Stage": "Saved"}])
    rows = st.read("Applications")["Applications"]
    assert [(r["Job ID"], r["Stage"]) for r in rows] == [("J1", "Applied"), ("J2", "Saved")]
    assert rows[0]["Applied Date"] == "2026-10-09" and rows[0]["_row"] == 2
    ws = st.sh.tabs["Applications"]
    ws.rows[0] = ["Notes", "Job ID", "Stage"]            # user reordered / old layout: new columns get added, not reordered
    st.upsert("Applications", [{"Job ID": "J2", "Stage": "Offer"}])
    assert ws.rows[0][:3] == ["Notes", "Job ID", "Stage"] and set(TABS["Applications"]) <= set(ws.rows[0])
    assert {r["Job ID"]: r["Stage"] for r in st.read("Applications")["Applications"]}["J2"] == "Offer"


def test_missing_tabs_read_empty(st):
    assert st.read("History", "Runs") == {"History": [], "Runs": []}
    assert st.get_json("_settings") == {}


def test_lock_lease(st):
    assert st.acquire_lock("run-a")
    assert not st.acquire_lock("run-b")                  # held
    st.release_lock("run-a")
    assert st.acquire_lock("run-b")
    st.put_json("_lock", {"run_id": "run-b", "expires": "2000-01-01T00:00:00Z"})   # crashed run: lease expired
    assert st.acquire_lock("run-c")


def test_usage_and_idempotency(st):
    st.append("Runs", [{"Run ID": "r1", "Started": "2026-10-09 08:00", "SerpApi Calls": 12},
                       {"Run ID": "r0", "Started": "2026-09-30 20:00", "SerpApi Calls": 30}])
    assert st.searches_used_this_month(datetime(2026, 10, 9)) == 12
    st.record("J1", "Stage", "Saved", "Applied", action_id="act-1")
    assert st.seen_action("act-1") and not st.seen_action("act-2") and not st.seen_action("")


def test_retry_queue(st):
    st.append("Jobs", [])
    st.sh.tabs["Jobs"] = FakeWS("Jobs", [["Job ID", "Job Title", "Company", "Location", "Original Listing URL", "Verification Status"],
                                         ["J1", "Data Analyst", "Acme", "Pune", "https://acme.com/j/1", "Needs Review"],
                                         ["J2", "Data Engineer", "Beta", "Pune", "https://beta.com/j/2", "Needs Review"],
                                         ["J3", "Data Analyst", "Gamma", "Pune", "https://g.com/j/3", "Verified"]])
    st.append("Verification", [
        {"Job ID": "J1", "Retry": "yes", "Attempts": 1, "Next Check": "2026-10-09 07:00"},
        {"Job ID": "J2", "Retry": "yes", "Attempts": 3, "Next Check": "2026-10-09 07:00"},   # gave up
        {"Job ID": "J3", "Retry": "yes", "Attempts": 1, "Next Check": "2026-10-09 07:00"}])  # already verified
    st.upsert("Details", [{"Job ID": "J1", "Description": "SQL, Python"}])
    q = st.retry_queue("2026-10-09 08:00")
    assert [(j.company, j.attempts, j.description) for j in q] == [("Acme", 1, "SQL, Python")]
    assert st.retry_queue("2026-10-09 06:00") == []       # not due yet


def test_stale_runs_and_duplicate_cron_guard(st):
    st.append("Runs", [{"Run ID": "old", "Started": "2026-10-09 07:00", "Status": "running"},
                       {"Run ID": "fresh", "Started": "2026-10-09 07:58", "Status": "running"},
                       {"Run ID": "done", "Started": "2026-10-09 07:50", "Status": "ok"}])
    now = datetime(2026, 10, 9, 8, 0)
    assert st.close_stale_runs(now) == 1
    status = {r["Run ID"]: r["Status"] for r in st.read("Runs")["Runs"]}
    assert status == {"old": "interrupted", "fresh": "running", "done": "ok"}
    assert st.recent_successful_run(now) and not st.recent_successful_run(datetime(2026, 10, 9, 20, 0))
