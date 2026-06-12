"""Pin the GDPR memory-delete endpoint (Task 3.2 / Component D).

Two contracts:

1. Authenticated DELETE returns 204 and forwards to
   `QueryMemoryService.delete_all_for_user(current_user.id)`.
2. Unauthenticated DELETE returns 401 (the bearer dependency rejects).

The memory service is patched — these tests pin the endpoint, not Milvus.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import UserRole
from app.db.session import get_db
from app.main import app


def _override_db():
    yield AsyncMock()


def _fake_user():
    return SimpleNamespace(
        id=uuid4(),
        email="user@test.local",
        name="test-user",
        role=UserRole.procurement_manager,
        is_active=True,
    )


@pytest.fixture(autouse=True)
def _reset_overrides():
    app.dependency_overrides[get_db] = _override_db
    yield
    app.dependency_overrides.clear()


def test_delete_my_memory_returns_204_and_forwards_user_id():
    user = _fake_user()
    app.dependency_overrides[get_current_user] = lambda: user

    mock_service = MagicMock()
    mock_service.delete_all_for_user = MagicMock(return_value=3)

    with patch(
        "app.services.query_memory.get_memory_service", return_value=mock_service
    ):
        client = TestClient(app)
        response = client.delete("/api/v1/users/me/memory")

    assert response.status_code == 204
    assert response.text == ""
    mock_service.delete_all_for_user.assert_called_once_with(str(user.id))


def test_delete_my_memory_requires_authentication():
    client = TestClient(app)
    response = client.delete("/api/v1/users/me/memory")
    assert response.status_code == 401


def test_delete_my_memory_503_when_memory_backend_fails():
    user = _fake_user()
    app.dependency_overrides[get_current_user] = lambda: user

    mock_service = MagicMock()
    mock_service.delete_all_for_user = MagicMock(
        side_effect=RuntimeError("milvus down")
    )

    with patch(
        "app.services.query_memory.get_memory_service", return_value=mock_service
    ):
        client = TestClient(app)
        response = client.delete("/api/v1/users/me/memory")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
