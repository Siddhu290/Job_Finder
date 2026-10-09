"""Vercel entry points: cron auth, serverless env preparation, sheet-backed cache, run time limit."""
import io
import json
import os
import stat
from unittest.mock import MagicMock

import gspread

from api import run as run_api
from tests.test_google_sheets import make_client


def call(h_cls, headers):
    h = h_cls.__new__(h_cls)
    h.headers, h.wfile, sent = headers, io.BytesIO(), {}
    h.send_response = lambda c: sent.setdefault("code", c)
    h.send_header = h.end_headers = lambda *a: None
    h.do_GET()
    return sent["code"], json.loads(h.wfile.getvalue())


def test_run_endpoint_requires_cron_secret(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert call(run_api.handler, {"Authorization": "Bearer x"})[0] == 401   # not configured -> refuse
    monkeypatch.setenv("CRON_SECRET", "cronsecret123")
    assert call(run_api.handler, {"Authorization": "Bearer nope"})[0] == 401
    assert call(run_api.handler, {})[0] == 401


def test_run_endpoint_prepares_env_and_runs(monkeypatch, tmp_path):
    import main
    monkeypatch.setenv("CRON_SECRET", "cronsecret123")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", '{"type": "service_account"}')
    for k in ("JOB_FINDER_DATA_DIR", "CACHE_IN_SHEET", "RUN_TIME_LIMIT", "GOOGLE_CREDENTIALS"):
        monkeypatch.setenv(k, "x")   # registers the original state so it is restored after the test
        monkeypatch.delenv(k)
    import webapi
    monkeypatch.setattr(webapi, "TMP", str(tmp_path))
    monkeypatch.setattr(main, "main", lambda argv: print("==== Run summary ====") or 0)
    code, body = call(run_api.handler, {"Authorization": "Bearer cronsecret123"})
    assert code == 200 and body["exit_code"] == 0 and "Run summary" in body["summary"]
    key = tmp_path / "credentials.json"
    assert os.environ["GOOGLE_CREDENTIALS"] == str(key) and stat.S_IMODE(key.stat().st_mode) == 0o600
    assert os.environ["CACHE_IN_SHEET"] == "1" and os.environ["JOB_FINDER_DATA_DIR"] == str(tmp_path)


def test_cache_tab_roundtrip(tmp_path, monkeypatch):
    client, gc = make_client(tmp_path, monkeypatch)
    client.open()
    sh = client.ws.spreadsheet
    sh.worksheet.side_effect = gspread.WorksheetNotFound("_cache")
    assert client.read_cache() == {}
    client.write_cache({"acme": {"domain": "acme.com", "checked": "2026-10-09"}})
    tab = sh.add_worksheet.return_value
    tab.clear.assert_called_once()
    rows = tab.update.call_args.kwargs["values"]
    assert rows == [["acme", json.dumps({"domain": "acme.com", "checked": "2026-10-09"})]]
    sh.worksheet.side_effect = None
    sh.worksheet.return_value = MagicMock(get_all_values=MagicMock(return_value=rows + [["bad", "{not json"]]))
    assert client.read_cache() == {"acme": {"domain": "acme.com", "checked": "2026-10-09"}}


def post(h_cls, headers, body):
    raw = json.dumps(body).encode()
    h = h_cls.__new__(h_cls)
    h.headers = {**headers, "Content-Length": str(len(raw))}
    h.rfile, h.wfile, sent = io.BytesIO(raw), io.BytesIO(), {}
    h.send_response = lambda c: sent.setdefault("code", c)
    h.send_header = h.end_headers = lambda *a: None
    h.do_POST()
    return sent["code"], json.loads(h.wfile.getvalue())


def test_dashboard_search_validates_and_passes_profile(monkeypatch):
    import webapi
    webapi._hits.clear()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    seen = []
    monkeypatch.setattr(run_api, "run_job", lambda argv: seen.append(argv) or (0, "summary"))
    key = {"X-Dashboard-Key": "pw"}
    assert post(run_api.handler, {"X-Dashboard-Key": "no"}, {"locations": ["Pune"]})[0] == 401
    assert post(run_api.handler, key, {"locations": ["Pune; rm -rf"], "mode": "any"})[0] == 400
    assert post(run_api.handler, key, {"locations": [], "mode": "any"})[0] == 400
    assert post(run_api.handler, key, {"locations": ["Pune"], "mode": "hack"})[0] == 400
    assert post(run_api.handler, key, {"locations": ["Pune", "Navi Mumbai"], "mode": "onsite"})[0] == 200
    assert post(run_api.handler, key, {"locations": [], "mode": "wfh"})[0] == 200
    assert seen == [["--trigger", "dashboard", "--mode", "onsite", "--locations", "Pune;Navi Mumbai"],
                    ["--trigger", "dashboard", "--mode", "wfh"]]
    code, out = post(run_api.handler, key, {"locations": ["Pune"], "mode": "any", "preview": True, "max_age_days": 3})
    assert code == 200 and out["preview"] and seen[-1] == ["--plan", "--mode", "any", "--locations", "Pune", "--max-age-days", "3"]
    import webapi
    webapi._hits.clear()
    for _ in range(3):
        post(run_api.handler, key, {"locations": ["Pune"]})
    assert post(run_api.handler, key, {"locations": ["Pune"]})[0] == 429     # 3 real searches per 10 minutes
    webapi._hits.clear()


def test_actions(monkeypatch):
    from api import action
    import webapi
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    client = MagicMock()
    client.set_status.return_value = True
    client.archive.return_value = 3
    monkeypatch.setattr(webapi, "jobs_client", lambda *a: client)
    key = {"X-Dashboard-Key": "pw"}
    assert post(action.handler, {}, {"action": "clear", "scope": "all"})[0] == 401
    from storage.store import Store
    from tests.test_store_budget import FakeClient
    mem = Store(FakeClient())
    monkeypatch.setattr(webapi, "store", lambda *a: mem)
    code, out = post(action.handler, key, {"action": "status", "id": "J1", "status": "Applied", "action_id": "a1"})
    assert code == 200 and out["changed"]["Stage"] == "Applied"
    assert mem.read("Applications")["Applications"][0]["Stage"] == "Applied"   # lifecycle, not the Jobs status column
    client.set_status.assert_not_called()
    assert post(action.handler, key, {"action": "status", "id": "J1", "status": "Hacked"})[0] == 400
    assert post(action.handler, key, {"action": "clear", "scope": "yesterday"}) == (200, {"ok": True, "archived": 3})
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    which = client.archive.call_args.args[0]
    yday = (datetime.now(ZoneInfo("Asia/Kolkata")) - timedelta(days=1)).strftime("%Y-%m-%d")
    from integrations.google_sheets import C, HEADERS
    r = [""] * len(HEADERS)
    r[C["Date Found"]] = yday + " 08:00"
    assert which(r) and not which([""] * len(HEADERS))


def test_health_reports_presence_not_values(monkeypatch):
    from api import health
    monkeypatch.setenv("SERPAPI_KEY", "supersecret-serp-key")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", "{}")
    code, body = call(health.handler, {})
    assert code == 200 and body["config"]["SERPAPI_KEY"] is True and "supersecret" not in json.dumps(body)
    assert "sheet" not in body                                   # sheet check only when signed in
    monkeypatch.delenv("SERPAPI_KEY")
    assert call(health.handler, {})[0] == 503


def test_dev_server_blocks_path_traversal(tmp_path):
    import dev_server
    h = dev_server.Dev.__new__(dev_server.Dev)
    h.path, h.wfile, sent = "/../.env", io.BytesIO(), {}
    h.send_response = lambda c: sent.setdefault("code", c)
    h.send_header = h.end_headers = lambda *a: None
    h.do_GET()
    assert b"<!doctype html>" in h.wfile.getvalue() and b"SERPAPI" not in h.wfile.getvalue()


def test_dashboard_store_works_on_vercel_with_json_credentials(monkeypatch, tmp_path):
    """Vercel has no key file: GOOGLE_CREDENTIALS_JSON must be enough for every endpoint, not just runs."""
    import webapi
    from storage import backend
    key = json.dumps({"type": "service_account", "client_email": "bot@proj.iam.gserviceaccount.com", "private_key": "k"})
    for k in ("GOOGLE_CREDENTIALS", "DATABASE_URL", "STORAGE_BACKEND"):
        monkeypatch.setenv(k, "x")
        monkeypatch.delenv(k)
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", key)
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    monkeypatch.setattr(webapi, "TMP", str(tmp_path))
    opened = {}

    class FakeClient:
        def __init__(self, cfg):
            opened["path"] = cfg.credentials_path
            self.ws = type("W", (), {"spreadsheet": None})()

        def open(self, **kw):
            return self
    monkeypatch.setattr("integrations.google_sheets.SheetsClient", FakeClient)
    assert not backend.is_pg()
    webapi.store()
    path = tmp_path / "credentials.json"
    assert opened["path"] == path and path.read_text() == key and stat.S_IMODE(path.stat().st_mode) == 0o600
