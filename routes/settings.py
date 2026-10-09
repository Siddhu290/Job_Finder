"""/api/settings (authenticated). GET -> current settings; POST {settings} -> validated and saved.
Scheduled runs use these settings too."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import settings
        from integrations.google_sheets import SheetsError
        try:
            return webapi.send(self, 200, settings.clean(webapi.store(self).get_json("_settings")))
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import settings
        from integrations.google_sheets import SheetsError
        try:
            st = webapi.store(self)
            s = settings.clean(webapi.read_json(self))
            st.put_json("_settings", s)
            webapi.audit(st, "settings", "update")
            return webapi.send(self, 200, s)
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})
