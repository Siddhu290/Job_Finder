

def test_resume_args_takes_request(monkeypatch):
    """Regression: _resume_args was defined without a parameter, so 'Use my resume's roles' crashed with HTTP 500."""
    from routes import run
    import webapi
    monkeypatch.setattr(webapi, "store", lambda req: "store-for-" + req)
    monkeypatch.setattr(webapi, "resume_args", lambda st: ["--roles", st])
    assert run._resume_args("req") == ["--roles", "store-for-req"]


def test_discover_runs_searches_in_parallel(monkeypatch):
    """5 searches of 0.3 s each must finish in well under 5 x 0.3 s, results kept in query order."""
    import time
    import main
    import filters
    from discovery import query_builder
    monkeypatch.setattr(main.ats_boards, "load_boards", lambda path: [])
    monkeypatch.setattr(query_builder, "build", lambda *a: [(f"q{i}", "India", False) for i in range(5)])
    monkeypatch.setattr(main, "google_jobs", lambda serp, q, where, wfh: (time.sleep(0.3), [q])[1])
    monkeypatch.setenv("RUN_TIME_LIMIT", "0")
    filters.set_profile(["Pune"], "any", [], [], None)
    t = time.monotonic()
    raw = main.discover(None, {"errors": []}, 10)
    assert raw == ["q0", "q1", "q2", "q3", "q4"]
    assert time.monotonic() - t < 1.0
