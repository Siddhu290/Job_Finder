"""/api/run: one job-finder run.

GET  - Vercel Cron (08:00 and 20:00 IST, see vercel.json), authorised by "Authorization: Bearer $CRON_SECRET".
       Uses the saved Settings and, if switched on, the active resume profile.
POST - dashboard (signed in). Body: {"locations": [...], "mode": "any|wfh|onsite", "use_resume": bool,
       "max_age_days": 1|3|7|14|30, "preview": bool}. With "preview": true nothing is searched; the plan
       (queries + budget) is returned instead."""
import contextlib
import io
import os
import re
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402

_LOC = re.compile(r"^[A-Za-z][A-Za-z .\-]{0,39}$")
_ROLE = re.compile(r"^[A-Za-z][A-Za-z0-9 +#./&()-]{1,59}$")


def run_job(argv):
    webapi.prepare_env()
    import main  # after env is prepared
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main.main(argv)
    summary = out.getvalue()
    print(summary)  # also lands in the Vercel function logs
    return code, summary


def _resume_args():
    try:
        return webapi.resume_args(webapi.store(self))
    except Exception:  # no profile / sheet problem: fall back to the default roles; the run reports sheet errors itself
        return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not webapi.cron_ok(self):
            return webapi.send(self, 401, {"error": "unauthorized"})
        from storage import backend
        if not backend.is_pg():
            code, summary = run_job(["--trigger", "cron", "--use-saved-settings"])
            return webapi.send(self, 200 if code in (0, 2) else 500, {"exit_code": code, "summary": summary[-4000:]})
        return webapi.send(self, 200, {"runs": cron_all_users()})

    def do_POST(self):
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        body = webapi.read_json(self)
        preview = bool(body.get("preview"))
        locations = [str(l).strip() for l in body.get("locations") or [] if str(l).strip()][:5]
        mode = body.get("mode", "any")
        age = body.get("max_age_days")
        roles = [str(r).strip() for r in body.get("roles") or [] if str(r).strip()][:6]
        if not all(_ROLE.match(r) for r in roles):
            return webapi.send(self, 400, {"error": "Job roles must be plain titles, e.g. Data Analyst (max 6)"})
        if mode not in ("any", "wfh", "onsite") or not all(_LOC.match(l) for l in locations) or age not in (None, 1, 3, 7, 14, 30):
            return webapi.send(self, 400, {"error": "Locations must be plain place names (max 5); mode any/wfh/onsite"})
        if not locations and mode != "wfh":
            return webapi.send(self, 400, {"error": "Add at least one location, or choose Work from home"})
        if not preview and not webapi.rate_ok(self, "run", 3, window=600):   # only valid, real searches count
            return webapi.send(self, 429, {"error": "At most 3 searches per 10 minutes"})
        argv = ["--mode", mode] + (["--locations", ";".join(locations)] if locations else [])
        if age:
            argv += ["--max-age-days", str(age)]
        if body.get("use_resume"):
            argv += _resume_args(self)          # resume roles + skills (+ experience)
        elif roles and roles != ["Data Analyst", "Data Engineer"]:
            argv += ["--roles", ";".join(roles)]
        uid = webapi.user_of(self)["id"]
        if uid:
            argv += ["--user-id", uid]
        argv = (["--plan"] if preview else ["--trigger", "dashboard"]) + argv
        code, summary = run_job(argv)
        return webapi.send(self, 200 if code in (0, 2) else 500, {"exit_code": code, "summary": summary[-4000:], "preview": preview})
