"""
Regression guards for the OAuth flow's two security properties:

1. Login-CSRF: /authorize issues a random `state` (URL param + HttpOnly
   cookie) and the callback rejects any request whose state does not
   match the cookie — before touching the provider or the database.
2. Token delivery: on success the callback puts tokens in the URL
   *fragment* (#access_token=...), never the query string, so they stay
   out of server logs and Referer headers.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import UserRole
from app.db.session import get_db
from app.main import app

AUTHORIZE_URL = "/api/v1/auth/google/authorize"
CALLBACK_URL = "/api/v1/auth/google/callback"


def _override_db():
    yield AsyncMock()


@pytest.fixture(autouse=True)
def _mock_db_dependency(monkeypatch):
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module.settings, "GOOGLE_CLIENT_ID", "test-client-id")
    app.dependency_overrides[get_db] = _override_db
    yield
    app.dependency_overrides.pop(get_db, None)


def test_authorize_sets_state_param_and_cookie():
    client = TestClient(app)
    response = client.get(AUTHORIZE_URL, follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    state_values = parse_qs(urlsplit(location).query).get("state")
    assert state_values and state_values[0], "authorize URL must carry a state param"
    assert response.cookies.get("oauth_state") == state_values[0]
    assert "httponly" in response.headers["set-cookie"].lower()


def test_callback_rejects_state_mismatch_without_token_exchange():
    from app.api.v1 import auth as auth_module

    client = TestClient(app)
    client.cookies.set("oauth_state", "expected-state")
    with patch.object(auth_module.httpx, "AsyncClient") as mock_client:
        response = client.get(
            CALLBACK_URL,
            params={"code": "attacker-code", "state": "wrong-state"},
            follow_redirects=False,
        )

    assert response.status_code == 307
    assert "error=invalid_state" in response.headers["location"]
    mock_client.assert_not_called()


def test_callback_success_delivers_tokens_in_fragment_not_query():
    from app.api.v1 import auth as auth_module

    fake_user = SimpleNamespace(
        id=uuid4(),
        email="user@example.com",
        name="User",
        role=UserRole.procurement_manager,
    )

    # httpx.AsyncClient() used as async context manager
    http = AsyncMock()
    http.post.return_value = MagicMock(
        status_code=200, json=lambda: {"access_token": "google-token"}
    )
    http.get.return_value = MagicMock(
        json=lambda: {"sub": "g-123", "email": "user@example.com", "name": "User"}
    )
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=http)
    client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(
        auth_module.httpx, "AsyncClient", return_value=client_cm
    ), patch.object(
        auth_module, "_get_or_create_user", new=AsyncMock(return_value=fake_user)
    ), patch.object(
        auth_module, "create_access_token", return_value="jwt-token"
    ), patch.object(
        auth_module, "create_refresh_token", return_value="refresh-token"
    ):
        client = TestClient(app)
        client.cookies.set("oauth_state", "good-state")
        response = client.get(
            CALLBACK_URL,
            params={"code": "valid-code", "state": "good-state"},
            follow_redirects=False,
        )

    assert response.status_code == 307
    parts = urlsplit(response.headers["location"])
    assert "access_token" not in parts.query
    assert "refresh_token" not in parts.query
    assert "access_token=jwt-token" in parts.fragment
    assert "refresh_token=refresh-token" in parts.fragment
