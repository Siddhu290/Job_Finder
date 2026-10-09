"""Multi-user mode: every user gets their own tab in the Google spreadsheet ("Jobs - <email>"), kept in sync
from Postgres (the source of truth).

- The tab is created when the account is created, and again on first sync if it was deleted.
- One-way: database -> tab. New jobs are appended, changed rows rewritten; nothing is ever deleted, and the
  tab is never read back into the app.
- Same 15 columns as the Jobs sheet. Values are written RAW (no formula injection).
- Optional: needs GOOGLE_SHEET_ID + service-account credentials. Users can switch it off in Settings
  ("sheet_mirror"). Anyone with access to the spreadsheet (the admin) can see every user's tab.
- Failures never break a search; they are reported."""
import logging
import os
import re

log = logging.getLogger(__name__)
MAX_TITLE = 100


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_SHEET_ID")) and bool(os.environ.get("GOOGLE_CREDENTIALS_JSON") or os.environ.get("GOOGLE_CREDENTIALS"))


def tab_title(email: str) -> str:
    """Sheet titles can't contain : \\ / ? * [ ] and are limited to 100 characters."""
    return ("Jobs - " + re.sub(r"[:\\/?*\[\]]", "_", email or "user"))[:MAX_TITLE]


def _client(title):
    from config import load_config
    from integrations.google_sheets import SheetsClient
    if os.environ.get("GOOGLE_CREDENTIALS_JSON") and not os.environ.get("GOOGLE_CREDENTIALS"):
        import webapi
        webapi.prepare_env()   # serverless: write the key from GOOGLE_CREDENTIALS_JSON to /tmp
    return SheetsClient(load_config(require_serpapi=False)).open(create_worksheet=True, title=title)


def create_tab(email: str) -> bool:
    """Make the user's tab with headers (called when the account is created). Best effort."""
    if not configured():
        return False
    try:
        from integrations.google_sheets import needs_headers
        c = _client(tab_title(email))
        if needs_headers(c.read()):
            c.write_headers()
        return True
    except Exception as e:  # noqa: BLE001 - account creation must not fail because of the sheet
        log.warning("could not create sheet tab for %s: %s", email, type(e).__name__)
        return False


def plan(sheet_values, rows):
    """(appends, updates) to make the tab contain every row (by Job ID). Never deletes."""
    from integrations.google_sheets import HEADERS
    width = len(HEADERS)
    end = chr(ord("A") + width - 1)
    existing = {r[0]: (n, (r + [""] * width)[:width]) for n, r in enumerate(sheet_values[1:], start=2) if r and r[0]}
    appends, updates = [], []
    for r in rows:
        r = [("" if v is None else str(v)) for v in (list(r) + [""] * width)[:width]]
        if r[0] not in existing:
            appends.append(r)
        elif existing[r[0]][1] != r:
            n = existing[r[0]][0]
            updates.append({"range": f"A{n}:{end}{n}", "values": [r]})
    return appends, updates


def sync_user(email: str, rows) -> dict:
    """rows: the user's jobs as sheet rows (no header). Returns counts; raises SheetsError on sheet problems."""
    from integrations.google_sheets import HEADERS, needs_headers
    c = _client(tab_title(email))
    values = c.read()
    if needs_headers(values):
        c.write_headers()
        values = [list(HEADERS)]
    appends, updates = plan(values, rows)
    c.apply(appends, updates)
    return {"tab": tab_title(email), "added": len(appends), "updated": len(updates)}
