import json
from datetime import date
from unittest.mock import MagicMock

import gspread
import pytest
from google.auth.exceptions import RefreshError

from config import Config
from integrations import google_sheets as gs
from integrations.google_sheets import C, HEADERS, SheetsError, needs_headers, plan_sync
from models import CLOSED, NEEDS_REVIEW, REJECTED, VERIFIED, Job
from storage.deduplication import job_id

NOW = "2026-10-09 08:00"


def row(**kw):
    r = [""] * len(HEADERS)
    for k, v in kw.items():
        r[C[k.replace("_", " ")]] = v
    return r


def vjob(status=VERIFIED, **kw):
    d = dict(title="Data Analyst", company="Acme", location="Pune, India", req_id="4001",
             apply_url="https://boards.greenhouse.io/acme/jobs/4001", careers_url="https://acme.com/careers",
             posted_date=date(2026, 10, 8), experience="0-1 years", source="Google Jobs (LinkedIn)",
             listing_url="https://linkedin.com/jobs/1")
    d.update(kw)
    j = Job(**d)
    j.status = status
    j.notes = ["reason"]
    return j


# ---------- headers ----------
def test_headers_valid_and_empty_sheet():
    assert needs_headers([]) is True
    assert needs_headers([[""] * 15]) is True
    assert needs_headers([HEADERS + ["My extra column"]]) is False


def test_header_mismatch_refuses_to_write():
    bad = HEADERS.copy()
    bad[10], bad[11] = bad[11], bad[10]
    with pytest.raises(SheetsError, match="column K"):
        needs_headers([bad])


def test_data_without_header_row_refuses_to_write():
    with pytest.raises(SheetsError):
        needs_headers([[""] * 15, ["user", "data"]])


# ---------- planning ----------
def test_new_jobs_appended_and_apply_url_only_for_verified():
    appends, updates, dupes = plan_sync([HEADERS], [vjob(), vjob(NEEDS_REVIEW, req_id="5", title="Data Engineer")], {}, NOW)
    assert len(appends) == 2 and not updates and dupes == 0
    assert appends[0][C["Official Apply URL"]].startswith("https://")
    assert appends[1][C["Official Apply URL"]] == ""
    assert appends[1][C["Verification Status"]] == NEEDS_REVIEW


def test_rejected_and_closed_are_not_appended_as_new_rows():
    appends, _, _ = plan_sync([HEADERS], [vjob(REJECTED), vjob(CLOSED, req_id="9")], {}, NOW)
    assert appends == []


def test_existing_job_is_not_duplicated_and_only_status_cells_change():
    j = vjob()
    existing = row(Job_ID=job_id(j), Job_Title="Data Analyst", Company="Acme", Location="Pune, India",
                   Verification_Status=NEEDS_REVIEW, Notes="my own notes")
    appends, updates, dupes = plan_sync([HEADERS, existing], [j], {}, NOW)
    assert appends == [] and dupes == 1
    ranges = {u["range"]: u["values"][0][0] for u in updates}
    assert ranges == {"N2": NOW, "L2": VERIFIED, "K2": j.apply_url, "J2": j.careers_url}  # empty URL cells filled
    # nothing touches Notes (O) or user columns
    existing[C["Official Careers URL"]] = "user-set"
    ranges = {u["range"] for u in plan_sync([HEADERS, existing], [j], {}, NOW)[1]}
    assert "J2" not in ranges and "O2" not in ranges


def test_same_vacancy_found_on_another_board_matches_existing_row():
    existing = row(Job_ID="JOLDID", Job_Title="Data Analyst", Company="Acme Pvt Ltd", Location="Pune",
                   Verification_Status=NEEDS_REVIEW)
    j = vjob(NEEDS_REVIEW, req_id="", apply_url="", source="Google Jobs (Naukri)")
    appends, updates, dupes = plan_sync([HEADERS, existing], [j], {}, NOW)
    assert appends == [] and dupes == 1


