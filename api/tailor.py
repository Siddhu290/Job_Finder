"""/api/tailor (authenticated). Drafts only; nothing is stored or sent anywhere.
POST {"job_id": "...", "resume_text": "..."}       -> suggestions + tailored draft (with truthfulness warnings)
POST {"action": "docx", "text": "...", "name": ""}  -> the given draft as a .docx download"""
import os
import re
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import llm
        import tailor
        body = webapi.read_json(self, limit=200_000)
        if body.get("action") == "docx":
            data = tailor.to_docx(str(body.get("text", ""))[:40000])
            name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(body.get("name") or "resume"))[:60] or "resume"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", f'attachment; filename="{name}.docx"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(data)
        if not webapi.rate_ok(self, "tailor", 10):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        from integrations.google_sheets import SheetsError
        try:
            data = webapi.store(self).read("Jobs", "Details")
            jid = str(body.get("job_id", ""))
            job = next((r for r in data["Jobs"] if r.get("Job ID") == jid), None)
            if not job:
                return webapi.send(self, 404, {"error": "Job not found"})
            desc = str(body.get("job_text") or "") or next((d.get("Description", "") for d in data["Details"] if d.get("Job ID") == jid), "")
            out = tailor.tailor(str(body.get("resume_text", "")), job.get("Job Title", ""), job.get("Company", ""), desc)
            return webapi.send(self, 200, out)
        except llm.LLMError as e:
            return webapi.send(self, 502, {"error": str(e)})
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})
