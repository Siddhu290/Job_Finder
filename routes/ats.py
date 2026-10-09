"""POST /api/ats (signed in): ATS-style score of one resume against one job.
Body: {"resume_id" | "resume_text", "job_id" | "job_text", "job_title"}"""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import ats
        import resumes
        import user_secrets
        body, st = webapi.read_json(self, limit=200_000), webapi.store(self)
        try:
            text = resumes.get_text(st, str(body["resume_id"])) if body.get("resume_id") else str(body.get("resume_text", ""))
        except KeyError:
            return webapi.send(self, 404, {"error": "No such resume"})
        except user_secrets.SecretsError as e:
            return webapi.send(self, 400, {"error": str(e)})
        jd, title = str(body.get("job_text", ""))[:20000], str(body.get("job_title", ""))[:120]
        if body.get("job_id"):
            data = st.read("Jobs", "Details")
            job = next((r for r in data["Jobs"] if r.get("Job ID") == body["job_id"]), None)
            if not job:
                return webapi.send(self, 404, {"error": "Job not found"})
            jd = jd or next((d.get("Description", "") for d in data["Details"] if d.get("Job ID") == body["job_id"]), "")
            title = title or job.get("Job Title", "")
        if len(text.strip()) < 100:
            return webapi.send(self, 400, {"error": "Choose a resume (or paste one) first"})
        if len(jd.strip()) < 80:
            return webapi.send(self, 400, {"error": "This job has no stored description; paste the job description instead"})
        return webapi.send(self, 200, ats.score(text, jd, title))
