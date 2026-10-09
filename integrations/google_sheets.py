"""Google Sheets storage. Append-only for new jobs; for existing rows only Last Checked, Verification
Status and (when empty) the official URLs are touched. All writes are batched and RAW (no formula injection)."""
import json
import logging

import gspread
import requests
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.service_account import Credentials
from gspread.http_client import BackOffHTTPClient

from config import service_account_email
from http_client import retry
from models import BUDGET_NOTE, CLOSED, NEEDS_REVIEW, REJECTED, STATUSES, VERIFIED
from storage.deduplication import job_id, loose_key

log = logging.getLogger(__name__)

HEADERS = ["Job ID", "Date Found", "Job Title", "Company", "Location", "Experience Requirement", "Employment Type",
           "Source Platform", "Original Listing URL", "Official Careers URL", "Official Apply URL",
           "Verification Status", "Job Posted Date", "Last Checked", "Notes"]
C = {h: i for i, h in enumerate(HEADERS)}
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsError(Exception):
    pass


def _cell(row_num, header):
    return f"{chr(ord('A') + C[header])}{row_num}"


def needs_headers(values) -> bool:
    """True if the sheet is completely empty; raises if row 1 is anything but the expected headers."""
    if not values or not any(c.strip() for c in values[0]):
        if any(any(c.strip() for c in r) for r in values[1:]):
            raise SheetsError("Row 1 of the worksheet is empty but other rows contain data. Add the expected "
                              "headers to row 1 manually; nothing was written.")
        return True
    got = [c.strip() for c in values[0][:len(HEADERS)]]
    got += [""] * (len(HEADERS) - len(got))
    if got != HEADERS:
        diffs = [f"column {chr(65 + i)}: expected '{e}', found '{g}'" for i, (e, g) in enumerate(zip(HEADERS, got)) if e != g]
        raise SheetsError("Worksheet headers do not match; nothing was written.\n  " + "\n  ".join(diffs))
    return False


def job_row(job, now: str) -> list:
    apply_url = job.apply_url if job.status == VERIFIED else ""  # hard rule: only Verified rows carry an apply URL
    notes = "; ".join(job.notes)
    emp = job.employment_type
    if job.remote and "work from home" not in emp.lower():
        emp = f"{emp}, Work from home" if emp else "Work from home"
    return [job_id(job), now, job.title, job.company, job.location, job.experience or "Not stated",
            emp, job.source, job.listing_url, job.careers_url, apply_url, job.status,
            job.posted_date.isoformat() if job.posted_date else "", now, notes[:1500]]


def plan_sync(values, jobs, rechecks, now, archived=()):
    """Pure planning step. Returns (rows_to_append, cell_updates, duplicates_skipped).
    rechecks: {row_number: state} for previously Verified rows re-checked this run ('open'/'closed').
    archived: rows from the Archive tab; those jobs are never added again (no repeats after Clear)."""
    rows = values[1:] if values else []
    pad = lambda r: r + [""] * (len(HEADERS) - len(r))
    by_id, by_loose = {}, {}
    for i, r in enumerate(rows, start=2):
        r = pad(r)
        if r[C["Job ID"]]:
            by_id[r[C["Job ID"]]] = i
        by_loose.setdefault(loose_key(r[C["Company"]], r[C["Job Title"]], r[C["Location"]]), []).append(i)
    get = lambda n: pad(rows[n - 2])

    arch = [pad(list(r)) for r in archived]
    arch_ids = {r[C["Job ID"]] for r in arch if r[C["Job ID"]]}
    arch_loose = {loose_key(r[C["Company"]], r[C["Job Title"]], r[C["Location"]]) for r in arch}
    appends, updates, dupes, touched = [], [], 0, set()
    for job in jobs:
        jid = job_id(job)
        row = by_id.get(jid)
        if row is None:
            row = next((n for n in by_loose.get(loose_key(job.company, job.title, job.location), [])
                        if n > 0 and get(n)[C["Official Apply URL"]] in ("", job.apply_url)), None)
        if row == -1:            # already appended earlier in this batch
            dupes += 1
            continue
        if row is not None:
            dupes += 1
            touched.add(row)
            updates += _row_updates(row, get(row), job.status, job, now)
        elif jid in arch_ids or loose_key(job.company, job.title, job.location) in arch_loose:
            dupes += 1  # cleared earlier: don't bring it back
        elif job.status in (VERIFIED, NEEDS_REVIEW) and not (job.notes and job.notes[0] == BUDGET_NOTE):
            # budget-skipped jobs are left for a later run instead of filling the sheet with unchecked rows
            appends.append(job_row(job, now))
            by_id[jid] = -1
            by_loose.setdefault(loose_key(job.company, job.title, job.location), []).append(-1)

    for row, state in rechecks.items():
        if row in touched:
            continue
        if state == "closed":
            updates += _row_updates(row, get(row), CLOSED, None, now)
        elif state == "open":
            updates.append({"range": _cell(row, "Last Checked"), "values": [[now]]})
    return appends, updates, dupes


