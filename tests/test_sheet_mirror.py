"""Per-user tabs in the Google spreadsheet (multi-user mode). Google is mocked."""
from unittest.mock import MagicMock

import sheet_mirror
from integrations.google_sheets import HEADERS


def row(jid, status="Needs Review", title="Data Analyst"):
    r = [jid, "2026-10-09 08:00", title, "Acme"] + [""] * 11
    r[11] = status
    return r


def test_tab_titles_are_valid_and_unique_per_user():
    assert sheet_mirror.tab_title("asha@example.com") == "Jobs - asha@example.com"
    assert sheet_mirror.tab_title("a:b/c?d*e[f]g\\h@x.com") == "Jobs - a_b_c_d_e_f_g_h@x.com"
    assert len(sheet_mirror.tab_title("x" * 300 + "@x.com")) == 100


def test_plan_appends_new_updates_changed_never_deletes():
    sheet = [HEADERS, row("J1"), row("J2"), row("J-OLD")]
    appends, updates = sheet_mirror.plan(sheet, [row("J1"), row("J2", status="Verified"), row("J3")])
    assert [a[0] for a in appends] == ["J3"]
    assert updates == [{"range": "A3:O3", "values": [row("J2", status="Verified")]}]   # only the changed row
    assert sheet_mirror.plan(sheet, [row("J1")]) == ([], [])                             # J2/J-OLD are kept, not deleted


def test_sync_creates_tab_with_headers(monkeypatch):
    client = MagicMock()
    client.read.return_value = []
    monkeypatch.setattr(sheet_mirror, "_client", lambda title: client)
    out = sheet_mirror.sync_user("asha@example.com", [row("J1")])
    client.write_headers.assert_called_once()
    assert out == {"tab": "Jobs - asha@example.com", "added": 1, "updated": 0}
    assert client.apply.call_args.args[0][0][0] == "J1"


def test_create_tab_is_best_effort(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    assert sheet_mirror.create_tab("a@x.com") is False                                  # not configured: skip quietly
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    monkeypatch.setenv("GOOGLE_CREDENTIALS", "creds.json")
    monkeypatch.setattr(sheet_mirror, "_client", lambda t: (_ for _ in ()).throw(RuntimeError("google down")))
    assert sheet_mirror.create_tab("a@x.com") is False                                  # never raises
