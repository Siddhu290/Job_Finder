"""/api/tailor (authenticated). Drafts only; nothing is stored or sent anywhere.
POST {"job_id" | "job_text"+"job_title", "resume_id" | "resume_text"} -> suggestions + tailored draft (truthfulness warnings)
POST {"action": "docx", "text": "...", "name": ""}  -> the given draft as a .docx download
A LaTeX resume gets {"mode": "latex", "edits": [{id, find, replace, reason, warning}], ...} instead of a draft:
POST {"action": "latex_apply", "resume_id" | "tex", "edits": [{find, replace}]} -> {"tex", "applied", "skipped"} (re-checked)
POST {"action": "latex", "text": "..."}          -> a plain-text resume as a .tex document (no AI)"""
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
        import latex_resume
        if body.get("action") == "latex":
            return webapi.send(self, 200, {"tex": latex_resume.to_latex(str(body.get("text", ""))[:40000])})
        if body.get("action") == "latex_apply":
            tex = str(body.get("tex", ""))
            if body.get("resume_id"):
                import resumes
                try:
                    tex = resumes.get_text(webapi.store(self), str(body["resume_id"]))
                except KeyError:
                    return webapi.send(self, 404, {"error": "No such resume"})
            if not latex_resume.is_latex(tex):
                return webapi.send(self, 400, {"error": "Not a LaTeX resume"})
            edits = body.get("edits") if isinstance(body.get("edits"), list) else []
            desc = str(body.get("job_text", ""))[:20000]
            if body.get("job_id"):
                found = webapi.job_text(webapi.store(self), str(body["job_id"]))
                desc = found[2] if found else desc
            return webapi.send(self, 200, latex_resume.apply_edits(tex[:latex_resume.MAX_TEX], edits[:latex_resume.MAX_EDITS + latex_resume.MAX_ADDITIONS], desc))
        if not webapi.rate_ok(self, "tailor", 10):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        from integrations.google_sheets import SheetsError
        try:
            st = webapi.store(self)
            data = st.read("Jobs", "Details")
            jid = str(body.get("job_id", ""))
            job = next((r for r in data["Jobs"] if r.get("Job ID") == jid), None)
            if not job and not body.get("job_text"):
                return webapi.send(self, 404, {"error": "Job not found"})
            job = job or {"Job Title": str(body.get("job_title", ""))[:120], "Company": ""}
            desc = str(body.get("job_text") or "") or next((d.get("Description", "") for d in data["Details"] if d.get("Job ID") == jid), "")
            text = str(body.get("resume_text", ""))
            if body.get("resume_id"):
                import resumes
                try:
                    text = resumes.get_text(st, str(body["resume_id"]))
                except KeyError:
                    return webapi.send(self, 404, {"error": "No such resume"})
            if latex_resume.is_latex(text):         # the user's own .tex: exact edits to approve, layout untouched
                out = latex_resume.propose_edits(text, job.get("Job Title", ""), job.get("Company", ""), desc,
                                                 webapi.llm_key(self, st) or None)
                return webapi.send(self, 200, {**out, "tex": text})
            out = tailor.tailor(text, job.get("Job Title", ""), job.get("Company", ""), desc,
                                webapi.llm_key(self, st) or None)
            return webapi.send(self, 200, out)
        except llm.LLMError as e:
            return webapi.send(self, 502, {"error": str(e)})
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})
