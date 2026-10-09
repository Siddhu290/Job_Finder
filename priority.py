"""Priority ranking and published-contact extraction, shared by the CLI and the web dashboard.
Works on sheet rows ({header: value}) so the dashboard can rank whatever is in the spreadsheet."""
import re
from datetime import date

import filters
from models import BUDGET_NOTE, CLOSED, REJECTED, VERIFIED

EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}\b")
_SKIP_EMAIL = re.compile(r"^(no-?reply|donotreply|do-not-reply|privacy|abuse|postmaster|webmaster|unsubscribe)@"
                         r"|@(example|sentry|wixpress|domain|email)\.|\.(png|jpe?g|gif|svg|webp)$", re.I)
_FRESHER = re.compile(r"fresher|entry|graduate|\b0(\.\d)?\b|\b0\s*-|months", re.I)


def published_emails(text: str, limit=3) -> list:
    """Emails written in the job text itself. Never guessed or constructed."""
    out = []
    for e in EMAIL_RX.findall(text or ""):
        e = e.lower().rstrip(".")
        if e not in out and not _SKIP_EMAIL.search(e):
            out.append(e)
    return out[:limit]


def score(row: dict, today: date | None = None, match_overall: int | None = None, preferred: bool = False) -> tuple:
    """(points, label, reasons). Label is High / Medium / Low, or Hidden for Rejected/Closed."""
    today = today or date.today()
    status = row.get("Verification Status", "")
    if status in (REJECTED, CLOSED):
        return -1, "Hidden", [status.lower()]
    wfh = "work from home" in row.get("Employment Type", "").lower()
    pts, why = 0, []

    def add(n, reason):
        nonlocal pts
        pts += n
        why.append(reason)

    if status == VERIFIED and row.get("Official Apply URL"):
        add(100, "verified apply link on company site")
    source = row.get("Source Platform", "")
    company_page = "board (" in source or "Company career page" in source
    if company_page:
        add(25, "listed on company's own career page")
    if row.get("Official Careers URL"):
        add(25, "company careers page found")
    elif not company_page:
        add(-10, "only seen on job portals")
    if wfh or filters.is_remote_job(row.get("Location", "")):
        why.append("work from home")
    exp = row.get("Experience Requirement", "")
    if _FRESHER.search(exp) and "not stated" not in exp.lower():
        add(15, "fresher-friendly")
    elif "1 year" in exp:
        add(-5, "asks for 1 year")
    posted = filters.parse_posted(row.get("Job Posted Date"))
    if posted and (today - posted).days <= 3:
        add(10, "posted in last 3 days")
    elif posted and (today - posted).days <= 7:
        add(5, "posted this week")
    notes = row.get("Notes", "")
    if published_emails(notes):
        add(5, "HR email published")
    if "HR on LinkedIn" in notes:
        add(5, "HR profile found")
    m = re.search(r"Resume match: (\d+)%", notes)
    pct = match_overall if match_overall is not None else int(m.group(1)) if m else None
    if pct is not None and pct >= 20:
        add(min(25, pct // 4), f"{pct}% resume match")
    if preferred:
        add(15, "preferred company")
    if notes.startswith(BUDGET_NOTE):
        add(-20, "not checked yet")
    label = "High" if pts >= 100 else "Medium" if pts >= 40 else "Low"
    return pts, label, why
