"""Which storage backend to use, and opening it for a user.

- "postgres" (multi-user): when STORAGE_BACKEND=postgres, or DATABASE_URL is set and STORAGE_BACKEND is unset.
- "sheets" (single-user, the original setup): otherwise. Google Sheets also remains available as a per-user export.
One connection per thread (serverless invocations are single-threaded; the local dev server is threaded)."""
import os
import threading
import uuid

_local = threading.local()


def is_pg() -> bool:
    b = os.getenv("STORAGE_BACKEND", "").strip().lower()
    return b == "postgres" or (not b and bool(os.getenv("DATABASE_URL")))


def conn():
    from storage import pg
    c = getattr(_local, "conn", None)
    if c is None or c.closed or c.broken:
        c = _local.conn = pg.connect()
    return c


def resolve_user(ref: str) -> str:
    """User id from a UUID or an email address. Raises ValueError if unknown."""
    if not ref:
        raise ValueError("a user is required in multi-user mode (--user-id <email or id>)")
    try:
        key, sql = str(uuid.UUID(ref)), "SELECT id FROM users WHERE id = %s"
    except ValueError:
        key, sql = ref.strip().lower(), "SELECT id FROM users WHERE email = %s"
    r = conn().execute(sql, [key]).fetchone()
    if not r:
        raise ValueError(f"unknown user {ref}")
    return str(r["id"])


def open_for_run(cfg, user_ref=None):
    """(jobs_client, store) for a live run."""
    if is_pg():
        from storage.pg import PgJobs, PgStore
        uid = resolve_user(user_ref)
        return PgJobs(conn(), uid), PgStore(conn(), uid)
    from config import credentials_file_is_private
    from integrations.google_sheets import SheetsClient
    from storage.store import Store
    import logging
    if not credentials_file_is_private(cfg.credentials_path):
        logging.getLogger(__name__).warning("%s is readable by other users; run: chmod 600 %s", cfg.credentials_path, cfg.credentials_path)
    sheets = SheetsClient(cfg).open(create_worksheet=True)
    return sheets, Store(sheets)


def open_store(user_id=None):
    if is_pg():
        from storage.pg import PgStore
        if not user_id:
            raise PermissionError("no signed-in user")
        return PgStore(conn(), user_id)
    from config import load_config
    from integrations.google_sheets import SheetsClient
    from storage.store import Store
    return Store(SheetsClient(load_config(require_serpapi=False)).open())


def active_users(limit=50) -> list:
    """Enabled users, least recently searched first (so every user gets served across cron runs)."""
    return [str(r["id"]) for r in conn().execute(
        "SELECT id FROM users WHERE NOT disabled ORDER BY last_run_at NULLS FIRST, created_at LIMIT %s", [limit]).fetchall()]


def user_role(user_id) -> str:
    r = conn().execute("SELECT role FROM users WHERE id = %s", [user_id]).fetchone()
    return r["role"] if r else ""


def user_email(user_id) -> str:
    r = conn().execute("SELECT email FROM users WHERE id = %s", [user_id]).fetchone()
    return r["email"] if r else ""
