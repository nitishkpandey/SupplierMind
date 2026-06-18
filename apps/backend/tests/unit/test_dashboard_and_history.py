from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import UserRole
from app.db.session import get_db
from app.main import app


def _fake_user(role: UserRole = UserRole.procurement_manager):
    return SimpleNamespace(
        id=uuid4(),
        email=f"{role.value}@test.local",
        name=role.value,
        role=role,
        is_active=True,
    )


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def test_supplier_stats_returns_db_count_and_index_health():
    user = _fake_user()
    app.dependency_overrides[get_current_user] = lambda: user

    fake_repo = MagicMock()
    fake_repo.count_active = AsyncMock(return_value=10136)
    fake_vector_store = MagicMock()
    fake_vector_store.count.return_value = 10127

    async def session_override():
        yield AsyncMock()

    app.dependency_overrides[get_db] = session_override

    with patch("app.api.v1.suppliers.SupplierRepository", return_value=fake_repo), \
         patch("app.api.v1.suppliers.get_vector_store", return_value=fake_vector_store):
        response = TestClient(app).get("/api/v1/suppliers/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_active": 10136,
        "indexed_suppliers": 10127,
        "index_status": "out_of_sync",
    }


def test_supplier_stats_reports_unavailable_index():
    user = _fake_user()
    app.dependency_overrides[get_current_user] = lambda: user

    fake_repo = MagicMock()
    fake_repo.count_active = AsyncMock(return_value=118)

    async def session_override():
        yield AsyncMock()

    app.dependency_overrides[get_db] = session_override

    with patch("app.api.v1.suppliers.SupplierRepository", return_value=fake_repo), \
         patch("app.api.v1.suppliers.get_vector_store", side_effect=RuntimeError("not ready")):
        response = TestClient(app).get("/api/v1/suppliers/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_active": 118,
        "indexed_suppliers": None,
        "index_status": "unavailable",
    }


def test_clear_history_deletes_only_current_users_query_artifacts():
    user = _fake_user()
    app.dependency_overrides[get_current_user] = lambda: user

    fake_result = SimpleNamespace(rowcount=12)
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(return_value=fake_result)
    fake_session.commit = AsyncMock()

    async def session_override():
        yield fake_session

    app.dependency_overrides[get_db] = session_override

    response = TestClient(app).delete("/api/v1/queries/history")

    assert response.status_code == 200
    assert response.json() == {"deleted": 12}
    assert fake_session.execute.await_count == 4
    fake_session.commit.assert_awaited_once()
