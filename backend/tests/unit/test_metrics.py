"""
Tests for the admin metrics endpoint (Task 2.5).

Two scenarios pin the contract:
  - admin caller gets 200 plus the documented response shape
  - non-admin caller gets 403

A passthrough math test verifies the endpoint correctly carries SQL-aggregated
values into the response (the percentile math itself is Postgres' PERCENTILE_CONT
and is trusted here; we own the formatting boundary).

Bounds on window_hours (1..168) are pinned via FastAPI's built-in Query
validation, so out-of-range values return 422.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import UserRole
from app.db.session import get_db
from app.main import app


METRICS_URL = "/api/v1/admin/metrics"


def _fake_user(role: UserRole):
    return SimpleNamespace(
        id=uuid4(),
        email=f"{role.value}@test.local",
        name=role.value,
        role=role,
        is_active=True,
    )


def _fake_session_for(metrics_rows):
    """
    Returns a MagicMock session whose .execute() returns the prepared
    results in the order the endpoint consumes them:
      1. latency rows (.all())
      2. summary row (.one())
      3. throttle row (.one())
      4. sanctions row (.one())
      5. error rows  (.all())
    """
    latency_result = MagicMock()
    latency_result.all.return_value = metrics_rows["latency"]
    summary_result = MagicMock()
    summary_result.one.return_value = metrics_rows["summary"]
    throttle_result = MagicMock()
    throttle_result.one.return_value = metrics_rows["throttle"]
    sanctions_result = MagicMock()
    sanctions_result.one.return_value = metrics_rows["sanctions"]
    errors_result = MagicMock()
    errors_result.all.return_value = metrics_rows["errors"]

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            latency_result,
            summary_result,
            throttle_result,
            sanctions_result,
            errors_result,
        ]
    )
    session.commit = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def _default_rows():
    return {
        "latency": [
            SimpleNamespace(
                agent_name="parser", p50=1820.0, p95=3240.0, mean=2105.0, cnt=87
            ),
            SimpleNamespace(
                agent_name="compliance",
                p50=15200.0,
                p95=62100.0,
                mean=21800.0,
                cnt=87,
            ),
            SimpleNamespace(
                agent_name="rate_limiter",
                p50=250.0,
                p95=900.0,
                mean=410.0,
                cnt=42,
            ),
        ],
        "summary": SimpleNamespace(
            queries=87, agent_invocations=412, human_decisions=6, error_queries=3
        ),
        "throttle": SimpleNamespace(pacing=42, rate_429=1),
        "sanctions": SimpleNamespace(cnt=9),
        "errors": [
            SimpleNamespace(
                timestamp=datetime(2026, 6, 2, 19, 45, 12, tzinfo=timezone.utc),
                agent_name="external_discovery",
                action="no_web_results",
                query_id=uuid4(),
                reasoning="No web hits for query",
            )
        ],
    }


# ── 1. Admin can fetch + shape matches docs ───────────────────────────
def test_admin_metrics_returns_documented_shape():
    admin = _fake_user(UserRole.admin)
    app.dependency_overrides[get_current_user] = lambda: admin

    fake_session = _fake_session_for(_default_rows())

    async def session_override():
        yield fake_session

    app.dependency_overrides[get_db] = session_override

    client = TestClient(app)
    response = client.get(METRICS_URL)

    assert response.status_code == 200, response.text
    body = response.json()

    # Shape sanity
    assert set(body.keys()) >= {
        "window_hours",
        "as_of",
        "summary",
        "agent_latency",
        "throttle_events",
        "recent_errors",
    }
    assert body["window_hours"] == 24
    assert isinstance(body["agent_latency"], list)
    assert len(body["agent_latency"]) == 3
    assert {row["agent_name"] for row in body["agent_latency"]} == {
        "parser",
        "compliance",
        "rate_limiter",
    }
    assert body["summary"] == {
        "total_queries": 87,
        "total_agent_invocations": 412,
        "total_human_decisions": 6,
        "queries_with_errors": 3,
    }
    assert body["throttle_events"] == {
        "groq_429_count": 1,
        "groq_pacing_events": 42,
        "sanctions_pending_review": 9,
    }
    assert len(body["recent_errors"]) == 1
    err = body["recent_errors"][0]
    assert err["agent_name"] == "external_discovery"
    assert err["action"] == "no_web_results"


# ── 2. Non-admin gets 403 ─────────────────────────────────────────────
def test_non_admin_metrics_returns_403():
    manager = _fake_user(UserRole.procurement_manager)
    app.dependency_overrides[get_current_user] = lambda: manager

    client = TestClient(app)
    response = client.get(METRICS_URL)

    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


# ── 3. Math correctness — values flow from SQL row to response ────────
def test_latency_row_values_passthrough_to_int_ms():
    """
    The endpoint owns the boundary between Decimal/float SQL values and the
    JSON int response. Pin that conversion explicitly so a future refactor
    that drops the int() coercion doesn't silently leak floats to the UI.
    """
    admin = _fake_user(UserRole.admin)
    app.dependency_overrides[get_current_user] = lambda: admin

    rows = _default_rows()
    rows["latency"] = [
        SimpleNamespace(
            agent_name="compliance",
            p50=15200.7,
            p95=62100.4,
            mean=21800.0,
            cnt=87,
        ),
    ]
    fake_session = _fake_session_for(rows)

    async def session_override():
        yield fake_session

    app.dependency_overrides[get_db] = session_override

    client = TestClient(app)
    response = client.get(METRICS_URL)

    assert response.status_code == 200
    row = response.json()["agent_latency"][0]
    assert row == {
        "agent_name": "compliance",
        "p50_ms": 15200,
        "p95_ms": 62100,
        "mean_ms": 21800,
        "count": 87,
    }
    # Sanity: the int coercion is non-lossy on .0 but truncates non-zero decimals.
    assert isinstance(row["p50_ms"], int)
    assert isinstance(row["p95_ms"], int)


# ── 4. Bounds: window_hours must be 1..168 ────────────────────────────
def test_window_hours_lower_bound_rejected():
    admin = _fake_user(UserRole.admin)
    app.dependency_overrides[get_current_user] = lambda: admin

    client = TestClient(app)
    response = client.get(f"{METRICS_URL}?window_hours=0")
    assert response.status_code == 422


def test_window_hours_upper_bound_rejected():
    admin = _fake_user(UserRole.admin)
    app.dependency_overrides[get_current_user] = lambda: admin

    client = TestClient(app)
    response = client.get(f"{METRICS_URL}?window_hours=200")
    assert response.status_code == 422
