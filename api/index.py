"""The only Vercel function (Hobby allows 12 per deployment). vercel.json rewrites /api/<name> to
/api/index?__route=<name>; this dispatches to routes/<name>.py. Only names in ROUTES can be loaded."""
import importlib
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402

ROUTES = {"jobs", "run", "action", "application", "resume", "tailor", "settings", "analytics",
          "login", "register", "account", "serpapi", "sheet", "health", "keys", "resumes", "ats", "access"}


def route_name(path: str) -> str:
    u = urlparse(path or "")
    return (parse_qs(u.query).get("__route") or [""])[0] or u.path.removeprefix("/api/").strip("/").split("/")[0]


class handler(BaseHTTPRequestHandler):
    def _dispatch(self, method):
        name = route_name(self.path)
        if name not in ROUTES:
            return webapi.send(self, 404, {"error": "Not found"})
        fn = getattr(importlib.import_module(f"routes.{name}").handler, method, None)
        if fn is None:
            return webapi.send(self, 405, {"error": "Method not allowed"})
        try:
            return fn(self)
        except Exception as e:  # show the cause on the dashboard instead of Vercel's bare HTML 500
            import traceback
            traceback.print_exc()
            return webapi.send(self, 500, {"error": f"Server error in {name}: {type(e).__name__}"})

    def do_GET(self):
        return self._dispatch("do_GET")

    def do_POST(self):
        return self._dispatch("do_POST")
