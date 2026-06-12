"""Shared test fixtures.

The API rate-limit middleware keeps a process-global sliding window keyed
by JWT sub or client IP. Under TestClient every unauthenticated request
shares the identity "ip:testclient", so a full suite run can cross the
20-requests/minute ceiling and later endpoint tests start failing with
429s that have nothing to do with the code under test. Reset the window
store before every test so each test sees a fresh limiter.
"""

import pytest

from app.middleware import rate_limit


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._windows.clear()
    yield
    rate_limit._windows.clear()
