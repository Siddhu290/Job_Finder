from datetime import date
from unittest.mock import MagicMock

import pytest

import analytics
import applications
import followups
import settings
from storage.store import Store
from tests.test_store_budget import FakeClient

TODAY = date(2026, 10, 9)


@pytest.fixture
def st():
    return Store(FakeClient())


def stage(st, jid="J1"):
    return {a["Job ID"]: a for a in st.read("Applications")["Applications"]}[jid]


def test_stage_changes_dates_history_and_idempotency(st):
    applications.apply_change(st, "J1", {"Stage": "Saved"}, "a1", TODAY)
    out = applications.apply_change(st, "J1", {"Stage": "Applied", "Notes": "via careers page"}, "a2", TODAY)
    assert out["changed"]["Applied Date"] == "2026-10-09" and stage(st)["Saved Date"] == "2026-10-09"
    assert applications.apply_change(st, "J1", {"Stage": "Applied"}, "a2", TODAY) == {"ok": True, "duplicate": True}   # retry/double click
    h = applications.history(st, "J1")
    assert [(x["Field"], x["Old"], x["New"]) for x in h][:2] == [("Stage", "", "Saved"), ("Saved Date", "", "2026-10-09")]


def test_undo_reverts_whole_last_action(st):
    applications.apply_change(st, "J1", {"Stage": "Applied"}, "a1", TODAY)
    applications.apply_change(st, "J1", {"Stage": "Technical Interview", "Interview Date": "2026-10-15"}, "a2", TODAY)
    applications.undo(st, "J1", "u1")
    rec = stage(st)
    assert rec["Stage"] == "Applied" and rec["Interview Date"] == ""
    assert applications.undo(st, "J9", "u2") == {"ok": False, "error": "Nothing to undo"}


@pytest.mark.parametrize("fields,msg", [({"Stage": "Hired!"}, "Unknown stage"), ({"Applied Date": "09/10/2026"}, "YYYY-MM-DD"),
                                        ({"Applied Date": "2026-02-30"}, "day is out of range"), ({"Password": "x"}, "Unknown field")])
def test_invalid_input(st, fields, msg):
    with pytest.raises(ValueError, match=msg):
        applications.apply_change(st, "J1", fields, "a", TODAY)


def test_text_fields_truncated(st):
    applications.apply_change(st, "J1", {"Notes": "x" * 5000}, "a", TODAY)
    assert len(stage(st)["Notes"]) == 2000


# ---------- follow-ups ----------
def jobs(*rows):
    return [{"Job ID": j, "Job Title": "Data Analyst", "Company": c, "Verification Status": s} for j, c, s in rows]


def test_followup_buckets_and_no_duplicates():
    js = jobs(("J1", "Acme", "Verified"), ("J2", "Beta", "Needs Review"), ("J3", "Gamma", "Verified"), ("J4", "Delta", "Verified"))
    apps = {"J1": {"Stage": "Applied", "Applied Date": "2026-10-01"},                    # 5 days -> due 10-06: overdue
            "J2": {"Stage": "Technical Interview", "Applied Date": "2026-10-08", "Interview Date": "2026-10-09"},
            "J4": {"Stage": "Rejected", "Applied Date": "2026-09-01"}}                    # terminal: nothing
    details = {"J3": {"Closes": "2026-10-11"}}                                             # verified, not applied, closes soon
    r = followups.reminders(js, apps, details, TODAY, follow_up_days=5)
    assert [(x["job_id"], x["kind"]) for x in r["overdue"]] == [("J1", "follow-up")]
    assert ("J2", "interview") in [(x["job_id"], x["kind"]) for x in r["today"]]
    assert ("J3", "closing") in [(x["job_id"], x["kind"]) for x in r["upcoming"]]
    assert all(x["job_id"] != "J4" for b in r.values() for x in b)
    apps["J1"]["Follow-up Done"] = "2026-10-07"                                            # marked done: suppressed
    assert not followups.reminders(js, apps, details, TODAY)["overdue"]


