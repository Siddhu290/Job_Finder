"""/api/serpapi (signed in). The user's own SerpApi key, encrypted at rest; never returned to the browser.
GET                         -> {"source": "own"|"server"|"none", "hint": "…a1b2", "searches_left", "used_this_month"}
POST {"key": "..."}         -> test it with SerpApi's free account endpoint, then save (replaces any previous key)
POST {"action": "remove"}   -> forget the saved key"""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


def status(h, st):
    import budget
    import user_secrets
    from storage import backend
    try:
        key, source = user_secrets.key_for_run(st, backend.is_pg(), webapi.user_of(h)["role"] == "admin")
    except user_secrets.SecretsError as e:
        return {"source": "error", "error": str(e), "hint": user_secrets.hint(st)}
    acct = budget.account(key) if key else {}
    return {"source": source, "hint": user_secrets.hint(st) if source == "own" else "",
            "searches_left": acct.get("total_searches_left"), "used_this_month": acct.get("this_month_usage"),
            "plan": acct.get("plan_name") or acct.get("plan_id")}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        return webapi.send(self, 200, status(self, webapi.store(self)))

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        if not webapi.rate_ok(self, "serpapi", 10):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        import budget
        import user_secrets
        body, st = webapi.read_json(self), webapi.store(self)
        try:
            if body.get("action") == "remove":
                user_secrets.remove_serpapi_key(st)
                webapi.audit(st, "serpapi", "key removed")
            elif isinstance(body.get("key"), str):
                key = body["key"].strip()
                if not budget.account(key):
                    return webapi.send(self, 400, {"error": "SerpApi did not accept this key (check it on serpapi.com/manage-api-key)"})
                user_secrets.save_serpapi_key(st, key)
                webapi.audit(st, "serpapi", "key saved", detail="…" + key[-4:])
            else:
                return webapi.send(self, 400, {"error": "Send a key or {\"action\": \"remove\"}"})
        except user_secrets.SecretsError as e:
            return webapi.send(self, 400, {"error": str(e)})
        return webapi.send(self, 200, status(self, st))