def test_closed_clears_apply_url_we_wrote():
    j = vjob(CLOSED)
    existing = row(Job_ID=job_id(j), Company="Acme", Job_Title="Data Analyst", Location="Pune, India",
                   Verification_Status=VERIFIED, Official_Apply_URL=j.apply_url)
    ranges = {u["range"]: u["values"][0][0] for u in plan_sync([HEADERS, existing], [j], {}, NOW)[1]}
    assert ranges["L2"] == CLOSED and ranges["K2"] == ""


def test_needs_review_never_downgrades_verified_and_custom_status_untouched():
    j = vjob(NEEDS_REVIEW)
    verified = row(Job_ID=job_id(j), Verification_Status=VERIFIED, Official_Apply_URL="https://x")
    assert [u["range"] for u in plan_sync([HEADERS, verified], [j], {}, NOW)[1]] == ["N2"]
    custom = row(Job_ID=job_id(j), Verification_Status="Applied")
    assert [u["range"] for u in plan_sync([HEADERS, custom], [vjob(CLOSED)], {}, NOW)[1]] == ["N2"]


def test_recheck_results_update_previous_rows():
    rows = [HEADERS, row(Job_ID="JA", Verification_Status=VERIFIED, Official_Apply_URL="https://a"),
            row(Job_ID="JB", Verification_Status=VERIFIED, Official_Apply_URL="https://b")]
    _, updates, _ = plan_sync(rows, [], {2: "closed", 3: "open"}, NOW)
    got = {u["range"]: u["values"][0][0] for u in updates}
    assert got == {"N2": NOW, "L2": CLOSED, "K2": "", "N3": NOW}


def test_duplicate_within_one_batch_appended_once():
    appends, _, dupes = plan_sync([HEADERS], [vjob(), vjob()], {}, NOW)
    assert len(appends) == 1 and dupes == 1


# ---------- client error handling (gspread mocked) ----------
def make_client(tmp_path, monkeypatch):
    cred = tmp_path / "credentials.json"
    cred.write_text(json.dumps({"type": "service_account", "client_email": "bot@proj.iam.gserviceaccount.com",
                                "private_key": "x"}))
    cfg = Config("", "SHEET", "Jobs", cred, "Asia/Kolkata", 7, 30, tmp_path, tmp_path)
    monkeypatch.setattr(gs.Credentials, "from_service_account_file", lambda *a, **k: object())
    gc = MagicMock()
    monkeypatch.setattr(gs.gspread, "authorize", lambda *a, **k: gc)
    monkeypatch.setattr("http_client.time.sleep", lambda s: None)
    return gs.SheetsClient(cfg), gc


def api_error(code):
    resp = MagicMock(status_code=code)
    resp.json.return_value = {"error": {"code": code, "message": "nope", "status": "X"}}
    return gspread.exceptions.APIError(resp)


def test_permission_error_explains_sharing(tmp_path, monkeypatch):
    client, gc = make_client(tmp_path, monkeypatch)
    gc.open_by_key.side_effect = PermissionError()
    with pytest.raises(SheetsError, match="bot@proj.iam.gserviceaccount.com"):
        client.open()


@pytest.mark.parametrize("code,msg", [(403, "Share"), (429, "quota"), (404, "not found"), (400, "error 400")])
def test_api_errors_are_translated(tmp_path, monkeypatch, code, msg):
    client, gc = make_client(tmp_path, monkeypatch)
    gc.open_by_key.side_effect = api_error(code)
    with pytest.raises(SheetsError, match=msg):
        client.open()


def test_revoked_credentials(tmp_path, monkeypatch):
    client, gc = make_client(tmp_path, monkeypatch)
    gc.open_by_key.side_effect = RefreshError("invalid_grant")
    with pytest.raises(SheetsError, match="rejected the service-account credentials"):
        client.open()


def test_network_errors_retried_then_reported(tmp_path, monkeypatch):
    import requests
    client, gc = make_client(tmp_path, monkeypatch)
    gc.open_by_key.side_effect = requests.ConnectionError("down")
    with pytest.raises(SheetsError, match="Network error"):
        client.open()
    assert gc.open_by_key.call_count == 4


def test_missing_worksheet_created_only_when_allowed(tmp_path, monkeypatch):
    client, gc = make_client(tmp_path, monkeypatch)
    sh = gc.open_by_key.return_value
    sh.worksheet.side_effect = gspread.WorksheetNotFound("Jobs")
    with pytest.raises(SheetsError, match="does not exist"):
        client.open(create_worksheet=False)
    client.open(create_worksheet=True)
    sh.add_worksheet.assert_called_once()


