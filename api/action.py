"""POST /api/action (X-Dashboard-Key):
  {"action": "status", "id": "J...", "status": "Applied" | "Not interested" | "Needs Review"}
  {"action": "clear", "scope": "yesterday" | "all"}   -> rows move to the Archive tab (never deleted)"""
import os
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402

STATUSES = {"Applied", "Not interested", "Needs Review", "Verified"}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Wrong password"})
        body = webapi.read_json(self)
        from integrations.google_sheets import C, SheetsError
        try:
            client = webapi.jobs_client(self)
            if body.get("action") == "status" and body.get("status") in STATUSES and body.get("id"):
                # earlier dashboard actions now go to the application lifecycle (never the verification column)
                import applications
                import uuid
                stage = {"Applied": "Applied", "Not interested": "Not Interested"}.get(body["status"], "Discovered")
                out = applications.apply_change(webapi.store(self), str(body["id"])[:20], {"Stage": stage},
                                                str(body.get("action_id") or uuid.uuid4().hex[:12]))
                return webapi.send(self, 200, out)
            if body.get("action") == "clear" and body.get("scope") in ("yesterday", "all"):
                if body["scope"] == "all":
                    n = client.archive(lambda r: True)
                else:
                    tz = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Kolkata"))
                    day = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")
                    n = client.archive(lambda r: r[C["Date Found"]].startswith(day))
                return webapi.send(self, 200, {"ok": True, "archived": n})
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})
        return webapi.send(self, 400, {"error": "unknown action"})
