"""End-to-end run with SerpApi, the web and Google Sheets all faked."""
import json

import pytest

import config
import http_client
import main
from integrations.google_sheets import C, HEADERS
from tests.test_verification import ACME_KG, CAREERS, GH_API, GH_JOB, GH_POSTING, HOME, FakeWeb
from verification import ats_clients

GJ = {"jobs_results": [
    {"title": "Data Analyst", "company_name": "Acme Analytics", "location": "Pune, Maharashtra, India",
     "via": "via LinkedIn", "description": "Freshers welcome, 0-1 years experience.",
     "detected_extensions": {"posted_at": "1 day ago"},
     "apply_options": [{"link": "https://in.linkedin.com/jobs/view/1"}, {"link": GH_JOB}]},
    {"title": "Senior Data Engineer", "company_name": "Other", "location": "Pune, India", "description": ""},
    {"title": "Data Analyst", "company_name": "Gamma", "location": "Remote", "description": "Work from anywhere"},
]}


class FakeSheets:
    initial = []

    def __init__(self, cfg):
        self.values, self.applied = list(FakeSheets.initial), []
        FakeSheets.last = self
        self.email = "bot@x"

    def open(self, create_worksheet=False):
        return self

    def read(self):
        return self.values

    def write_headers(self):
        self.values = [list(HEADERS)]

    def read_archive(self):
        return []

    def apply(self, appends, updates):
        self.applied.append((appends, updates))
        self.values += appends


class FakeStore:
    """In-memory stand-in for storage.store.Store."""
    last = None

    def __init__(self, client):
        self.tabs, self.locked = {}, False
        FakeStore.last = self

    def searches_used_this_month(self, now):
        return 0

    def get_json(self, tab, default=None):
        return self.tabs.get(tab, {})

    def put_json(self, tab, value):
        self.tabs[tab] = value

    def acquire_lock(self, run_id, minutes=10):
        self.locked = True
        return True

    def release_lock(self, run_id):
        self.locked = False

    def retry_queue(self, now_s, limit=5, max_attempts=3):
        return []

    def recent_successful_run(self, now, minutes=30):
        return False

    def close_stale_runs(self, now, minutes=15):
        return 0

    def append(self, tab, records):
        self.tabs.setdefault(tab, []).extend(records)

    def upsert(self, tab, records, key="Job ID"):
        rows = self.tabs.setdefault(tab, [])
        for r in records:
            cur = next((x for x in rows if x.get(key) == r[key]), None)
            cur.update(r) if cur else rows.append(dict(r))


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    (tmp_path / "credentials.json").write_text(json.dumps({"type": "service_account", "client_email": "bot@x", "private_key": "k"}))
    (tmp_path / "credentials.json").chmod(0o600)
    monkeypatch.setenv("SERPAPI_KEY", "test-key-0000000000")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    for k in ("GOOGLE_CREDENTIALS", "CACHE_IN_SHEET", "JOB_FINDER_DATA_DIR", "RUN_TIME_LIMIT"):
        monkeypatch.setenv(k, "x")
        monkeypatch.delenv(k)
    monkeypatch.setattr(main, "STOP", False)

    def search(self, **p):
        self.calls += 1
        if p["engine"] == "google_jobs":
            return GJ if self.calls == 1 else {}
        return {"knowledge_graph": ACME_KG} if p["q"] == "Acme Analytics" else {}
    monkeypatch.setattr(main.SerpApi, "search", search)

    web = FakeWeb(pages={HOME: (200, '<a href="/careers">Careers</a>'),
                         CAREERS: (200, '<a href="https://boards.greenhouse.io/acmeanalytics">Jobs</a>'),
                         GH_JOB: (200, "Data Analyst")},
                  api={GH_API: GH_POSTING})
    monkeypatch.setattr(http_client, "get_page", web.get_page)
    monkeypatch.setattr(http_client, "get_json", web.get_json)
    ats_clients.fetch_posting.cache_clear()
    monkeypatch.setattr(main, "SheetsClient", FakeSheets)
    monkeypatch.setattr(main.store, "Store", FakeStore)
    monkeypatch.setattr(main.backend, "is_pg", lambda: False)
    monkeypatch.setattr(main.backend, "open_for_run", lambda cfg, user=None: (lambda sh: (sh, FakeStore(sh)))(FakeSheets(cfg)))
    monkeypatch.setattr(main.budget, "account", lambda key: {})   # never call SerpApi from unit tests
    FakeSheets.initial, FakeSheets.last = [], None
    return tmp_path


