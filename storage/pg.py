"""Postgres (Neon) storage for multi-user mode. Same interface as the Google Sheets backend, so the job finder,
APIs and dashboard work unchanged:

- PgStore  ~ storage.store.Store        (Details, Verification, Applications, History, Runs, settings/profile JSON)
- PgJobs   ~ integrations.google_sheets.SheetsClient (the Jobs list, archive/restore, company cache)

Isolation: every statement runs in a transaction that first sets app.user_id (row-level security, see
prisma/migrations/0002) AND filters on user_id explicitly. Use DATABASE_URL = Neon's *pooled* connection string."""
import json
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from integrations.google_sheets import HEADERS
from storage.store import Store, TABS

JOB_COLS = dict(zip(HEADERS, ["job_id", "date_found", "title", "company", "location", "experience", "employment_type", "source",
                              "listing_url", "careers_url", "apply_url", "status", "posted_date", "last_checked", "notes"]))
TABLES = {
    "Details": ("job_details", ("job_id",), {"Job ID": "job_id", "Updated": "updated", "Description": "description",
               "Required Skills": "required_skills", "Preferred Skills": "preferred_skills", "Min Years": "min_years",
               "Education": "education", "Closes": "closes", "Contacts": "contacts"}),
    "Verification": ("verification", None, {"Timestamp": "timestamp", "Job ID": "job_id", "Run ID": "run_id", "Status": "status",
                     "Req ID": "req_id", "Reason": "reason", "Checks": "checks", "Last Open Check": "last_open_check",
                     "Retry": "retry", "Attempts": "attempts", "Next Check": "next_check"}),
    "Applications": ("applications", ("job_id",), {h: h.lower().replace(" ", "_").replace("-", "_") for h in TABS["Applications"]}),
    "History": ("history", None, {"Timestamp": "timestamp", "Job ID": "job_id", "Field": "field", "Old": "old", "New": "new",
                "Action ID": "action_id", "Source": "source"}),
    "Runs": ("runs", ("run_id",), {"Run ID": "run_id", "Started": "started", "Finished": "finished", "Trigger": "trigger",
             "Profile": "profile", "Allowed Searches": "allowed_searches", "SerpApi Calls": "serpapi_calls",
             "Discovered": "discovered", "Unique": "unique_jobs", "New Rows": "new_rows", "Verified": "verified",
             "Needs Review": "needs_review", "Errors": "errors", "Status": "status"}),
}
JSONB = {"contacts", "checks"}
INTS = {"attempts", "allowed_searches", "serpapi_calls", "discovered", "unique_jobs", "new_rows", "verified", "needs_review", "errors"}
ORDER = {"verification": "id", "history": "id", "runs": "started", "job_details": "job_id", "applications": "job_id"}


def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    # prepare_threshold=None: Neon's pooler (PgBouncer, transaction mode) does not support prepared statements
    # autocommit: every `with conn.transaction()` is a real BEGIN/COMMIT (never a savepoint inside an implicit transaction)
    return psycopg.connect(url, row_factory=dict_row, prepare_threshold=None, connect_timeout=10, autocommit=True)


def rls_role_available(conn) -> bool:
    """Is the restricted role from migration 0003 usable by this login? Cached per connection."""
    if not hasattr(conn, "_jf_rls_role"):
        r = conn.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls') "
                         "AND pg_has_role(current_user, 'app_rls', 'MEMBER') AS ok").fetchone()
        conn._jf_rls_role = bool(r and r["ok"])
    return conn._jf_rls_role


def rls_status(conn) -> str:
    """'enforced' if per-user isolation is guaranteed by Postgres for this connection, else why not."""
    if rls_role_available(conn):
        return "enforced"
    r = conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
    if r and (r["rolsuper"] or r["rolbypassrls"]):
        return "NOT enforced: the database role bypasses row-level security; run the migrations (0003)"
    return "enforced"


@contextmanager
def user_tx(conn, user_id):
    with conn.transaction():
        if rls_role_available(conn):
            conn.execute("SET LOCAL ROLE app_rls")   # restricted role: RLS applies even if the login role could bypass it
        conn.execute("SELECT set_config('app.user_id', %s, true)", [str(user_id)])
        yield conn


def _to_db(col, v):
    if col in JSONB:
        if isinstance(v, str):
            try:
                v = json.loads(v) if v else ([] if col == "contacts" else {})
            except ValueError:
                v = [] if col == "contacts" else {}
        return json.dumps(v)
    if col == "retry":
        return v in (True, "yes", "true", 1)
    if col in INTS:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    return "" if v is None else str(v)


def _from_db(col, v):
    if col in JSONB:
        return json.dumps(v)          # same shape as a sheet cell: JSON text
    if col == "retry":
        return "yes" if v else ""
    return "" if v is None else v


