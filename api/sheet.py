"""/api/sheet (signed in, multi-user mode): the user's own tab in the Google spreadsheet.
GET                      -> {"configured", "enabled", "tab"}
POST {"action": "sync"}  -> copy my current jobs to my tab now"""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import sheet_mirror
        from storage import backend
        if not backend.is_pg():
            return webapi.send(self, 200, {"configured": False, "single_user": True})
        enabled = (webapi.store(self).get_json("_settings") or {}).get("sheet_mirror") is not False
        return webapi.send(self, 200, {"configured": sheet_mirror.configured(), "enabled": enabled,
                                       "tab": sheet_mirror.tab_title(webapi.user_of(self)["email"])})

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import sheet_mirror
        from integrations.google_sheets import SheetsError
        from storage import backend
        if not backend.is_pg() or webapi.read_json(self).get("action") != "sync":
            return webapi.send(self, 400, {"error": "Only available in multi-user mode: {\"action\": \"sync\"}"})
        if not sheet_mirror.configured():
            return webapi.send(self, 400, {"error": "The admin hasn't connected a Google spreadsheet (GOOGLE_SHEET_ID + credentials)"})
        if not webapi.rate_ok(self, "sheet", 5):
            return webapi.send(self, 429, {"error": "Too many syncs; wait a minute"})
        st = webapi.store(self)
        try:
            out = sheet_mirror.sync_user(webapi.user_of(self)["email"], st.c.read()[1:])
        except SheetsError as e:
            return webapi.send(self, 502, {"error": str(e)})
        webapi.audit(st, "sheet", "sync", detail=f"{out['added']} added, {out['updated']} updated")
        return webapi.send(self, 200, out)
