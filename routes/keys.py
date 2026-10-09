"""/api/keys (signed in). The user's own SerpApi and Groq keys: encrypted at rest, never returned in full.
GET                                         -> {"serpapi": status, "groq": status}
POST {"kind": "serpapi"|"groq", "key": ...} -> test with the provider (free call), then save / replace
POST {"kind": ..., "action": "remove"}       -> forget it"""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402


def status(h, st, kind):
    import budget
    import user_secrets
    from storage import backend
    try:
        key, source = user_secrets.key_for(st, kind, backend.is_pg(), webapi.user_of(h)["role"] == "admin")
    except user_secrets.SecretsError as e:
        return {"source": "error", "error": str(e)}
    out = {"source": source, "hint": user_secrets.key_hint(st, kind) if source == "own" else ""}
    if kind == "serpapi" and key:
        acct = budget.account(key)
        out.update(searches_left=acct.get("total_searches_left"), used_this_month=acct.get("this_month_usage"))
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        st = webapi.store(self)
        return webapi.send(self, 200, {k: status(self, st, k) for k in ("serpapi", "groq")})

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        if not webapi.rate_ok(self, "keys", 10):
            return webapi.send(self, 429, {"error": "Too many requests; wait a minute"})
        import budget
        import llm
        import user_secrets
        body, st = webapi.read_json(self), webapi.store(self)
        kind = body.get("kind")
        if kind not in user_secrets.KINDS:
            return webapi.send(self, 400, {"error": "kind must be serpapi or groq"})
        try:
            if body.get("action") == "remove":
                user_secrets.remove_key(st, kind)
                webapi.audit(st, "keys", f"{kind} key removed")
            elif isinstance(body.get("key"), str):
                key = body["key"].strip()
                if not user_secrets.KINDS[kind]["format"].match(key):
                    return webapi.send(self, 400, {"error": user_secrets.KINDS[kind]["bad"]})
                ok = bool(budget.account(key)) if kind == "serpapi" else llm.test_key(key)
                if not ok:
                    return webapi.send(self, 400, {"error": f"{'SerpApi' if kind == 'serpapi' else 'Groq'} did not accept this key"})
                user_secrets.save_key(st, kind, key)
                webapi.audit(st, "keys", f"{kind} key saved", detail="…" + key[-4:])
            else:
                return webapi.send(self, 400, {"error": "Send a key, or action=remove"})
        except user_secrets.SecretsError as e:
            return webapi.send(self, 400, {"error": str(e)})
        return webapi.send(self, 200, status(self, st, kind))