class PgStore(Store):
    """Store backed by Postgres for one user."""

    def __init__(self, conn, user_id):
        self.conn, self.user_id, self._titles = conn, str(user_id), None
        self.c = PgJobs(conn, user_id)   # same attribute the Sheets Store exposes (archive/restore live there)

    # ---------- primitives (override the Sheets versions) ----------
    def titles(self):
        return set(TABLES) | {"Jobs", "Archive", "_settings", "_profile", "_lock"}

    def _rows(self, tab):
        if tab in ("Jobs", "Archive"):
            cols = ", ".join(f'{c} AS "{h}"' for h, c in JOB_COLS.items())
            rows = self.conn.execute(f"SELECT {cols} FROM jobs WHERE user_id = %s AND archived = %s ORDER BY seq",
                                     [self.user_id, tab == "Archive"]).fetchall()
            return [{**r, "_row": i} for i, r in enumerate(rows, start=2)]
        table, _, cols = TABLES[tab]
        sel = ", ".join(cols.values())
        rows = self.conn.execute(f"SELECT {sel} FROM {table} WHERE user_id = %s ORDER BY {ORDER[table]}", [self.user_id]).fetchall()
        return [{**{h: _from_db(c, r[c]) for h, c in cols.items()}, "_row": i} for i, r in enumerate(rows, start=2)]

    def read(self, *tabs):
        with user_tx(self.conn, self.user_id):
            return {t: (self._rows(t) if t in self.titles() and not t.startswith("_") else []) for t in tabs}

    def bundle(self, tabs, json_tabs=()):
        with user_tx(self.conn, self.user_id):
            out = {t: self._rows(t) for t in tabs if t in self.titles()}
            for t in json_tabs:
                r = self.conn.execute("SELECT value FROM user_docs WHERE user_id = %s AND kind = %s", [self.user_id, t]).fetchone()
                out[t] = r["value"] if r else {}
            return out

    def append(self, tab, records):
        if not records:
            return
        table, _, cols = TABLES[tab]
        conflict = " ON CONFLICT (user_id, action_id) DO NOTHING" if table == "history" else \
            " ON CONFLICT (run_id) DO NOTHING" if table == "runs" else ""
        with user_tx(self.conn, self.user_id):
            for rec in records:
                given = [(c, _to_db(c, rec[h])) for h, c in cols.items() if h in rec]
                names = ", ".join(["user_id"] + [c for c, _ in given])
                marks = ", ".join(["%s"] * (len(given) + 1))
                self.conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks}){conflict}", [self.user_id] + [v for _, v in given])

    def upsert(self, tab, records, key="Job ID"):
        if not records:
            return
        table, pk, cols = TABLES[tab]
        target = "(run_id)" if table == "runs" else "(user_id, job_id)"
        with user_tx(self.conn, self.user_id):
            for rec in records:
                given = [(c, _to_db(c, rec[h])) for h, c in cols.items() if h in rec]
                names = ", ".join(["user_id"] + [c for c, _ in given])
                marks = ", ".join(["%s"] * (len(given) + 1))
                sets = ", ".join(f"{c} = EXCLUDED.{c}" for c, _ in given if c not in pk) or f"{pk[0]} = EXCLUDED.{pk[0]}"
                guard = " WHERE runs.user_id = EXCLUDED.user_id" if table == "runs" else ""
                self.conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks}) ON CONFLICT {target} DO UPDATE SET {sets}{guard}",
                                  [self.user_id] + [v for _, v in given])

    def get_json(self, tab, default=None):
        with user_tx(self.conn, self.user_id):
            r = self.conn.execute("SELECT value FROM user_docs WHERE user_id = %s AND kind = %s", [self.user_id, tab]).fetchone()
        return r["value"] if r and r["value"] else (default if default is not None else {})

    def put_json(self, tab, value):
        with user_tx(self.conn, self.user_id):
            self.conn.execute("INSERT INTO user_docs (user_id, kind, value) VALUES (%s, %s, %s) "
                              "ON CONFLICT (user_id, kind) DO UPDATE SET value = EXCLUDED.value",
                              [self.user_id, tab, json.dumps(value)])

    # ---------- usage, lock, idempotency ----------
    key_fp = "none"   # fingerprint of the SerpApi key in use (set by the run); usage is tracked per key

    def _usage_key(self, now):
        return f"{now.strftime('%Y-%m')}:{self.key_fp}"

    def searches_used_this_month(self, now) -> int:
        r = self.conn.execute("SELECT calls FROM serpapi_usage WHERE month = %s", [self._usage_key(now)]).fetchone()
        return r["calls"] if r else 0

    def add_usage(self, now, calls: int):
        with self.conn.transaction():
            self.conn.execute("INSERT INTO serpapi_usage (month, calls) VALUES (%s, %s) "
                              "ON CONFLICT (month) DO UPDATE SET calls = serpapi_usage.calls + EXCLUDED.calls",
                              [self._usage_key(now), int(calls)])
            self.conn.execute("UPDATE users SET last_run_at = now() WHERE id = %s", [self.user_id])

    def acquire_lock(self, run_id, minutes=10) -> bool:
        """Atomic: succeeds only if there is no unexpired lock held by another run."""
        with user_tx(self.conn, self.user_id):
            r = self.conn.execute(
                "INSERT INTO run_locks (user_id, run_id, expires_at) VALUES (%s, %s, now() + make_interval(mins => %s)) "
                "ON CONFLICT (user_id) DO UPDATE SET run_id = EXCLUDED.run_id, expires_at = EXCLUDED.expires_at "
                "WHERE run_locks.expires_at < now() OR run_locks.run_id = EXCLUDED.run_id RETURNING run_id",
                [self.user_id, run_id, minutes]).fetchone()
        return bool(r)

    def release_lock(self, run_id):
        with user_tx(self.conn, self.user_id):
            self.conn.execute("DELETE FROM run_locks WHERE user_id = %s AND run_id = %s", [self.user_id, run_id])

    def seen_action(self, action_id, recent=200) -> bool:
        if not action_id:
            return False
        with user_tx(self.conn, self.user_id):
            return bool(self.conn.execute("SELECT 1 FROM history WHERE user_id = %s AND action_id = %s",
                                          [self.user_id, action_id]).fetchone())