def _row_updates(row, cells, new, job, now):
    out = [{"range": _cell(row, "Last Checked"), "values": [[now]]}]
    old = cells[C["Verification Status"]].strip()
    if old and old not in STATUSES:
        return out  # user-defined status (e.g. "Applied"): never override
    set_ = lambda h, v: out.append({"range": _cell(row, h), "values": [[v]]})
    if new == VERIFIED:
        if old != VERIFIED:
            set_("Verification Status", VERIFIED)
        if not cells[C["Official Apply URL"]] and job.apply_url:
            set_("Official Apply URL", job.apply_url)
        if not cells[C["Official Careers URL"]] and job.careers_url:
            set_("Official Careers URL", job.careers_url)
    elif new in (CLOSED, REJECTED) and old != new:
        set_("Verification Status", new)
        if old == VERIFIED:
            set_("Official Apply URL", "")  # we wrote it; it is no longer a verified open vacancy
    elif new == NEEDS_REVIEW and not old:
        set_("Verification Status", NEEDS_REVIEW)
    # Notes are the user's, except our own "budget used up" placeholder, which is replaced once a real check ran
    if job and job.notes and job.notes[0] != BUDGET_NOTE and cells[C["Notes"]].startswith(BUDGET_NOTE):
        set_("Notes", "; ".join(job.notes)[:1500])
    # Needs Review never downgrades Verified/Closed/Rejected: a failed re-check is not evidence.
    return out


class SheetsClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.email = service_account_email(cfg.credentials_path)
        try:
            creds = Credentials.from_service_account_file(str(cfg.credentials_path), scopes=SCOPES)
        except (ValueError, OSError, KeyError):
            raise SheetsError(f"Could not load service-account credentials from {cfg.credentials_path}") from None
        self.gc = gspread.authorize(creds, http_client=BackOffHTTPClient)
        self.ws = None

    def _call(self, fn, *a, **kw):
        try:
            return retry(exceptions=(requests.ConnectionError, requests.Timeout, TransportError))(fn)(*a, **kw)
        except RefreshError:
            raise SheetsError("Google rejected the service-account credentials (key deleted, disabled or expired). "
                              "Create a new key and save it to GOOGLE_CREDENTIALS.") from None
        except PermissionError:
            raise SheetsError(self._share_hint("Permission denied")) from None
        except gspread.SpreadsheetNotFound:
            raise SheetsError(self._share_hint("Spreadsheet not found")) from None
        except gspread.exceptions.APIError as e:
            code = e.response.status_code
            if code == 403:
                raise SheetsError(self._share_hint("Permission denied (403)")) from None
            if code == 429:
                raise SheetsError("Google Sheets API quota exceeded even after backoff; try again later.") from None
            if code == 404:
                raise SheetsError(self._share_hint("Spreadsheet not found (404)")) from None
            raise SheetsError(f"Google Sheets API error {code}: {e.error.get('message', '')}") from None
        except (requests.ConnectionError, requests.Timeout, TransportError) as e:
            raise SheetsError(f"Network error talking to Google Sheets: {type(e).__name__}") from None

    def _share_hint(self, what):
        return (f"{what} for spreadsheet {self.cfg.sheet_id}. Open the sheet, click Share, and add "
                f"{self.email or 'the service-account client_email'} as Editor. Also confirm the Google Sheets API "
                "is enabled for the service account's Cloud project and GOOGLE_SHEET_ID is correct.")

    def open(self, create_worksheet=False, title=None):
        """Open the Jobs worksheet, or another tab (e.g. a user's own tab) when title is given."""
        title = title or self.cfg.worksheet
        sh = self._call(self.gc.open_by_key, self.cfg.sheet_id)
        try:
            self.ws = self._call(sh.worksheet, title)
        except gspread.WorksheetNotFound:
            if not create_worksheet:
                raise SheetsError(f"Worksheet '{title}' does not exist in the spreadsheet") from None
            self.ws = self._call(sh.add_worksheet, title=title, rows=1000, cols=len(HEADERS))
            log.info("created worksheet '%s'", title)
        return self

    def read(self) -> list:
        return self._call(self.ws.get_all_values)

    ARCHIVE_TAB = "Archive"

    def _tab(self, title, create_rows=100):
        sh = self.ws.spreadsheet
        try:
            return self._call(sh.worksheet, title)
        except gspread.WorksheetNotFound:
            return self._call(sh.add_worksheet, title=title, rows=create_rows, cols=len(HEADERS))

    def read_archive(self) -> list:
        try:
            ws = self._call(self.ws.spreadsheet.worksheet, self.ARCHIVE_TAB)
        except gspread.WorksheetNotFound:
            return []
        return self._call(ws.get_all_values)[1:]

    def restore(self, job_ids) -> int:
        """Move rows back from the Archive tab to Jobs (copied first, then removed from Archive)."""
        ids = set(job_ids)
        try:
            tab = self._call(self.ws.spreadsheet.worksheet, self.ARCHIVE_TAB)
        except gspread.WorksheetNotFound:
            return 0
        values = self._call(tab.get_all_values)
        pad = lambda r: r + [""] * (len(HEADERS) - len(r))
        rows = [n for n, r in enumerate(values[1:], start=2) if r and r[C["Job ID"]] in ids]
        if not rows:
            return 0
        self._call(self.ws.append_rows, [pad(values[n - 1])[:len(HEADERS)] for n in rows], value_input_option="RAW",
                   insert_data_option="OVERWRITE", table_range="A1")
        reqs = [{"deleteDimension": {"range": {"sheetId": tab.id, "dimension": "ROWS", "startIndex": n - 1, "endIndex": n}}}
                for n in sorted(rows, reverse=True)]
        self._call(self.ws.spreadsheet.batch_update, {"requests": reqs})
        return len(rows)

    def set_status(self, job_id: str, status: str) -> bool:
        """Dashboard actions (Applied / Not interested / undo). Only the Verification Status cell changes."""
        ids = self._call(self.ws.col_values, C["Job ID"] + 1)
        if job_id not in ids[1:]:
            return False
        row = ids.index(job_id, 1) + 1
        self._call(self.ws.update, range_name=_cell(row, "Verification Status"), values=[[status]], value_input_option="RAW")
        return True

    def archive(self, which) -> int:
        """Move rows where which(row) is true to the Archive tab (copied first, then removed from Jobs)."""
        values = self.read()
        if needs_headers(values):
            return 0
        pad = lambda r: r + [""] * (len(HEADERS) - len(r))
        rows = [n for n, r in enumerate(values[1:], start=2) if any(c.strip() for c in r) and which(pad(r))]
        if not rows:
            return 0
        tab = self._tab(self.ARCHIVE_TAB, create_rows=max(100, len(rows) + 10))
        if needs_headers(self._call(tab.get_all_values)):
            self._call(tab.update, range_name="A1", values=[HEADERS], value_input_option="RAW")
        self._call(tab.append_rows, [pad(values[n - 1]) for n in rows], value_input_option="RAW",
                   insert_data_option="OVERWRITE", table_range="A1")
        reqs = [{"deleteDimension": {"range": {"sheetId": self.ws.id, "dimension": "ROWS", "startIndex": n - 1, "endIndex": n}}}
                for n in sorted(rows, reverse=True)]  # bottom-up so indexes stay valid
        self._call(self.ws.spreadsheet.batch_update, {"requests": reqs})
        return len(rows)

    # Employer/HR look-up cache kept in a "_cache" tab, for hosts without persistent disk (Vercel).
    CACHE_TAB = "_cache"

    def read_cache(self) -> dict:
        sh = self.ws.spreadsheet
        try:
            ws = self._call(sh.worksheet, self.CACHE_TAB)
        except gspread.WorksheetNotFound:
            return {}
        out = {}
        for row in self._call(ws.get_all_values):
            if len(row) >= 2 and row[0]:
                try:
                    out[row[0]] = json.loads(row[1])
                except ValueError:
                    pass
        return out

    def write_cache(self, data: dict):
        sh = self.ws.spreadsheet
        try:
            ws = self._call(sh.worksheet, self.CACHE_TAB)
        except gspread.WorksheetNotFound:
            ws = self._call(sh.add_worksheet, title=self.CACHE_TAB, rows=max(100, len(data) + 10), cols=2)
        rows = [[k, json.dumps(v)] for k, v in sorted(data.items())]
        self._call(ws.clear)  # our own cache tab only; never the Jobs sheet
        if rows:
            self._call(ws.update, range_name="A1", values=rows, value_input_option="RAW")

    def write_headers(self):
        self._call(self.ws.update, range_name="A1", values=[HEADERS], value_input_option="RAW")

    def apply(self, appends, updates):
        if updates:
            self._call(self.ws.batch_update, updates, value_input_option="RAW")
        if appends:
            self._call(self.ws.append_rows, appends, value_input_option="RAW",
                       insert_data_option="OVERWRITE", table_range="A1")  # INSERT_ROWS copies the header formatting
