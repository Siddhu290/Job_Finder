"""GET /api/health: liveness + configuration presence (never values). Signed in: also checks the sheet."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402

SINGLE_USER = ("SERPAPI_KEY", "GOOGLE_SHEET_ID", "DASHBOARD_PASSWORD")
MULTI_USER = ("DATABASE_URL", "SESSION_SECRET", "SECRETS_KEY")
OPTIONAL = ("CRON_SECRET", "LLM_API_KEY", "INVITE_CODE", "ALLOW_SIGNUP")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from storage import backend
        multi = backend.is_pg()
        required = MULTI_USER if multi else SINGLE_USER
        cfg = {k: bool(os.environ.get(k)) for k in SINGLE_USER + MULTI_USER + OPTIONAL}
        cfg["GOOGLE_CREDENTIALS"] = bool(os.environ.get("GOOGLE_CREDENTIALS_JSON") or os.environ.get("GOOGLE_CREDENTIALS"))
        ok = all(cfg[k] for k in required) and (multi or cfg["GOOGLE_CREDENTIALS"])
        from routes.register import policy
        body = {"ok": ok, "config": cfg, "auth": "users" if multi else "password",
                "registration": policy() if multi else "closed"}
        if multi:
            try:
                from storage import pg
                body["data_isolation"] = pg.rls_status(backend.conn())
                body["ok"] = body["ok"] and body["data_isolation"] == "enforced"
            except Exception as e:  # noqa: BLE001
                body["data_isolation"], body["ok"] = f"database unreachable ({type(e).__name__})", False
        if webapi.authorized(self):
            try:
                webapi.store(self).get_json("_settings")   # proves storage is reachable for this user
                body["storage"] = "ok"
            except Exception as e:
                body["storage"], body["ok"] = f"error ({type(e).__name__})", False
        return webapi.send(self, 200 if body["ok"] else 503, body)
