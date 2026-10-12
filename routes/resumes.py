"""/api/resumes (signed in). The user's named resume collection (encrypted at rest, private to the user).
GET                                                   -> {"versions": [{id, name, source, job, created, chars}]}
POST {"action": "save", "name", "text", "source", "job"} -> new version
POST {"action": "get" | "delete", "id"}  |  {"action": "rename", "id", "name"}
POST {"action": "details", "id"} -> details read from the resume (or the user's checked ones) + what to check
POST {"action": "save_details", "id", "details"} -> validated, stored encrypted; the template is built from them
POST {"action": "recommend", "job_id" | "job_text"+"job_title", "current_id"} -> closest tailored version for this job (no AI)
A save with "job_id" remembers that job's role and skills, so the version can be recommended for similar jobs."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import resumes
        return webapi.send(self, 200, {"versions": resumes.list_versions(webapi.store(self))})

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import resumes
        import user_secrets
        body, st = webapi.read_json(self, limit=200_000), webapi.store(self)
        action, vid = body.get("action"), str(body.get("id", ""))[:20]
        try:
            if action == "save":
                role, skills = "", []
                if body.get("job_id"):
                    import matching
                    found = webapi.job_text(st, str(body["job_id"]))
                    if found:
                        role, skills = found[0], matching.find_skills(found[2])
                v = resumes.save(st, body.get("name"), str(body.get("text", "")), body.get("source", "pasted"), body.get("job", ""),
                                 role, skills)
                webapi.audit(st, "resume", "version saved", detail=v["name"])
                return webapi.send(self, 200, v)
            if action == "get":
                return webapi.send(self, 200, {"id": vid, "text": resumes.get_text(st, vid)})
            if action == "details":                  # what to show in "Check your details"
                import latex_resume
                text = resumes.get_text(st, vid)
                if latex_resume.is_latex(text):
                    return webapi.send(self, 400, {"error": "A LaTeX resume keeps its own layout; edit the .tex itself"})
                d = resumes.get_details(st, vid) or latex_resume.parse_details(text)
                return webapi.send(self, 200, {"details": d, "issues": latex_resume.check_details(d), "checked": bool(resumes.get_details(st, vid))})
            if action == "save_details":
                import latex_resume
                try:
                    d = latex_resume.clean_details(body.get("details"))
                except ValueError as e:
                    return webapi.send(self, 400, {"error": str(e)})
                v = resumes.set_details(st, vid, d)
                webapi.audit(st, "resume", "details checked", detail=v["name"])
                return webapi.send(self, 200, {"version": v, "details": d, "issues": latex_resume.check_details(d)})
            if action == "recommend":
                title, desc = str(body.get("job_title", ""))[:120], str(body.get("job_text", ""))[:20000]
                if body.get("job_id"):
                    found = webapi.job_text(st, str(body["job_id"]))
                    if not found:
                        return webapi.send(self, 404, {"error": "Job not found"})
                    title, desc = found[0], found[2]
                return webapi.send(self, 200, {"recommendation": resumes.recommend(st, title, desc, str(body.get("current_id", "")))})
            if action == "rename":
                return webapi.send(self, 200, resumes.rename(st, vid, body.get("name")))
            if action == "delete":
                resumes.delete(st, vid)
                webapi.audit(st, "resume", "version deleted", detail=vid)
                return webapi.send(self, 200, {"ok": True})
            return webapi.send(self, 400, {"error": "Unknown action"})
        except KeyError:
            return webapi.send(self, 404, {"error": "No such resume"})
        except (resumes.ResumeError, user_secrets.SecretsError) as e:
            return webapi.send(self, 400, {"error": str(e)})
