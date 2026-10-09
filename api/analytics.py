"""GET /api/analytics?range=7|30|90|all (authenticated). Computed from stored data only."""
import os
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        import analytics
        import budget
        from api.jobs import build
        rng = (parse_qs(urlparse(self.path).query).get("range") or ["30"])[0]
        if rng not in analytics.RANGES:
            return webapi.send(self, 400, {"error": "range must be 7, 30, 90 or all"})
        try:
            st = webapi.store(self)
            b = st.bundle(("Jobs", "Details", "Verification", "Applications", "Runs", "History", "Archive"), ("_settings", "_profile"))
        except Exception as e:
            return webapi.send(self, 502, {"error": f"Could not read the Google Sheet ({type(e).__name__})"})
        scores = [j["match"]["overall"] for j in build(b)["jobs"] if j["match"]]
        used = budget.account(webapi.serpapi_key(self, st)).get("this_month_usage")
        return webapi.send(self, 200, analytics.compute(b["Jobs"], b["Archive"], b["Applications"], b["History"], b["Runs"],
                                                         scores, date.today(), rng, used))
