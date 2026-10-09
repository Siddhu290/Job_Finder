import json
import logging

import pytest
import requests

import config
import http_client
from discovery import serpapi_search
from discovery.serpapi_search import SerpApi, SerpApiAuthError, SerpApiError, BudgetExhausted


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)  # no real .env is read
    for k in ("SERPAPI_KEY", "GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_missing_credentials_and_keys(env, monkeypatch):
    with pytest.raises(config.ConfigError) as e:
        config.load_config()
    msg = str(e.value)
    assert "SERPAPI_KEY is not set" in msg and "GOOGLE_SHEET_ID" in msg and "credentials file not found" in msg


def test_invalid_credentials_file_is_reported_without_contents(env, monkeypatch):
    (env / "credentials.json").write_text(json.dumps({"type": "authorized_user", "private_key": "SECRETKEYDATA"}))
    monkeypatch.setenv("SERPAPI_KEY", "k" * 20)
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    with pytest.raises(config.ConfigError) as e:
        config.load_config()
    assert "not a service-account key" in str(e.value) and "SECRETKEYDATA" not in str(e.value)


def test_valid_config(env, monkeypatch):
    (env / "creds.json").write_text(json.dumps({"type": "service_account", "client_email": "a@b", "private_key": "x"}))
    monkeypatch.setenv("GOOGLE_CREDENTIALS", "creds.json")
    monkeypatch.setenv("SERPAPI_KEY", "k" * 20)
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    cfg = config.load_config()
    assert cfg.credentials_path == env / "creds.json" and cfg.max_age_days == 7


def test_dry_run_needs_no_google_credentials(env, monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "k" * 20)
    assert config.load_config(require_sheets=False).serpapi_key


# ---------- retries / timeouts ----------
class R:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data or {}

    def json(self):
        return self._d


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(http_client.time, "sleep", lambda s: None)


def test_timeouts_are_retried_with_backoff(monkeypatch, no_sleep):
    delays, calls = [], []
    monkeypatch.setattr(http_client.time, "sleep", delays.append)

    def flaky(method, url, **kw):
        calls.append(kw["timeout"])
        if len(calls) < 3:
            raise requests.Timeout("slow")
        return R(200)
    monkeypatch.setattr(http_client._session, "request", flaky)
    assert http_client.request("GET", "https://api.example.org/x").status_code == 200
    assert len(calls) == 3 and all(t == http_client.TIMEOUT for t in calls)
    assert [d for d in delays if d >= 2] == [2.0, 4.0]  # exponential


def test_retries_give_up(monkeypatch, no_sleep):
    monkeypatch.setattr(http_client._session, "request", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    with pytest.raises(requests.ConnectionError):
        http_client.request("GET", "https://api.example.org/y")


def test_429_and_5xx_are_retried(monkeypatch, no_sleep):
    seq = [R(429), R(503), R(200)]
    monkeypatch.setattr(http_client._session, "request", lambda *a, **k: seq.pop(0))
    assert http_client.request("GET", "https://api.example.org/z").status_code == 200


# ---------- SerpApi ----------
def test_serpapi_auth_error_and_budget(monkeypatch):
    monkeypatch.setattr(serpapi_search.http_client, "request", lambda *a, **k: R(401, {"error": "Invalid API key"}))
    with pytest.raises(SerpApiAuthError):
        SerpApi("secret-key-123456", 5).search(q="x")
    s = SerpApi("secret-key-123456", 0)
    with pytest.raises(BudgetExhausted):
        s.search(q="x")


def test_serpapi_timeout_becomes_error_without_leaking_key(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("https://serpapi.com/search.json?api_key=secret-key-123456&q=x timed out")
    monkeypatch.setattr(serpapi_search.http_client, "request", boom)
    with pytest.raises(SerpApiError) as e:
        SerpApi("secret-key-123456", 5).search(q="x")
    assert "secret-key-123456" not in str(e.value)


def test_serpapi_no_results_is_empty(monkeypatch):
    monkeypatch.setattr(serpapi_search.http_client, "request",
                        lambda *a, **k: R(200, {"error": "Google hasn't returned any results for this query."}))
    assert SerpApi("secret-key-123456", 5).search(q="x") == {}


def test_google_jobs_normalisation(monkeypatch):
    data = {"jobs_results": [{"title": "Data Analyst", "company_name": "Acme", "location": "Pune, Maharashtra, India",
                              "via": "via LinkedIn", "description": "Freshers",
                              "detected_extensions": {"posted_at": "2 days ago", "schedule_type": "Full-time"},
                              "apply_options": [{"title": "LinkedIn", "link": "https://in.linkedin.com/jobs/view/1"},
                                                {"title": "Acme", "link": "https://boards.greenhouse.io/acme/jobs/1"}]}]}
    s = SerpApi("secret-key-123456", 5)
    monkeypatch.setattr(s, "search", lambda **p: data)
    [job] = serpapi_search.google_jobs(s, "q")
    assert job.listing_url == "https://boards.greenhouse.io/acme/jobs/1"  # company page preferred over portal
    assert job.source == "Company career page + Google Jobs (LinkedIn)" and len(job.links) == 2 and job.posted_date is not None


# ---------- secrets never logged ----------
def test_log_redaction(caplog):
    http_client.register_secret("supersecretvalue99")
    logger = logging.getLogger("t")
    handler = logging.Handler()
    records = []
    handler.emit = records.append
    handler.addFilter(http_client.RedactingFilter())
    logger.addHandler(handler)
    logger.warning("GET https://serpapi.com/search?api_key=abc123&q=x and %s", "supersecretvalue99")
    logger.warning("-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----")
    text = " ".join(r.getMessage() for r in records)
    assert "abc123" not in text and "supersecretvalue99" not in text and "MIIE" not in text
