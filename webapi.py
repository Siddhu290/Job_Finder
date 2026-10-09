"""Shared helpers for the Vercel functions in api/ (auth, JSON I/O, serverless environment)."""
import hashlib
import hmac
import json
import os
import time
from collections import defaultdict, deque

TMP = "/tmp/job-finder"
MAX_BODY = 10_000


SESSION_HOURS = 12
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}


def send(h, code, body):
    data = json.dumps(body).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    h.send_header("Cache-Control", "private, no-store")
    for k, v in SECURITY_HEADERS.items():
        h.send_header(k, v)
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


def _eq(a, b):
    return bool(b) and hmac.compare_digest(a.encode(), b.encode())


def _secret() -> bytes:
    # Changing DASHBOARD_PASSWORD (or SESSION_SECRET) signs everyone out.
    return hashlib.sha256((os.environ.get("SESSION_SECRET", "") + "|" + os.environ.get("DASHBOARD_PASSWORD", "")).encode()).digest()


def issue_token(now=None) -> str:
    exp = int((now or time.time()) + SESSION_HOURS * 3600)
    return f"{exp}.{hmac.new(_secret(), str(exp).encode(), hashlib.sha256).hexdigest()}"


def token_ok(token: str, now=None) -> bool:
    try:
        exp, sig = token.split(".", 1)
        return int(exp) > (now or time.time()) and _eq(sig, hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest())
    except (ValueError, AttributeError):
        return False


OWNER = {"id": None, "email": "", "name": "Owner", "role": "admin"}


def authorized(h) -> bool:
    """Multi-user (Postgres): a valid per-user session token; the user is attached as h.user.
    Single-user (Sheets): the dashboard session token or the raw password header (scripts/curl)."""
    from storage import backend
    auth = h.headers.get("Authorization", "")
    if backend.is_pg():
        if not auth.startswith("Bearer "):
            return False
        try:
            import accounts
            user = accounts.user_for_token(backend.conn(), auth[7:])
        except Exception:  # database down or misconfigured: deny, never fail open
            return False
        if user:
            h.user = user
        return bool(user)
    if not os.environ.get("DASHBOARD_PASSWORD"):
        return False
    ok = (auth.startswith("Bearer ") and token_ok(auth[7:])) or \
        _eq(h.headers.get("X-Dashboard-Key", ""), os.environ.get("DASHBOARD_PASSWORD", ""))
    if ok:
        h.user = OWNER
    return ok


def user_of(h) -> dict:
    return getattr(h, "user", None) or OWNER


dashboard_ok = authorized  # backwards-compatible name

# ---------- best-effort rate limiting (per serverless instance; resets on cold start) ----------
_hits = defaultdict(deque)


def client_ip(h) -> str:
    fwd = h.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() or (getattr(h, "client_address", None) or ("?",))[0]


def rate_ok(h, bucket: str, per_minute: int, window=60.0) -> bool:
    q, now = _hits[(bucket, client_ip(h))], time.monotonic()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= per_minute:
        return False
    q.append(now)
    return True


def login_blocked(h) -> bool:
    q, now = _hits[("login-fail", client_ip(h))], time.monotonic()
    while q and now - q[0] > 900:
        q.popleft()
    return len(q) >= 5


def login_failed(h):
    _hits[("login-fail", client_ip(h))].append(time.monotonic())


def cron_ok(h) -> bool:
    return _eq(h.headers.get("Authorization", ""), "Bearer " + os.environ["CRON_SECRET"]) if os.environ.get("CRON_SECRET") else False


def read_json(h, limit=MAX_BODY) -> dict:
    n = int(h.headers.get("Content-Length") or 0)
    if n <= 0 or n > limit:
        return {}
    try:
        body = json.loads(h.rfile.read(n))
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def prepare_env(tmp=None):
    """Serverless: writable dirs in /tmp, key file from env, cache kept in the sheet, stop before the 300s cap."""
    tmp = tmp or TMP
    os.makedirs(tmp, exist_ok=True)
    os.environ.setdefault("JOB_FINDER_DATA_DIR", tmp)
    os.environ.setdefault("CACHE_IN_SHEET", "1")
    os.environ.setdefault("RUN_TIME_LIMIT", "240")
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw:
        path = os.path.join(tmp, "credentials.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(raw)
        os.environ["GOOGLE_CREDENTIALS"] = path


def store(h=None):
    """The signed-in user's store (Postgres) or the spreadsheet store (single-user)."""
    from storage import backend
    return backend.open_store(user_of(h)["id"] if h is not None else None)


def jobs_client(h=None):
    return store(h).c


def audit(st, kind, action, job_id="", detail=""):
    """Important user actions go to the History tab (never secrets or resume text)."""
    try:
        st.record(job_id, kind, "", f"{action} {detail}".strip()[:200], source="dashboard")
    except Exception:  # auditing must not break the action itself
        pass


def sheets_client():
    """Editor-access client for dashboard actions."""
    prepare_env()
    from config import load_config
    from integrations.google_sheets import SheetsClient
    return SheetsClient(load_config(require_serpapi=False)).open()


def serpapi_key(h, st=None) -> str:
    """Key used for this user's searches/budget display ('' if none)."""
    import user_secrets
    from storage import backend
    try:
        return user_secrets.key_for_run(st or store(h), backend.is_pg(), user_of(h)["role"] == "admin")[0]
    except Exception:
        return ""


def resume_args(st) -> list:
    """CLI arguments for the active resume profile when 'use in searches' is on."""
    import profiles
    return profiles.search_args(profiles.load(st.get_json("_profile")))
