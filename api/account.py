"""/api/account (signed in). GET -> who am I. POST (multi-user mode):
{"action": "change_password", "current", "new"} | {"action": "sign_out_everywhere"} | {"action": "delete", "password"}
Deleting removes the account and all of its data (jobs, applications, resume profiles, history, saved keys)."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        from storage import backend
        u = webapi.user_of(self)
        return webapi.send(self, 200, {"email": u["email"], "name": u["name"], "role": u["role"], "multi_user": backend.is_pg()})

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import accounts
        from storage import backend
        if not backend.is_pg():
            return webapi.send(self, 400, {"error": "Single-user mode: change DASHBOARD_PASSWORD on the server instead"})
        if not webapi.rate_ok(self, "account", 10):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        body, uid = webapi.read_json(self), webapi.user_of(self)["id"]
        try:
            if body.get("action") == "change_password":
                accounts.change_password(backend.conn(), uid, str(body.get("current", "")), str(body.get("new", "")))
            elif body.get("action") == "sign_out_everywhere":
                accounts.sign_out_everywhere(backend.conn(), uid)
            elif body.get("action") == "delete":
                accounts.delete_account(backend.conn(), uid, str(body.get("password", "")))
            else:
                return webapi.send(self, 400, {"error": "Unknown account action"})
        except accounts.AccountError as e:
            return webapi.send(self, 400, {"error": str(e)})
        return webapi.send(self, 200, {"ok": True})
