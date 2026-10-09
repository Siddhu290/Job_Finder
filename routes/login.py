"""POST /api/login.
Multi-user: {"email", "password"} -> per-user session token (5 failures lock the account for 15 minutes).
Single-user: {"password"} -> session token (5 failures per IP per 15 minutes)."""
import hmac
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        from storage import backend
        if webapi.login_blocked(self):
            return webapi.send(self, 429, {"error": "Too many failed attempts; try again in 15 minutes"})
        body = webapi.read_json(self)
        if backend.is_pg():
            import accounts
            try:
                u = accounts.authenticate(backend.conn(), str(body.get("email", "")), str(body.get("password", "")))
                return webapi.send(self, 200, {"token": accounts.issue_token(u["id"], u["session_version"]),
                                               "expires_in": accounts.SESSION_HOURS * 3600, "name": u["name"]})
            except accounts.AccountError as e:
                webapi.login_failed(self)
                return webapi.send(self, 401, {"error": str(e)})
        expected = os.environ.get("DASHBOARD_PASSWORD", "")
        if not expected:
            return webapi.send(self, 500, {"error": "DASHBOARD_PASSWORD is not configured on the server"})
        if not hmac.compare_digest(str(body.get("password", "")).encode(), expected.encode()):
            webapi.login_failed(self)
            return webapi.send(self, 401, {"error": "Wrong password"})
        return webapi.send(self, 200, {"token": webapi.issue_token(), "expires_in": webapi.SESSION_HOURS * 3600})
