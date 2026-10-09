"""Test-suite guard: tests must never touch real services.

1. The real .env is never loaded (python-dotenv is neutralised before any project module imports it).
2. Credentials/settings for real services are removed from the environment for every test.
3. Any network connection that isn't local (unix socket / localhost) raises immediately."""
import os
import socket

import dotenv
import pytest

dotenv.load_dotenv = lambda *a, **k: False          # before config/dev_server/manage import it

REAL_SERVICE_ENV = ("DATABASE_URL", "DATABASE_URL_UNPOOLED", "STORAGE_BACKEND", "GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS",
                    "GOOGLE_CREDENTIALS_JSON", "SERPAPI_KEY", "LLM_API_KEY", "GROQ_API_KEY", "SESSION_SECRET",
                    "SECRETS_KEY", "DASHBOARD_PASSWORD", "INVITE_CODE", "ALLOW_SIGNUP", "CRON_SECRET")
for _k in REAL_SERVICE_ENV:                          # also scrub anything inherited from the shell
    os.environ.pop(_k, None)

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _local(sock, address):
    if sock.family == getattr(socket, "AF_UNIX", None):
        return True
    host = address[0] if isinstance(address, tuple) else address
    return host in ("127.0.0.1", "localhost", "::1")


def _guarded(real):
    def connect(self, address):
        if not _local(self, address):
            raise RuntimeError(f"network access is not allowed in tests: {address!r}")
        return real(self, address)
    return connect


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for k in REAL_SERVICE_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(socket.socket, "connect", _guarded(_real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded(_real_connect_ex))
    yield
