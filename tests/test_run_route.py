

def test_resume_args_takes_request(monkeypatch):
    """Regression: _resume_args was defined without a parameter, so 'Use my resume's roles' crashed with HTTP 500."""
    from routes import run
    import webapi
    monkeypatch.setattr(webapi, "store", lambda req: "store-for-" + req)
    monkeypatch.setattr(webapi, "resume_args", lambda st: ["--roles", st])
    assert run._resume_args("req") == ["--roles", "store-for-req"]
