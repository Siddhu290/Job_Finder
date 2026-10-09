"""POST /api/application (authenticated). Application lifecycle; every change is in History and can be undone.
{"action": "set", "job_id", "fields": {"Stage": "Applied", "Interview Date": "2026-10-20", ...}, "action_id"}
{"action": "undo", "job_id", "action_id"}  |  {"action": "history", "job_id"}
{"action": "archive" | "restore", "job_ids": [...]}   (archive moves rows to the Archive tab; nothing is deleted)"""
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        if not webapi.rate_ok(self, "application", 60):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        import applications
        from integrations.google_sheets import SheetsError
        body = webapi.read_json(self)
        action, jid = body.get("action"), str(body.get("job_id", ""))[:20]
        aid = str(body.get("action_id") or uuid.uuid4().hex[:12])[:40]
        try:
            st = webapi.store(self)
            if action == "set" and jid and isinstance(body.get("fields"), dict):
                return webapi.send(self, 200, applications.apply_change(st, jid, body["fields"], aid))
            if action == "undo" and jid:
                out = applications.undo(st, jid, aid)
                return webapi.send(self, 200 if out.get("ok") else 404, out)
            if action == "history" and jid:
                return webapi.send(self, 200, {"history": applications.history(st, jid)})
            if action in ("archive", "restore") and isinstance(body.get("job_ids"), list):
                ids = [str(i)[:20] for i in body["job_ids"]][:500]
                n = st.c.archive(lambda r: r[0] in ids) if action == "archive" else st.c.restore(ids)
                webapi.audit(st, "archive", f"{action} {n}", ",".join(ids)[:200])
                return webapi.send(self, 200, {"ok": True, "count": n})
            return webapi.send(self, 400, {"error": "Unknown application action"})
        except ValueError as e:
            return webapi.send(self, 400, {"error": str(e)})
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})
