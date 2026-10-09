import os
import socket

import pytest


def test_tests_cannot_reach_the_internet_or_real_settings():
    with pytest.raises(RuntimeError, match="network access is not allowed"):
        socket.create_connection(("sheets.googleapis.com", 443), timeout=1)
    for k in ("DATABASE_URL", "GOOGLE_SHEET_ID", "SERPAPI_KEY", "SESSION_SECRET"):
        assert k not in os.environ
    import dev_server  # noqa: F401  (used to load the real .env at import time)
    assert "DATABASE_URL" not in os.environ
