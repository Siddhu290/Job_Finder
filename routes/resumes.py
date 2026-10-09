"""/api/resumes (signed in). The user's named resume collection (encrypted at rest, private to the user).
GET                                                   -> {"versions": [{id, name, source, job, created, chars}]}
POST {"action": "save", "name", "text", "source", "job"} -> new version
POST {"action": "get" | "delete", "id"}  |  {"action": "rename", "id", "name"}"""
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
                v = resumes.save(st, body.get("name"), str(body.get("text", "")), body.get("source", "pasted"), body.get("job", ""))
                webapi.audit(st, "resume", "version saved", detail=v["name"])
                return webapi.send(self, 200, v)
            if action == "get":
                return webapi.send(self, 200, {"id": vid, "text": resumes.get_text(st, vid)})
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