def test_writes_are_batched_and_raw(tmp_path, monkeypatch):
    client, gc = make_client(tmp_path, monkeypatch)
    client.open()
    ws = client.ws
    client.apply([["=HYPERLINK(evil)"] + [""] * 14, ["b"] * 15], [{"range": "N2", "values": [["x"]]}])
    ws.batch_update.assert_called_once()
    assert ws.batch_update.call_args.kwargs["value_input_option"] == "RAW"
    ws.append_rows.assert_called_once()
    assert ws.append_rows.call_args.kwargs["value_input_option"] == "RAW"
    assert ws.append_rows.call_args.kwargs["insert_data_option"] == "OVERWRITE"
    ws.delete_rows.assert_not_called()
    ws.clear.assert_not_called()


def test_budget_skipped_jobs_are_not_appended_and_placeholder_note_replaced():
    from models import BUDGET_NOTE
    j = vjob(NEEDS_REVIEW)
    j.notes = [BUDGET_NOTE]
    assert plan_sync([HEADERS], [j], {}, NOW)[0] == []
    existing = row(Job_ID=job_id(j), Verification_Status=NEEDS_REVIEW, Notes=BUDGET_NOTE + " (raise SERPAPI_MAX_CALLS)")
    j.notes = ["official website not established: x"]
    got = {u["range"]: u["values"][0][0] for u in plan_sync([HEADERS, existing], [j], {}, NOW)[1]}
    assert got["O2"].startswith("official website not established")
    existing[C["Notes"]] = "my note"
    assert "O2" not in {u["range"] for u in plan_sync([HEADERS, existing], [j], {}, NOW)[1]}


def test_archived_jobs_never_come_back():
    j = vjob(NEEDS_REVIEW)
    archived = [row(Job_ID=job_id(j), Company="Acme", Job_Title="Data Analyst", Location="Pune, India")]
    appends, updates, dupes = plan_sync([HEADERS], [j], {}, NOW, archived)
    assert appends == [] and updates == [] and dupes == 1
    other = vjob(NEEDS_REVIEW, req_id="", company="Acme Pvt Ltd", apply_url="")  # same vacancy via another board
    assert plan_sync([HEADERS], [other], {}, NOW, archived)[0] == []


def test_applied_status_is_kept_on_rediscovery():
    j = vjob()
    applied = row(Job_ID=job_id(j), Verification_Status="Applied", Official_Apply_URL=j.apply_url)
    appends, updates, _ = plan_sync([HEADERS, applied], [j], {}, NOW)
    assert appends == [] and [u["range"] for u in updates] == ["N2"]


def test_set_status_and_archive(tmp_path, monkeypatch):
    client, gc = make_client(tmp_path, monkeypatch)
    client.open()
    ws = client.ws
    ws.col_values.return_value = ["Job ID", "J1", "J2"]
    assert client.set_status("J2", "Applied")
    assert ws.update.call_args.kwargs["range_name"] == "L3"
    assert not client.set_status("J9", "Applied")

    ws.get_all_values.return_value = [HEADERS, row(Job_ID="J1", Date_Found="2026-10-08 08:00"),
                                      row(Job_ID="J2", Date_Found="2026-10-09 08:00"),
                                      row(Job_ID="J3", Date_Found="2026-10-08 20:00")]
    ws.id = 0
    tab = MagicMock()
    tab.get_all_values.return_value = []
    ws.spreadsheet.worksheet.return_value = tab
    n = client.archive(lambda r: r[C["Date Found"]].startswith("2026-10-08"))
    assert n == 2
    moved = tab.append_rows.call_args.args[0]
    assert [r[0] for r in moved] == ["J1", "J3"]
    reqs = ws.spreadsheet.batch_update.call_args.args[0]["requests"]
    assert [q["deleteDimension"]["range"]["startIndex"] for q in reqs] == [3, 1]   # rows 4 and 2, bottom-up
    tab.append_rows.assert_called_once()  # copied to Archive before anything was removed