# ---------- settings ----------
def test_settings_validation():
    s = settings.clean({"locations": ["Pune", "<script>", "Navi Mumbai"], "mode": "hack", "max_age_days": 5,
                        "employment_types": ["internship", "bogus"], "exclude": ["Sales", "x" * 99], "follow_up_days": 99})
    assert s["locations"] == ["Pune", "Navi Mumbai"] and s["mode"] == "any" and s["max_age_days"] == 7
    assert s["employment_types"] == ["internship"] and s["exclude"] == ["Sales"] and s["follow_up_days"] == 30
    args = settings.run_args(s)
    assert args[:2] == ["--locations", "Pune;Navi Mumbai"] and "--employment" in args and "--exclude" in args


# ---------- analytics ----------
def test_analytics_from_stored_data_only():
    js = [{"Job ID": "J1", "Job Title": "Data Analyst", "Location": "Pune", "Date Found": "2026-10-08 08:00", "Verification Status": "Verified",
           "Source Platform": "Company career page + Google Jobs (Naukri)", "Employment Type": "Full-time", "Job Posted Date": "2026-10-07"},
          {"Job ID": "J2", "Job Title": "Junior Data Engineer", "Location": "Remote", "Date Found": "2026-10-09 08:00",
           "Verification Status": "Needs Review", "Employment Type": "Work from home"},
          {"Job ID": "J3", "Job Title": "Data Analyst", "Location": "Pune", "Date Found": "2026-06-01 08:00", "Verification Status": "Closed"}]
    history = [{"Job ID": "J1", "Field": "Stage", "New": "Applied", "Timestamp": "2026-10-08 10:00"},
               {"Job ID": "J1", "Field": "Stage", "New": "Technical Interview", "Timestamp": "2026-10-09 10:00"}]
    runs = [{"Started": "2026-10-09 08:00", "SerpApi Calls": "12"}]
    a = analytics.compute(js, [], [{"Job ID": "J1", "Stage": "Technical Interview", "Applied Date": "2026-10-08"}], history, runs,
                          [80, 30], TODAY, "30", confirmed_used=None)
    assert a["total_discovered"] == 2 and a["by_status"]["Verified"] == 1                     # J3 is outside 30 days
    assert a["by_role"] == {"Data Analyst": 1, "Data Engineer": 1} and a["by_location"]["Work from home"] == 1
    assert a["applications"] == 1 and a["interviews"] == 1 and a["application_to_interview_pct"] == 100
    assert a["interview_to_offer_pct"] == 0 and a["new_since_last_search"] == 1
    assert a["searches"]["serpapi_used_estimated"] == 12 and a["searches"]["serpapi_used_confirmed_this_month"] is None
    empty = analytics.compute([], [], [], [], [], [], TODAY, "7")
    assert empty["application_to_interview_pct"] is None and empty["match_distribution"] is None   # n/a, not 0%
    assert analytics.compute(js, [], [], [], [], [], TODAY, "all")["total_discovered"] == 3


def test_application_api_archive_restore(monkeypatch):
    import webapi
    from routes import application
    from tests.test_vercel import post
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    mem = Store(FakeClient())
    mem.c.archive, mem.c.restore = MagicMock(return_value=2), MagicMock(return_value=1)
    monkeypatch.setattr(webapi, "store", lambda *a: mem)
    key = {"X-Dashboard-Key": "pw"}
    assert post(application.handler, {}, {"action": "undo", "job_id": "J1"})[0] == 401
    assert post(application.handler, key, {"action": "set", "job_id": "J1", "fields": {"Stage": "Saved"}})[1]["changed"]["Stage"] == "Saved"
    assert post(application.handler, key, {"action": "set", "job_id": "J1", "fields": {"Stage": "Nope"}})[0] == 400
    assert post(application.handler, key, {"action": "archive", "job_ids": ["J1", "J2"]}) == (200, {"ok": True, "count": 2})
    which = mem.c.archive.call_args.args[0]
    assert which(["J1"]) and not which(["J9"])
    assert post(application.handler, key, {"action": "restore", "job_ids": ["J1"]}) == (200, {"ok": True, "count": 1})
    assert len(post(application.handler, key, {"action": "history", "job_id": "J1"})[1]["history"]) >= 1
