"""Integration tests against a real, throwaway Postgres (started for this test session, migrations applied).
Skipped automatically when no Postgres server binaries are available.

The app connects as a NON-superuser role (superusers bypass row-level security), like Neon's app role."""
import glob
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
psycopg = pytest.importorskip("psycopg")


def _bin(name):
    found = sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{name}")) or ([shutil.which(name)] if shutil.which(name) else [])
    return found[-1] if found else None


@pytest.fixture(scope="session")
def pg(tmp_path_factory):
    initdb, pg_ctl = _bin("initdb"), _bin("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.skip("no local Postgres server binaries")
    d = tmp_path_factory.mktemp("pg")
    sock = tmp_path_factory.mktemp("sock")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    subprocess.run([initdb, "-D", str(d / "data"), "-U", "postgres", "--auth=trust", "-E", "UTF8"], check=True, capture_output=True)
    subprocess.run([pg_ctl, "-D", str(d / "data"), "-o", f"-p {port} -k {sock} -c listen_addresses=''", "-l", str(d / "log"), "-w", "start"],
                   check=True, capture_output=True)
    admin = f"postgresql://postgres@/postgres?host={sock}&port={port}"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute("CREATE DATABASE jobs_test")
    db_admin = f"postgresql://postgres@/jobs_test?host={sock}&port={port}"
    with psycopg.connect(db_admin, autocommit=True) as c:
        for f in sorted((ROOT / "prisma" / "migrations").glob("*/migration.sql")):
            c.execute(f.read_text())
        c.execute("CREATE ROLE app_user LOGIN; GRANT ALL ON ALL TABLES IN SCHEMA public TO app_user; "
                  "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_user;")
        c.execute("CREATE ROLE owner_user LOGIN; GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO owner_user;")
    yield {"app": f"postgresql://app_user@/jobs_test?host={sock}&port={port}", "admin": db_admin,
           "owner": f"postgresql://owner_user@/jobs_test?host={sock}&port={port}"}
    subprocess.run([pg_ctl, "-D", str(d / "data"), "-m", "immediate", "stop"], capture_output=True)


@pytest.fixture
def db(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg["app"])
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("SECRETS_KEY", "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=")
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    from storage import backend
    backend._local.conn = None
    with psycopg.connect(pg["admin"], autocommit=True) as c:
        c.execute("TRUNCATE users, company_cache, serpapi_usage CASCADE")
    yield backend
    if getattr(backend._local, "conn", None):
        backend._local.conn.close()
        backend._local.conn = None


def users(backend):
    import accounts
    c = backend.conn()
    a = accounts.create_user(c, "asha@example.com", "correct horse battery", "Asha")
    b = accounts.create_user(c, "bala@example.com", "another long password", "Bala")
    return a["id"], b["id"]


# ---------- accounts ----------
def test_accounts_password_lockout_and_sessions(db):
    import accounts
    c = db.conn()
    a, _ = users(db)
    with pytest.raises(accounts.AccountError, match="already exists"):
        accounts.create_user(c, "ASHA@example.com", "whatever long pass")
    with pytest.raises(accounts.AccountError, match="at least 10"):
        accounts.create_user(c, "new@example.com", "short")
    u = accounts.authenticate(c, "Asha@Example.com", "correct horse battery")
    tok = accounts.issue_token(u["id"], u["session_version"])
    assert accounts.user_for_token(c, tok)["email"] == "asha@example.com"
    for _ in range(4):
        with pytest.raises(accounts.AccountError, match="Wrong email or password"):
            accounts.authenticate(c, "asha@example.com", "nope")
    with pytest.raises(accounts.AccountError):
        accounts.authenticate(c, "asha@example.com", "nope")                       # 5th failure locks
    with pytest.raises(accounts.AccountError, match="Too many failed attempts"):
        accounts.authenticate(c, "asha@example.com", "correct horse battery")      # locked even with the right password
    with pytest.raises(accounts.AccountError, match="Wrong email or password"):
        accounts.authenticate(c, "nobody@example.com", "x")                        # no account enumeration
    accounts.sign_out_everywhere(c, a)
    assert accounts.user_for_token(c, tok) is None                                  # old sessions revoked
    stored = c.execute("SELECT password_hash FROM users WHERE id = %s", [a]).fetchone()["password_hash"]
    assert stored.startswith("scrypt$") and "correct horse" not in stored


# ---------- isolation ----------
def test_row_level_security_isolates_users(db, pg):
    from storage.pg import PgJobs, PgStore
    a, b = users(db)
    c = db.conn()
    PgJobs(c, a).apply([["JA1", "2026-10-09 08:00", "Data Analyst", "Acme"] + [""] * 11], [])
    PgStore(c, a).put_json("_settings", {"locations": ["Pune"]})
    PgStore(c, a).append("History", [{"Job ID": "JA1", "Field": "Stage", "New": "Applied", "Action ID": "x1"}])
    # B sees nothing of A's
    assert PgJobs(c, b).read() == [PgJobs(c, b).read()[0]]
    assert PgStore(c, b).get_json("_settings") == {} and PgStore(c, b).read("History")["History"] == []
    # even raw SQL without a WHERE clause only returns the current user's rows
    with c.transaction():
        c.execute("SELECT set_config('app.user_id', %s, true)", [b])
        assert c.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO jobs (user_id, job_id) VALUES (%s, 'X')", [a])     # can't write into A's data
    # no user set -> no rows at all
    assert c.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0
    # FORCE row level security: even the table owner is isolated
    with psycopg.connect(pg["admin"], autocommit=True) as adm:
        adm.execute("ALTER TABLE jobs OWNER TO owner_user")
    try:
        with psycopg.connect(pg["owner"], autocommit=True) as own:
            assert own.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    finally:
        with psycopg.connect(pg["admin"], autocommit=True) as adm:
            adm.execute("ALTER TABLE jobs OWNER TO postgres")


def test_delete_account_removes_all_user_data(db):
    import accounts
    from storage.pg import PgJobs, PgStore
    a, b = users(db)
    c = db.conn()
    PgJobs(c, a).apply([["JA1"] + [""] * 14], [])
    PgJobs(c, b).apply([["JB1"] + [""] * 14], [])
    PgStore(c, a).upsert("Applications", [{"Job ID": "JA1", "Stage": "Applied"}])
    accounts.delete_account(c, a, "correct horse battery")
    assert c.execute("SELECT count(*) AS n FROM users").fetchone()["n"] == 1
    assert [r[0] for r in PgJobs(c, b).read()[1:]] == ["JB1"]                          # B untouched


# ---------- store semantics (same contract as the Sheets backend) ----------
def test_store_contract(db):
    from datetime import datetime
    from storage.pg import PgJobs, PgStore
    a, _ = users(db)
    c = db.conn()
    st, jobs = PgStore(c, a), PgJobs(c, a)
    jobs.apply([["J1", "2026-10-08 08:00", "Data Analyst", "Acme", "Pune"] + [""] * 6 + ["Needs Review", "", "", ""],
                ["J2", "2026-10-09 08:00", "Data Engineer", "Beta", "Pune"] + [""] * 6 + ["Verified", "", "", ""]], [])
    jobs.apply([["J1"] + [""] * 14], [])                                               # duplicate append ignored
    rows = jobs.read()
    assert [r[0] for r in rows[1:]] == ["J1", "J2"]
    jobs.apply([], [{"range": "L2", "values": [["Closed"]]}, {"range": "N3", "values": [["2026-10-09 20:00"]]}])
    assert [r[11] for r in jobs.read()[1:]] == ["Closed", "Verified"] and jobs.read()[2][13] == "2026-10-09 20:00"
    assert jobs.archive(lambda r: r[0] == "J1") == 1 and [r[0] for r in jobs.read_archive()] == ["J1"]
    assert jobs.restore(["J1"]) == 1 and len(jobs.read()) == 3
    st.upsert("Details", [{"Job ID": "J1", "Description": "SQL", "Contacts": [{"type": "published", "value": "hr@acme.com"}]}])
    st.upsert("Details", [{"Job ID": "J1", "Required Skills": "SQL"}])                # partial update keeps other fields
    d = st.read("Details")["Details"][0]
    assert d["Description"] == "SQL" and d["Required Skills"] == "SQL" and json.loads(d["Contacts"])[0]["value"] == "hr@acme.com"
    st.append("Verification", [{"Job ID": "J1", "Status": "Needs Review", "Checks": {"open_status": {"status": "unknown"}}, "Retry": "yes", "Attempts": 1}])
    v = st.read("Verification")["Verification"][0]
    assert v["Retry"] == "yes" and json.loads(v["Checks"])["open_status"]["status"] == "unknown"
    st.record("J1", "Stage", "", "Saved", action_id="act-1")
    st.record("J1", "Stage", "", "Saved", action_id="act-1")                          # idempotent at the DB level
    assert len(st.read("History")["History"]) == 1 and st.seen_action("act-1")
    b = st.bundle(("Jobs", "Details", "Applications"), ("_settings", "_profile"))
    assert len(b["Jobs"]) == 2 and b["_settings"] == {} and b["Applications"] == []
    st.key_fp = "abc"
    now = datetime(2026, 10, 9, 8)
    st.add_usage(now, 7)
    st.add_usage(now, 5)
    assert st.searches_used_this_month(now) == 12
    st.key_fp = "other-key"
    assert st.searches_used_this_month(now) == 0                                        # usage is per SerpApi key


def test_atomic_run_lock(db):
    from storage.pg import PgStore
    a, b = users(db)
    c = db.conn()
    assert PgStore(c, a).acquire_lock("run-1")
    assert not PgStore(c, a).acquire_lock("run-2")
    assert PgStore(c, b).acquire_lock("run-3")                                          # locks are per user
    PgStore(c, a).release_lock("run-1")
    assert PgStore(c, a).acquire_lock("run-2")


def test_lifecycle_and_profiles_work_on_postgres(db):
    from datetime import date
    import applications
    import profiles
    import llm
    from storage.pg import PgStore
    a, b = users(db)
    st = PgStore(db.conn(), a)
    applications.apply_change(st, "J1", {"Stage": "Applied"}, "a1", date(2026, 10, 9))
    applications.apply_change(st, "J1", {"Stage": "Technical Interview", "Interview Date": "2026-10-15"}, "a2", date(2026, 10, 9))
    applications.undo(st, "J1", "u1")
    rec = st.read("Applications")["Applications"][0]
    assert rec["Stage"] == "Applied" and rec["Interview Date"] == "" and rec["Applied Date"] == "2026-10-09"
    c = profiles.load({})
    profiles.add(c, llm.clean_profile({"roles": ["Data Analyst"]}), "CV")
    st.put_json("_profile", c)
    assert profiles.active(profiles.load(st.get_json("_profile")))["name"] == "CV"
    assert PgStore(db.conn(), b).read("Applications")["Applications"] == []


def test_serpapi_key_encrypted_per_user(db):
    import user_secrets
    from storage.pg import PgStore
    a, b = users(db)
    c = db.conn()
    user_secrets.save_serpapi_key(PgStore(c, a), "abcdef0123456789abcdef0123456789")
    raw = c.execute("SELECT value FROM user_docs").fetchall()                            # no user set: RLS hides it
    assert raw == []
    with c.transaction():
        c.execute("SELECT set_config('app.user_id', %s, true)", [a])
        stored = json.dumps(c.execute("SELECT value FROM user_docs WHERE kind = '_secrets'").fetchone()["value"], ensure_ascii=False)
    assert "abcdef0123456789" not in stored and "…6789" in stored                      # encrypted; only a hint in clear
    assert user_secrets.get_serpapi_key(PgStore(c, a)) == "abcdef0123456789abcdef0123456789"
    assert user_secrets.key_for_run(PgStore(c, b), multi_user=True, is_admin=False) == ("", "none")
    os.environ["SERPAPI_KEY"] = "server-key-000000000000"
    try:
        assert user_secrets.key_for_run(PgStore(c, b), True, False)[1] == "none"        # users never spend the server key
        assert user_secrets.key_for_run(PgStore(c, b), True, True)[1] == "server"       # admins may
    finally:
        del os.environ["SERPAPI_KEY"]


def test_full_run_on_postgres(db, monkeypatch, tmp_path):
    """The real main.run against Postgres (network faked): results land in the right user's rows only."""
    import config
    import http_client
    import main
    from storage.pg import PgJobs, PgStore
    from tests.test_main import GJ
    from tests.test_verification import ACME_KG, CAREERS, GH_API, GH_JOB, GH_POSTING, HOME, FakeWeb
    from verification import ats_clients
    a, b = users(db)
    import user_secrets
    user_secrets.save_serpapi_key(PgStore(db.conn(), a), "userkey0123456789abcdef")
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(main, "STOP", False)
    monkeypatch.setattr(main.budget, "account", lambda key: {})
    used_keys = []

    def search(self, **p):
        used_keys.append(self.api_key)
        self.calls += 1
        if p["engine"] == "google_jobs":
            return GJ if self.calls == 1 else {}
        return {"knowledge_graph": ACME_KG} if p["q"] == "Acme Analytics" else {}
    monkeypatch.setattr(main.SerpApi, "search", search)
    web = FakeWeb(pages={HOME: (200, '<a href="/careers">Careers</a>'),
                         CAREERS: (200, '<a href="https://boards.greenhouse.io/acmeanalytics">Jobs</a>'), GH_JOB: (200, "Data Analyst")},
                  api={GH_API: GH_POSTING})
    monkeypatch.setattr(http_client, "get_page", web.get_page)
    monkeypatch.setattr(http_client, "get_json", web.get_json)
    ats_clients.fetch_posting.cache_clear()
    assert main.main(["--max-calls", "6", "--user-id", "asha@example.com"]) == 0
    assert set(used_keys) == {"userkey0123456789abcdef"}                                 # Asha's own key was used
    rows = PgJobs(db.conn(), a).read()[1:]
    assert len(rows) == 1 and rows[0][11] == "Verified"
    run = PgStore(db.conn(), a).read("Runs")["Runs"][0]
    assert run["Status"] == "ok" and run["SerpApi Calls"] >= 1
    assert PgJobs(db.conn(), b).read()[1:] == []                                         # Bala sees nothing
    assert main.main(["--max-calls", "6", "--user-id", "bala@example.com"]) == 1         # no key of her own -> refused


# ---------- HTTP endpoints in multi-user mode ----------
def _login(email, password):
    from routes import login
    from tests.test_vercel import post
    return post(login.handler, {"X-Forwarded-For": "10.0.0.%d" % (hash(email) % 200)}, {"email": email, "password": password})


def test_endpoints_are_per_user(db, monkeypatch):
    import webapi
    from routes import account, application, register, serpapi, settings as settings_api
    from tests.test_vercel import call, post
    webapi._hits.clear()
    users(db)
    code, a = _login("asha@example.com", "correct horse battery")
    assert code == 200
    _, b = _login("bala@example.com", "another long password")
    A, B = {"Authorization": "Bearer " + a["token"]}, {"Authorization": "Bearer " + b["token"]}
    assert post(settings_api.handler, A, {"locations": ["Mumbai"], "roles": ["Business Analyst"]})[1]["roles"] == ["Business Analyst"]
    assert call(settings_api.handler, B)[1]["locations"] == ["Pune", "Bengaluru", "Nashik"]          # Bala keeps defaults
    post(application.handler, A, {"action": "set", "job_id": "J1", "fields": {"Stage": "Saved"}})
    assert post(application.handler, B, {"action": "history", "job_id": "J1"})[1]["history"] == []   # can't see Asha's
    assert call(settings_api.handler, {"X-Dashboard-Key": "anything"})[0] == 401                       # no shared password in this mode
    assert call(settings_api.handler, {"Authorization": "Bearer forged.1.9999999999.abc"})[0] == 401
    # SerpApi key: validated with SerpApi first, then stored encrypted; only a hint comes back
    monkeypatch.setattr("budget.account", lambda key: {"total_searches_left": 99} if key == "goodkey0123456789abcd" else {})
    assert post(serpapi.handler, A, {"key": "badkey0123456789abcdef"})[0] == 400
    code, st = post(serpapi.handler, A, {"key": "goodkey0123456789abcd"})
    assert code == 200 and st == {"source": "own", "hint": "…abcd", "searches_left": 99, "used_this_month": None, "plan": None}
    assert "goodkey" not in json.dumps(call(serpapi.handler, A)[1])
    assert call(serpapi.handler, B)[1]["source"] == "none"
    assert post(serpapi.handler, A, {"action": "remove"})[1]["source"] == "none"
    # registration needs the invite code
    monkeypatch.setenv("INVITE_CODE", "letmein-2026")
    assert post(register.handler, {}, {"email": "c@example.com", "password": "long enough pass", "invite_code": "nope"})[0] == 403
    code, r = post(register.handler, {}, {"email": "c@example.com", "password": "long enough pass", "invite_code": "letmein-2026"})
    assert code == 200 and call(account.handler, {"Authorization": "Bearer " + r["token"]})[1]["email"] == "c@example.com"
    # change password signs out old sessions
    assert post(account.handler, A, {"action": "change_password", "current": "wrong", "new": "x" * 12})[0] == 400
    assert post(account.handler, A, {"action": "change_password", "current": "correct horse battery", "new": "brand new password"})[0] == 200
    assert call(account.handler, A)[0] == 401
    webapi._hits.clear()


def test_registration_closed_without_invite(db, monkeypatch):
    from routes import register
    from tests.test_vercel import post
    monkeypatch.delenv("INVITE_CODE", raising=False)
    assert post(register.handler, {}, {"email": "x@example.com", "password": "long enough pass"})[0] == 403


def test_import_sheet_into_user_account(db):
    """Single-user spreadsheet data moves into one user's Postgres rows (the sheet is only read)."""
    import manage
    from storage.pg import PgJobs, PgStore
    from storage.store import Store
    from tests.test_store_budget import FakeClient, FakeWS
    a, b = users(db)
    sheet = Store(FakeClient())
    H = ["Job ID", "Date Found", "Job Title", "Company", "Location", "Experience Requirement", "Employment Type", "Source Platform",
         "Original Listing URL", "Official Careers URL", "Official Apply URL", "Verification Status", "Job Posted Date", "Last Checked", "Notes"]
    sheet.sh.tabs["Jobs"] = FakeWS("Jobs", [H, ["J1", "2026-10-09 13:08", "Data Analyst", "Acme"] + [""] * 7 + ["Needs Review", "", "", ""]])
    sheet.sh.tabs["Archive"] = FakeWS("Archive", [H, ["J0", "2026-10-01 08:00", "Data Engineer", "Old Co"] + [""] * 11])
    sheet.upsert("Applications", [{"Job ID": "J1", "Stage": "Applied", "Applied Date": "2026-10-09"}])
    sheet.record("J1", "Stage", "", "Applied", action_id="h1")
    sheet.put_json("_settings", {"locations": ["Pune"]})
    counts = manage.import_sheet(db.conn(), a, sheet)
    assert counts["Jobs"] == 1 and counts["Archive"] == 1
    jobs = PgJobs(db.conn(), a)
    assert [r[0] for r in jobs.read()[1:]] == ["J1"] and [r[0] for r in jobs.read_archive()] == ["J0"]
    st = PgStore(db.conn(), a)
    assert st.read("Applications")["Applications"][0]["Stage"] == "Applied" and st.get_json("_settings") == {"locations": ["Pune"]}
    assert manage.import_sheet(db.conn(), a, sheet)["Jobs"] == 1 and len(PgJobs(db.conn(), a).read()) == 2   # re-import: no duplicates
    assert PgJobs(db.conn(), b).read()[1:] == []


def test_each_user_gets_own_tab_and_sync(db, monkeypatch):
    """Tab created at registration; a search syncs only that user's jobs to that user's tab."""
    import sheet_mirror
    import webapi
    from routes import register, sheet
    from storage.pg import PgJobs, PgStore
    from tests.test_vercel import call, post
    created, synced = [], []
    monkeypatch.setattr(sheet_mirror, "configured", lambda: True)
    monkeypatch.setattr(sheet_mirror, "create_tab", lambda email: created.append(email) or True)
    monkeypatch.setattr(sheet_mirror, "sync_user", lambda email, rows: synced.append((email, [r[0] for r in rows]))
                        or {"tab": sheet_mirror.tab_title(email), "added": len(rows), "updated": 0})
    monkeypatch.setenv("INVITE_CODE", "code-123")
    webapi._hits.clear()
    code, r = post(register.handler, {}, {"email": "new@example.com", "password": "long enough pass", "invite_code": "code-123"})
    assert code == 200 and created == ["new@example.com"]
    a, b = users(db)
    PgJobs(db.conn(), a).apply([["JA"] + [""] * 14], [])
    PgJobs(db.conn(), b).apply([["JB"] + [""] * 14], [])
    _, tok = _login("asha@example.com", "correct horse battery")
    A = {"Authorization": "Bearer " + tok["token"]}
    assert call(sheet.handler, A)[1] == {"configured": True, "enabled": True, "tab": "Jobs - asha@example.com"}
    code, out = post(sheet.handler, A, {"action": "sync"})
    assert code == 200 and synced[-1] == ("asha@example.com", ["JA"])                  # only Asha's jobs, to Asha's tab
    import main
    st = PgStore(db.conn(), b)
    main.mirror_to_sheet(PgJobs(db.conn(), b), st, "bala@example.com", {"errors": []})
    assert synced[-1] == ("bala@example.com", ["JB"])
    st.put_json("_settings", {"sheet_mirror": False})                                   # user switched it off
    n = len(synced)
    main.mirror_to_sheet(PgJobs(db.conn(), b), st, "bala@example.com", {"errors": []})
    assert len(synced) == n
    webapi._hits.clear()
