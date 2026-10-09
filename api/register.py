"""POST /api/register {"email", "password", "name", "invite_code"} (multi-user mode only).
Self-registration requires INVITE_CODE (there is no open sign-up: searches spend SerpApi credits)."""
import hmac
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        import accounts
        from storage import backend
        invite = os.environ.get("INVITE_CODE", "")
        if not backend.is_pg() or not invite:
            return webapi.send(self, 403, {"error": "Registration is closed; ask the admin for an account"})
        if not webapi.rate_ok(self, "register", 5, window=3600):
            return webapi.send(self, 429, {"error": "Too many attempts; try again later"})
        body = webapi.read_json(self)
        if not hmac.compare_digest(str(body.get("invite_code", "")).encode(), invite.encode()):
            return webapi.send(self, 403, {"error": "Wrong invite code"})
        try:
            u = accounts.create_user(backend.conn(), str(body.get("email", "")), str(body.get("password", "")), str(body.get("name", "")))
        except accounts.AccountError as e:
            return webapi.send(self, 400, {"error": str(e)})
        import sheet_mirror
        sheet_mirror.create_tab(u["email"])   # their own tab in the spreadsheet (best effort)
        return webapi.send(self, 200, {"token": accounts.issue_token(u["id"], 1), "expires_in": accounts.SESSION_HOURS * 3600})
