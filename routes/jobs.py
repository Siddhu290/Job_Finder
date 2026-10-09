"""GET /api/jobs (authenticated): everything the dashboard shows, from ONE spreadsheet read.

Per job: ranking, verification breakdown + history, live resume match (active profile), application record,
recruiter contacts with provenance, and the Apply link (official only when Verified)."""
import json
import os
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapi  # noqa: E402

TABS = ("Jobs", "Details", "Verification", "Applications", "Runs", "Archive")
JSON_TABS = ("_settings", "_profile")


def _json(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _split(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def apply_link(row) -> dict:
    """Where the Apply button goes: the verified company apply page, else the best unverified link."""
    from http_client import is_job_board
    if row.get("Verification Status") == "Verified" and row.get("Official Apply URL"):
        return {"apply_link": row["Official Apply URL"], "apply_kind": "verified"}
    listing = row.get("Original Listing URL", "")
    if listing and not is_job_board(listing):
        return {"apply_link": listing, "apply_kind": "company"}
    return {"apply_link": listing or row.get("Official Careers URL", ""), "apply_kind": "portal" if listing else "careers"}


def contacts(row, detail) -> list:
    """Stored contacts with provenance, plus ones the earlier version wrote into Notes."""
    from discovery.hr_search import from_notes
    from priority import published_emails
    out = list(_json(detail.get("Contacts"), []))
    seen = {c.get("value") for c in out}
    for e in published_emails(row.get("Notes", "")):
        if e not in seen:
            out.append({"type": "listing", "value": e, "evidence": row.get("Original Listing URL", "")})
    for p in from_notes(row.get("Notes", "")):
        if p["url"] not in seen:
            out.append({"type": "profile", "name": p["name"], "role": p["headline"], "value": p["url"], "evidence": "Google results"})
    return out


def build(b: dict, today: date | None = None) -> dict:
    import applications
    import followups
    import matching
    import profiles
    import settings as settings_mod
    from priority import score
    today = today or date.today()
    s = settings_mod.clean(b.get("_settings"))
    pc = profiles.load(b.get("_profile"))
    prof = profiles.active(pc)
    search = settings_mod.search_profile(s, prof)
    details = {d.get("Job ID"): d for d in b.get("Details", [])}
    apps = {a.get("Job ID"): a for a in b.get("Applications", [])}
    ver = {}
    for v in b.get("Verification", []):
        ver.setdefault(v.get("Job ID"), []).append(v)
    prefer = [p.lower() for p in s["prefer"]]
    jobs = []
    for row in b.get("Jobs", []):
        jid = row.get("Job ID", "")
        d, app, vs = details.get(jid, {}), apps.get(jid, {}), ver.get(jid, [])
        analysis = {"required": _split(d.get("Required Skills")), "preferred": _split(d.get("Preferred Skills")),
                    "education": _split(d.get("Education"))}
        match = None
        if prof:
            match = matching.score({"title": row.get("Job Title", ""), "location": row.get("Location", ""),
                                    "employment": row.get("Employment Type", ""), "description": d.get("Description", ""),
                                    "experience_text": row.get("Experience Requirement", ""), "status": row.get("Verification Status", "")},
                                   analysis, prof, search)
        company = row.get("Company", "")
        preferred = any(p in company.lower() for p in prefer)
        pts, label, why = score(row, today, match["overall"] if match and match["eligible"] else None, preferred)
        last = vs[-1] if vs else {}
        jobs.append({
            "id": jid, "title": row.get("Job Title", ""), "company": company, "location": row.get("Location", ""),
            "experience": row.get("Experience Requirement", ""), "employment": row.get("Employment Type", ""),
            "source": row.get("Source Platform", ""), "listing": row.get("Original Listing URL", ""),
            "careers": row.get("Official Careers URL", ""), "apply": row.get("Official Apply URL", "") if row.get("Verification Status") == "Verified" else "",
            "status": row.get("Verification Status", ""), "posted": row.get("Job Posted Date", ""), "found": row.get("Date Found", ""),
            "checked": row.get("Last Checked", ""), "notes": row.get("Notes", ""), "score": pts, "priority": label, "why": why,
            "preferred": preferred, **apply_link(row),
            "verification": {"checks": _json(last.get("Checks"), {}), "reason": last.get("Reason", ""), "req_id": last.get("Req ID", ""),
                             "last_open_check": next((v.get("Last Open Check") for v in reversed(vs) if v.get("Last Open Check")), ""),
                             "history": [{"time": v.get("Timestamp", ""), "status": v.get("Status", ""), "reason": v.get("Reason", "")[:200]} for v in vs[-6:]],
                             "retry": last.get("Retry") == "yes"},
            "match": match, "closes": d.get("Closes", ""), "contacts": contacts(row, d),
            "skills": {"required": analysis["required"], "preferred": analysis["preferred"], "education": analysis["education"]},
            "responsibilities": matching.responsibilities(d.get("Description", "")),
            "application": {**{k: app.get(k, "") for k in applications.FIELDS}, "Stage": applications.stage_of(app, row.get("Verification Status", ""))},
            "linkedin": "https://www.linkedin.com/search/results/people/?origin=GLOBAL_SEARCH_HEADER&keywords="
                        + quote(f'"{company}" (HR OR recruiter OR "talent acquisition" OR "human resources")') if company else "",
        })
    jobs.sort(key=lambda j: -j["score"])
    rem = followups.reminders(b.get("Jobs", []), apps, details, today, s["follow_up_days"])
    runs = [{k: r.get(k, "") for k in ("Run ID", "Started", "Finished", "Trigger", "Profile", "Allowed Searches", "SerpApi Calls",
                                         "Discovered", "New Rows", "Verified", "Needs Review", "Errors", "Status")} for r in b.get("Runs", [])][-25:]
    return {"jobs": jobs, "updated": max((j["checked"] for j in jobs), default=""), "followups": rem, "runs": runs[::-1],
            "settings": s, "profile": {"name": prof["name"], "use_in_search": pc["use_in_search"]} if prof else None,
            "stages": applications.STAGES,
            "archive": [{"id": r.get("Job ID", ""), "title": r.get("Job Title", ""), "company": r.get("Company", ""),
                         "location": r.get("Location", ""), "found": r.get("Date Found", ""), "status": r.get("Verification Status", "")}
                        for r in b.get("Archive", [])][-300:][::-1]}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from storage import backend
        if not backend.is_pg() and not os.environ.get("DASHBOARD_PASSWORD"):
            return webapi.send(self, 500, {"error": "DASHBOARD_PASSWORD is not configured on the server"})
        if not webapi.authorized(self):
            return webapi.send(self, 401, {"error": "Not signed in"})
        try:
            st = webapi.store(self)
            body = build(st.bundle(TABS, JSON_TABS))
        except Exception as e:  # never echo credentials; the type is enough to diagnose
            return webapi.send(self, 502, {"error": f"Could not read your data ({type(e).__name__})"})
        import budget
        acct = budget.account(webapi.serpapi_key(self, st))
        body["budget"] = {"confirmed_left": acct.get("total_searches_left"), "confirmed_used": acct.get("this_month_usage"),
                          "per_run": int(os.environ.get("SERPAPI_MAX_CALLS", "30") or 30), "monthly_limit": budget.monthly_limit()}
        body["searches_left"] = acct.get("total_searches_left")
        u = webapi.user_of(self)
        body["user"] = {"email": u["email"], "name": u["name"] or u.get("username", ""), "role": u["role"], "multi_user": backend.is_pg(),
                        "shared_access": u.get("shared_access", "none"), "pending_requests": 0}
        if backend.is_pg() and u["role"] == "admin":
            import access
            body["user"]["pending_requests"] = access.pending_count(backend.conn())
        return webapi.send(self, 200, body)
