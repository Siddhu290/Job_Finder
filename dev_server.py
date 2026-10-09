#!/usr/bin/env python3
"""Local preview of the Vercel app: http://127.0.0.1:8000 (uses .env and the local key file).
Routes /api/<name> to api/<name>.py exactly like Vercel, and serves public/ for everything else."""
import importlib
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
load_dotenv(ROOT / ".env")
import json  # noqa: E402
HEADERS = {h["key"]: h["value"] for h in json.loads((ROOT / "vercel.json").read_text())["headers"][0]["headers"]
           if h["key"] != "Strict-Transport-Security"}   # same security headers as production (no HSTS on http)
ROUTES = {"jobs", "run", "action", "resume", "login", "application", "settings", "analytics", "tailor", "health",
          "register", "account", "serpapi", "sheet", "keys", "resumes", "ats", "access"}


class Dev(BaseHTTPRequestHandler):
    def _api(self, method):
        name = urlparse(self.path).path.removeprefix("/api/").strip("/")
        if name not in ROUTES:
            return self.send_error(404)
        fn = getattr(importlib.import_module(f"routes.{name}").handler, method, None)
        return fn(self) if fn else self.send_error(405)

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._api("do_POST")
        self.send_error(404)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("do_GET")
        rel = urlparse(self.path).path.lstrip("/") or "index.html"
        f = (PUBLIC / rel).resolve()
        if PUBLIC not in f.parents or not f.is_file():   # no path traversal outside public/
            f = PUBLIC / "index.html"
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(f.name)[0] or "text/plain") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Dashboard: http://127.0.0.1:{port}  (password: DASHBOARD_PASSWORD in .env)")
    ThreadingHTTPServer(("127.0.0.1", port), Dev).serve_forever()