def test_dry_run_writes_nothing(world, capsys):
    assert main.main(["--dry-run", "--max-calls", "6"]) == 0
    out = capsys.readouterr().out
    assert "[Verified] Data Analyst | Acme Analytics" in out and f"APPLY:   {GH_JOB}" in out
    assert "DRY RUN" in out and FakeSheets.last is None
    audit = next((world / "logs").glob("verification-*.jsonl")).read_text()
    assert "linked from the official site" in audit and "test-key-0000000000" not in audit


def test_live_run_appends_then_dedupes(world, capsys):
    assert main.main(["--max-calls", "6"]) == 0
    sheet = FakeSheets.last
    assert sheet.values[0] == HEADERS and len(sheet.values) == 2
    row = sheet.values[1]
    assert row[C["Verification Status"]] == "Verified" and row[C["Official Apply URL"]] == GH_JOB
    assert row[C["Original Listing URL"]] == GH_JOB

    # second run against the same sheet: no new row, Last Checked updated
    FakeSheets.initial = sheet.values
    ats_clients.fetch_posting.cache_clear()
    assert main.main(["--max-calls", "6"]) == 0
    appends, updates = FakeSheets.last.applied[-1]
    assert appends == [] and any(u["range"] == "N2" for u in updates)
    assert "test-key-0000000000" not in (world / "logs" / "job_finder.log").read_text()


def test_time_limit_stops_early_but_still_saves(world, monkeypatch):
    monkeypatch.setenv("RUN_TIME_LIMIT", "0.001")
    import time
    monkeypatch.setattr(main, "discover", lambda *a, **k: (time.sleep(0.05), [])[1])
    assert main.main(["--max-calls", "6"]) == 0
    assert main.STOP is True and FakeSheets.last.values[0] == HEADERS   # headers/write step still ran
    monkeypatch.delenv("RUN_TIME_LIMIT")
    assert main.main(["--dry-run", "--max-calls", "6"]) == 0 and main.STOP is False  # next run starts fresh


def test_live_run_records_run_details_and_verification(world):
    assert main.main(["--max-calls", "6"]) == 0
    st = FakeStore.last
    [run] = st.tabs["Runs"]
    assert run["Status"] == "ok" and run["Allowed Searches"] == 6 and run["SerpApi Calls"] >= 1 and not st.locked
    [ver] = [v for v in st.tabs["Verification"] if v["Status"] == "Verified"]
    assert ver["Checks"]["open_status"]["status"] == "pass" and ver["Last Open Check"] and ver["Run ID"] == run["Run ID"]
    [det] = st.tabs["Details"]
    assert "SQL" not in det["Required Skills"] or det["Description"]   # description stored for re-scoring
    assert det["Job ID"] == ver["Job ID"]


def test_plan_spends_nothing(world, capsys, monkeypatch):
    monkeypatch.setattr(main.budget, "account", lambda key: {"total_searches_left": 5, "this_month_usage": 245})
    calls = []
    monkeypatch.setattr(main.SerpApi, "search", lambda self, **p: calls.append(p) or {})
    assert main.main(["--plan", "--locations", "Pune;Mumbai"]) == 0
    out = capsys.readouterr().out
    assert calls == [] and "Searches allowed this run: 3" in out and "1. Data Analyst fresher Pune" in out and "more queries not run" in out


def test_budget_exhausted_stops_safely(world, monkeypatch):
    monkeypatch.setattr(main.budget, "account", lambda key: {"total_searches_left": 1, "this_month_usage": 249})
    calls = []
    monkeypatch.setattr(main.SerpApi, "search", lambda self, **p: calls.append(p) or {})
    assert main.main(["--max-calls", "6"]) == 0 and calls == []


def test_duplicate_cron_call_is_skipped(world, monkeypatch):
    monkeypatch.setattr(FakeStore, "recent_successful_run", lambda self, now, minutes=30: True)
    calls = []
    monkeypatch.setattr(main.SerpApi, "search", lambda self, **p: calls.append(p) or {})
    assert main.main(["--trigger", "cron", "--max-calls", "6"]) == 0 and calls == []
    assert main.main(["--trigger", "dashboard", "--max-calls", "6"]) == 0 and calls   # manual searches still run


def test_use_saved_settings(world, monkeypatch):
    monkeypatch.setattr(main, "saved_settings_args", lambda user=None: ["--locations", "Mumbai", "--mode", "wfh"])
    seen = {}
    real = main.run
    monkeypatch.setattr(main, "run", lambda args: seen.update(loc=args.locations, mode=args.mode) or 0)
    assert main.main(["--use-saved-settings", "--trigger", "cron"]) == 0
    assert seen == {"loc": "Mumbai", "mode": "wfh"}