class PgJobs:
    """The Jobs list for one user, with the SheetsClient methods that main.run and the APIs use.
    read() returns sheet-shaped rows ([HEADERS] + rows) so plan_sync's rules (no repeats, never overwrite
    user-managed statuses, apply URL only when Verified) apply unchanged."""

    email = ""

    def __init__(self, conn, user_id):
        self.conn, self.user_id = conn, str(user_id)
        self._snapshot = []

    def open(self, create_worksheet=False):
        return self

    def _list(self, archived):
        cols = ", ".join(JOB_COLS.values())
        with user_tx(self.conn, self.user_id):
            rows = self.conn.execute(f"SELECT {cols} FROM jobs WHERE user_id = %s AND archived = %s ORDER BY seq",
                                     [self.user_id, archived]).fetchall()
        return [[r[c] or "" for c in JOB_COLS.values()] for r in rows]

    def read(self):
        rows = self._list(False)
        self._snapshot = [r[0] for r in rows]   # row number n -> job id, for A1-style updates from plan_sync
        return [list(HEADERS)] + rows

    def write_headers(self):
        pass

    def read_archive(self):
        return self._list(True)

    def apply(self, appends, updates):
        cols = list(JOB_COLS.values())
        with user_tx(self.conn, self.user_id):
            for u in updates:
                letter, row = u["range"][0], int(u["range"][1:])
                col = cols[ord(letter) - ord("A")]
                if col == "job_id" or not (2 <= row < len(self._snapshot) + 2):
                    continue
                self.conn.execute(f"UPDATE jobs SET {col} = %s, updated_at = now() WHERE user_id = %s AND job_id = %s",
                                  [str(u["values"][0][0]), self.user_id, self._snapshot[row - 2]])
            for r in appends:
                vals = (list(r) + [""] * len(cols))[:len(cols)]
                self.conn.execute(f"INSERT INTO jobs (user_id, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))}) "
                                  "ON CONFLICT (user_id, job_id) DO NOTHING", [self.user_id] + [str(v) for v in vals])

    def archive(self, which) -> int:
        ids = [r[0] for r in self._list(False) if which(r)]
        if ids:
            with user_tx(self.conn, self.user_id):
                self.conn.execute("UPDATE jobs SET archived = true WHERE user_id = %s AND job_id = ANY(%s)", [self.user_id, ids])
        return len(ids)

    def restore(self, job_ids) -> int:
        with user_tx(self.conn, self.user_id):
            cur = self.conn.execute("UPDATE jobs SET archived = false WHERE user_id = %s AND job_id = ANY(%s) AND archived",
                                    [self.user_id, list(job_ids)])
            return cur.rowcount

    def set_status(self, job_id, status) -> bool:
        with user_tx(self.conn, self.user_id):
            return self.conn.execute("UPDATE jobs SET status = %s WHERE user_id = %s AND job_id = %s",
                                     [status, self.user_id, job_id]).rowcount > 0

    # shared, non-personal employer look-up cache
    def read_cache(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM company_cache").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def write_cache(self, data: dict):
        with self.conn.transaction():
            for k, v in data.items():
                self.conn.execute("INSERT INTO company_cache (key, value, updated) VALUES (%s, %s, now()) "
                                  "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated = now()", [k, json.dumps(v)])
