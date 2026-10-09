"""POST /api/register {"email", "password", "name", "invite_code"} (multi-user mode).
Sign-up policy (env): ALLOW_SIGNUP=true opens registration; INVITE_CODE, if set, is additionally required.
The very first account becomes the admin. Each account's data is private to it (row-level security)."""
import hmac
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


def policy() -> str:
    """'open' | 'invite' | 'closed'."""
    if os.environ.get("ALLOW_SIGNUP", "").strip().lower() in ("1", "true", "yes"):
        return "invite" if os.environ.get("INVITE_CODE") else "open"
    return "invite" if os.environ.get("INVITE_CODE") else "closed"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        import accounts
        from storage import backend
        mode = policy()
        if not backend.is_pg() or mode == "closed":
            return webapi.send(self, 403, {"error": "Sign-up is closed; ask the admin for an account"})
        if not webapi.rate_ok(self, "register", 5, window=3600):
            return webapi.send(self, 429, {"error": "Too many sign-ups from this network; try again later"})
        body = webapi.read_json(self)
        if mode == "invite" and not hmac.compare_digest(str(body.get("invite_code", "")).encode(), os.environ["INVITE_CODE"].encode()):
            return webapi.send(self, 403, {"error": "Wrong invite code"})
        c = backend.conn()
        first = c.execute("SELECT NOT EXISTS (SELECT 1 FROM users) AS first").fetchone()["first"]
        try:
            u = accounts.create_user(c, str(body.get("email", "")), str(body.get("password", "")), str(body.get("name", "")),
                                     "admin" if first else "user")
        except accounts.AccountError as e:
            return webapi.send(self, 400, {"error": str(e)})
        import sheet_mirror
        sheet_mirror.create_tab(u["email"])   # their own tab in the spreadsheet (best effort)
        return webapi.send(self, 200, {"token": accounts.issue_token(u["id"], 1), "expires_in": accounts.SESSION_HOURS * 3600,
                                       "name": u["name"], "role": u["role"]})
