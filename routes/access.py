"""/api/access (multi-user mode, signed in). Using the admin's API keys.
GET                                         -> user: {"status": ...}; admin: + {"pending", "approved", "users"}
POST {"action": "request", "message"}        -> ask an admin for access
POST {"action": "approve"|"deny"|"revoke", "user_id"}   (admins only)"""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import access
        from storage import backend
        if not backend.is_pg():
            return webapi.send(self, 200, {"status": "approved", "single_user": True})
        u, c = webapi.user_of(self), backend.conn()
        body = access.status(c, u["id"])
        if u["role"] == "admin":
            body.update(access.overview(c, u))
        return webapi.send(self, 200, body)

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import access
        from storage import backend
        if not backend.is_pg():
            return webapi.send(self, 400, {"error": "Only available in multi-user mode"})
        if not webapi.rate_ok(self, "access", 20):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        body, u, c = webapi.read_json(self), webapi.user_of(self), backend.conn()
        action, target = body.get("action"), str(body.get("user_id", ""))[:40]
        try:
            if action == "request":
                out = access.request(c, u, body.get("message", ""))
            elif action in ("approve", "deny"):
                out = access.decide(c, u, target, action == "approve")
            elif action == "revoke":
                out = access.revoke(c, u, target)
            else:
                return webapi.send(self, 400, {"error": "Unknown action"})
        except PermissionError as e:
            return webapi.send(self, 403, {"error": str(e)})
        except (access.AccessError, ValueError) as e:
            return webapi.send(self, 400, {"error": str(e)})
        try:
            webapi.audit(webapi.store(self), "access", f"{action} {target or ''}".strip())
        except Exception:
            pass
        return webapi.send(self, 200, out)
