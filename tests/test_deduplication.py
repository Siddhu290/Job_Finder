from models import NEEDS_REVIEW, VERIFIED, Job
from storage.deduplication import dedupe, job_id, job_key


def test_same_vacancy_from_different_boards_is_merged():
    a = Job("Data Analyst", "Acme Analytics Pvt. Ltd.", "Bangalore, Karnataka", source="Google Jobs (LinkedIn)",
            links=["https://linkedin.com/jobs/1"])
    b = Job("Data Analyst (Remote)", "ACME ANALYTICS", "Bengaluru, India", source="Google Jobs (Naukri)",
            links=["https://naukri.com/x"])
    unique, merged = dedupe([a, b])
    assert len(unique) == 1 and merged == 1
    assert set(unique[0].links) == {"https://linkedin.com/jobs/1", "https://naukri.com/x"}
    assert "LinkedIn" in unique[0].source and "Naukri" in unique[0].source


def test_different_locations_are_different_jobs():
    unique, _ = dedupe([Job("Data Analyst", "Acme", "Pune"), Job("Data Analyst", "Acme", "Chennai")])
    assert len(unique) == 2


def test_requisition_id_key_wins_and_verified_copy_is_kept():
    gj = Job("Data Analyst", "Acme", "Pune", req_id="4001", status=NEEDS_REVIEW, source="Google Jobs")
    ats = Job("Data Analyst - Pune", "Acme Inc", "Pune, India", req_id="4001", status=VERIFIED, source="Greenhouse")
    unique, merged = dedupe([gj, ats], key=job_key)
    assert merged == 1 and unique[0].status == VERIFIED
    assert job_id(gj) == job_id(ats)


def test_without_req_id_key_includes_official_url():
    a = Job("Data Engineer", "Acme", "Pune", apply_url="https://jobs.lever.co/acme/1")
    b = Job("Data Engineer", "Acme", "Pune", apply_url="https://jobs.lever.co/acme/2")
    assert job_key(a) != job_key(b)


def test_board_watchlist_filters_postings(monkeypatch, tmp_path):
    from discovery import ats_boards
    from models import Posting
    monkeypatch.setattr(ats_boards.ats_clients, "list_board", lambda ref, term: [
        Posting("lever", "https://jobs.lever.co/acme/1", "Data Analyst", "Pune, India", description="0-1 years experience"),
        Posting("lever", "https://jobs.lever.co/acme/2", "Senior Data Engineer", "Pune, India"),
        Posting("lever", "https://jobs.lever.co/acme/3", "Data Analyst", "London, UK")])
    [job] = ats_boards.board_jobs({"company": "Acme", "ats": "lever", "board": "acme"}, {"errors": []})
    assert job.links == ["https://jobs.lever.co/acme/1"] and job.company == "Acme"
    (tmp_path / "b.json").write_text("not json")
    import pytest
    with pytest.raises(ValueError):
        ats_boards.load_boards(tmp_path / "b.json")



def test_queries_follow_profile():
    from discovery.query_builder import build
    q = build(["Pune", "Mumbai"], "any")
    assert q[0] == ("Data Analyst fresher Pune", "India", False) and q[1][0] == "Data Analyst fresher Mumbai"
    assert q[2] == ("Data Analyst fresher work from home", "India", True)
    assert all(w for _, _, w in build(["Pune"], "wfh")) and not any(w for _, _, w in build(["Pune"], "onsite"))


def test_queries_use_resume_roles():
    from discovery.query_builder import build
    q = build(["Pune"], "any", ["Business Analyst"])
    assert q[0] == ("Business Analyst fresher Pune", "India", False)
    assert ("Business Analyst fresher work from home", "India", True) in q
