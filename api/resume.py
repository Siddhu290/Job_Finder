"""/api/resume (authenticated). Resume profiles: extracted, user-editable fields only; resumes are never stored.
GET                                              -> {"use_in_search", "active", "profiles": [...]}
POST {"file": "<base64>", "filename": "cv.pdf", "name": "..."} -> parse PDF/DOCX in memory, AI extraction, new profile;
                                                    the extracted text is returned for the browser to keep (not stored)
POST {"text": "...", "name": "..."}              -> new profile from pasted resume text
POST {"action": "update", "id": ..., ...fields}  -> save the user's corrections
POST {"action": "activate", "id": ...} | {"action": "delete", "id": ...} | {"action": "use_in_search", "value": bool}"""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import profiles
        from integrations.google_sheets import SheetsError
        try:
            return webapi.send(self, 200, profiles.load(webapi.store(self).get_json("_profile")))
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        if not webapi.rate_ok(self, "resume", 20):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        import llm
        import profiles
        from integrations.google_sheets import SheetsError
        import base64
        import binascii
        import resume_parser
        body = webapi.read_json(self, limit=4_200_000)
        text = None
        try:
            action = body.get("action")
            if isinstance(body.get("file"), str) and not action:
                try:
                    raw = base64.b64decode(body["file"], validate=True)
                except (binascii.Error, ValueError):
                    return webapi.send(self, 400, {"error": "The upload was corrupted; try again"})
                text = resume_parser.extract_text(str(body.get("filename", "")), raw)
            elif isinstance(body.get("text"), str) and not action:
                text = body["text"]
            st = webapi.store(self)
            c = profiles.load(st.get_json("_profile"))
            if text is not None:
                profiles.add(c, llm.extract_profile(text), body.get("name", ""))
            elif action == "update":
                profiles.update(c, str(body.get("id")), body)
            elif action == "activate" and any(p["id"] == body.get("id") for p in c["profiles"]):
                c["active"] = body["id"]
            elif action == "delete":
                profiles.delete(c, str(body.get("id")))
            elif action == "use_in_search":
                c["use_in_search"] = bool(body.get("value")) and bool(profiles.active(c))
            else:
                return webapi.send(self, 400, {"error": "Unknown resume action"})
            st.put_json("_profile", c)
            webapi.audit(st, "resume", action or "create", "")
            return webapi.send(self, 200, {**c, "text": text} if text is not None else c)
        except resume_parser.ResumeFileError as e:
            return webapi.send(self, 400, {"error": str(e)})
        except (llm.LLMError, ValueError) as e:
            return webapi.send(self, 502 if isinstance(e, llm.LLMError) else 400, {"error": str(e)})
        except KeyError:
            return webapi.send(self, 404, {"error": "No such resume profile"})
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})
