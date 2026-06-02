"""
Resource-level RBAC regression tests (Task 2.3).

Three scenarios pin the three classes of authorization in the codebase:

1. Read-by-id of a user-scoped resource: a non-owner non-admin gets 404
   (NOT 403 — 404 avoids leaking the existence of the resource).
2. List endpoints filter by current_user.id at the SQL layer, so a
   user's list never contains another user's records.
3. Admin-only mutations (approve, reject) reject non-admins with 403 —
   here 403 is fine because the endpoint's existence is not sensitive,
   only the action is restricted.

These tests mock the dependencies rather than spinning up a real DB —
the goal is to pin authorization behavior, not exercise the persistence
layer.
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
    app.dependency_overrides[get_db] = _override_db
    yield
    app.dependency_overrides.clear()


# ── 1. Cross-user resource fetch returns 404, not 403 ─────────────────
def test_user_b_cannot_fetch_user_a_query_returns_404():
    user_a = _fake_user(UserRole.procurement_manager)
    user_b = _fake_user(UserRole.procurement_manager)

    fake_query = SimpleNamespace(
        id=uuid4(),
        user_id=user_a.id,   # owned by A
        results=[],
    )

    app.dependency_overrides[get_current_user] = lambda: user_b

    mock_repo = MagicMock()
    mock_repo.get_with_results = AsyncMock(return_value=fake_query)

    with patch("app.api.v1.queries.QueryRepository", return_value=mock_repo):
        client = TestClient(app)
        response = client.get(f"/api/v1/queries/{fake_query.id}")

    assert response.status_code == 404, (
        f"Expected 404 (existence-hiding), got {response.status_code}. "
        f"A 403 here would leak that the resource exists."
    )
    assert response.json()["detail"] == "Resource not found"


def test_owner_can_fetch_own_query():
    user_a = _fake_user(UserRole.procurement_manager)
    fake_query = SimpleNamespace(
        id=uuid4(),
        user_id=user_a.id,
        raw_query="test",
        status=SimpleNamespace(value="completed"),
        detected_language="en",
        parsed_constraints=None,
        execution_time_ms=100,
        error_message=None,
        created_at=SimpleNamespace(isoformat=lambda: "2026-06-02T00:00:00"),
        completed_at=None,
        results=[],
    )

    app.dependency_overrides[get_current_user] = lambda: user_a

    mock_repo = MagicMock()
    mock_repo.get_with_results = AsyncMock(return_value=fake_query)

    with patch("app.api.v1.queries.QueryRepository", return_value=mock_repo):
        client = TestClient(app)
        response = client.get(f"/api/v1/queries/{fake_query.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(fake_query.id)


def test_admin_can_fetch_other_users_query():
    user_a = _fake_user(UserRole.procurement_manager)
    admin = _fake_user(UserRole.admin)

    fake_query = SimpleNamespace(
        id=uuid4(),
        user_id=user_a.id,   # owned by A, admin requesting
        raw_query="test",
        status=SimpleNamespace(value="completed"),
        detected_language="en",
        parsed_constraints=None,
        execution_time_ms=100,
        error_message=None,
        created_at=SimpleNamespace(isoformat=lambda: "2026-06-02T00:00:00"),
        completed_at=None,
        results=[],
    )

    app.dependency_overrides[get_current_user] = lambda: admin

    mock_repo = MagicMock()
    mock_repo.get_with_results = AsyncMock(return_value=fake_query)

    with patch("app.api.v1.queries.QueryRepository", return_value=mock_repo):
        client = TestClient(app)
        response = client.get(f"/api/v1/queries/{fake_query.id}")

    assert response.status_code == 200, "admin bypass should permit cross-user fetch"


# ── 2. List endpoints scope by current_user.id at SQL layer ───────────
def test_list_queries_filters_by_current_user_id():
    """
    GET /queries must call get_user_queries with current_user.id. A bug
    that hardcoded a different user_id would leak across accounts.
    """
    user_b = _fake_user(UserRole.procurement_manager)

    captured = {}

    async def fake_get_user_queries(user_id, offset=0, limit=20):
        captured["user_id"] = user_id
        return []

    app.dependency_overrides[get_current_user] = lambda: user_b

    mock_repo = MagicMock()
    mock_repo.get_user_queries = AsyncMock(side_effect=fake_get_user_queries)

    fake_session = MagicMock()
    fake_count_result = MagicMock()
    fake_count_result.scalar_one.return_value = 0
    fake_session.execute = AsyncMock(return_value=fake_count_result)

    async def session_override():
        yield fake_session

    app.dependency_overrides[get_db] = session_override

    # list_queries re-imports QueryRepository inside the handler, so patch
    # the source module — patching the queries module binding is a no-op.
    with patch(
        "app.db.repositories.query_repo.QueryRepository", return_value=mock_repo
    ):
        client = TestClient(app)
        response = client.get("/api/v1/queries")

    assert response.status_code == 200
    assert captured.get("user_id") == user_b.id, (
        f"list_queries must scope by current user id {user_b.id}, "
        f"got {captured.get('user_id')!r}"
    )


# ── 3. Admin-only mutations reject non-admins with 403 ────────────────
def test_procurement_manager_cannot_approve_supplier_returns_403():
    """
    approve is admin-only because Tier-1 promotion is an org-wide event.
    A procurement_manager has Tier-2 (personal saves), not Tier-1 promotion.
    """
    manager = _fake_user(UserRole.procurement_manager)

    app.dependency_overrides[get_current_user] = lambda: manager

    client = TestClient(app)
    response = client.post(f"/api/v1/suppliers/{uuid4()}/approve")

    assert response.status_code == 403, (
        f"procurement_manager must be denied approve; got {response.status_code}"
    )


def test_admin_can_approve_supplier_returns_204():
    admin = _fake_user(UserRole.admin)
    app.dependency_overrides[get_current_user] = lambda: admin

    mock_result = MagicMock()
    mock_result.rowcount = 1
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=mock_result)
    fake_session.commit = AsyncMock()

    async def session_override():
        yield fake_session

    app.dependency_overrides[get_db] = session_override

    client = TestClient(app)
    response = client.post(f"/api/v1/suppliers/{uuid4()}/approve")

    assert response.status_code == 204, (
        f"admin should succeed; got {response.status_code} {response.text}"
    )


def test_procurement_manager_cannot_reject_supplier_returns_403():
    """Symmetry: reject has the same admin-only governance rationale."""
    manager = _fake_user(UserRole.procurement_manager)
    app.dependency_overrides[get_current_user] = lambda: manager

    client = TestClient(app)
    response = client.post(f"/api/v1/suppliers/{uuid4()}/reject")

    assert response.status_code == 403
