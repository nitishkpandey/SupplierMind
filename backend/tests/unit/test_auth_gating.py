"""
Regression guard for the /dev-login environment gate.

The dev-login endpoint must be reachable in development and return 404 in
any other environment. 404 (not 403) is deliberate: a 403 confirms that the
endpoint exists; 404 says "no such endpoint here" and leaks no information.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import UserRole
from app.db.session import get_db
from app.main import app

DEV_LOGIN_URL = "/api/v1/auth/dev-login"


def _override_db():
    yield AsyncMock()


@pytest.fixture(autouse=True)
def _mock_db_dependency():
    app.dependency_overrides[get_db] = _override_db
    yield
    app.dependency_overrides.pop(get_db, None)


def test_dev_login_returns_404_in_production(monkeypatch):
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module.settings, "APP_ENV", "production")

    client = TestClient(app)
    response = client.get(DEV_LOGIN_URL, follow_redirects=False)

    assert response.status_code == 404
    assert response.json()["detail"] == "Endpoint not available in this environment"


def test_dev_login_works_in_development(monkeypatch):
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module.settings, "APP_ENV", "development")

    fake_user = SimpleNamespace(
        id=uuid4(),
        email="dev@suppliermind.local",
        role=UserRole.procurement_manager,
    )

    with patch.object(
        auth_module, "_get_or_create_user", new=AsyncMock(return_value=fake_user)
    ), patch.object(
        auth_module, "create_access_token", return_value="fake-access-token"
    ), patch.object(
        auth_module, "create_refresh_token", return_value="fake-refresh-token"
    ):
        client = TestClient(app)
        response = client.get(DEV_LOGIN_URL, follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert "access_token=fake-access-token" in location
    assert "refresh_token=fake-refresh-token" in location
    assert f"role={UserRole.procurement_manager.value}" in location
