"""Endpoint + resume tests for Task 3.3 (Component D).

These pin the Component-C API contracts and the Component-B resume
guardrails:

- GET /queries/{id}/clarification returns 404 (not 403) on cross-user
  access — see assert_owner_or_admin's existence-leak rationale.
- POST /queries/{id}/clarify with a valid answer returns 200 + queues
  the background resume.
- POST /queries/{id}/clarify with empty answer returns 400.
- resume_pipeline() raises MaxTurnsReached when the next turn would
  exceed the 3-turn cap.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import UserRole
from app.db.repositories.clarification_repo import MaxTurnsReached
from app.db.session import get_db
from app.main import app

# ── Fixtures ─────────────────────────────────────────────────────────


def _override_db():
    """A mock DB session that swallows execute()/commit() calls."""
    mock = AsyncMock()
    mock.execute = AsyncMock()
    mock.commit = AsyncMock()
    yield mock


def _fake_user(role: UserRole = UserRole.procurement_manager) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email="user@test.local",
        name="test-user",
        role=role,
        is_active=True,
    )


@pytest.fixture(autouse=True)
def _reset_overrides():
    app.dependency_overrides[get_db] = _override_db
    yield
    app.dependency_overrides.clear()


def _fake_pc(user_id, *, turn: int = 1, qid=None) -> SimpleNamespace:
    """Stand-in for a PendingClarification row."""
    from datetime import datetime, timezone
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        query_id=qid or uuid4(),
        turn_number=turn,
        clarification_question="What product are you sourcing?",
        created_at=datetime.now(timezone.utc),
        partial_constraints={"product_type": None},
        react_trace=[],
        raw_query="find me suppliers for our project",
        resolved_at=None,
        user_answer=None,
    )


# ── 1. GET /clarification — cross-user returns 404 ───────────────────


def test_get_clarification_cross_user_returns_404():
    """Spec D-5: user B cannot see user A's pending clarification.

    The endpoint returns 404 (not 403) so the response is identical to
    'no clarification at all' — a probe cannot distinguish 'not yours'
    from 'doesn't exist'.
    """
    owner = _fake_user()
    intruder = _fake_user()
    query_id = uuid4()
    pc = _fake_pc(user_id=owner.id, qid=query_id)

    app.dependency_overrides[get_current_user] = lambda: intruder

    mock_repo = MagicMock()
    mock_repo.get_open_for_query = AsyncMock(return_value=pc)
    with patch(
        "app.api.v1.queries.ClarificationRepository", return_value=mock_repo
    ):
        client = TestClient(app)
        response = client.get(f"/api/v1/queries/{query_id}/clarification")

    assert response.status_code == 404
    assert response.json()["detail"] == "No pending clarification"


# ── 2. GET /clarification — owner sees it ────────────────────────────


def test_get_clarification_owner_sees_open_question():
    owner = _fake_user()
    query_id = uuid4()
    pc = _fake_pc(user_id=owner.id, qid=query_id, turn=2)

    app.dependency_overrides[get_current_user] = lambda: owner

    mock_repo = MagicMock()
    mock_repo.get_open_for_query = AsyncMock(return_value=pc)
    with patch(
        "app.api.v1.queries.ClarificationRepository", return_value=mock_repo
    ):
        client = TestClient(app)
        response = client.get(f"/api/v1/queries/{query_id}/clarification")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(pc.id)
    assert body["question"] == pc.clarification_question
    assert body["turn_number"] == 2
    assert body["max_turns"] == 3


# ── 3. POST /clarify — owner submits answer → 200, kicks resume ──────


def test_post_clarify_owner_submits_answer_returns_200():
    """Spec D-3: a valid answer from the owner queues the resume."""
    owner = _fake_user()
    query_id = uuid4()
    pc = _fake_pc(user_id=owner.id, qid=query_id)

    app.dependency_overrides[get_current_user] = lambda: owner

    mock_repo = MagicMock()
    mock_repo.get_open_for_query = AsyncMock(return_value=pc)

    # Background task: replace _resume_pipeline_background with a no-op so
    # the test doesn't try to call into the real pipeline.
    mock_bg = AsyncMock()
    with patch(
        "app.api.v1.queries.ClarificationRepository", return_value=mock_repo
    ), patch(
        "app.api.v1.queries._resume_pipeline_background", mock_bg
    ):
        client = TestClient(app)
        response = client.post(
            f"/api/v1/queries/{query_id}/clarify",
            json={"answer": "cardboard boxes"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resuming"
    assert body["turn_number"] == 1
    assert body["id"] == str(pc.id)

    # TestClient runs background tasks synchronously after response.
    mock_bg.assert_awaited_once()
    args, kwargs = mock_bg.call_args
    assert kwargs["user_answer"] == "cardboard boxes"
    assert kwargs["query_id"] == str(query_id)


# ── 3b. POST /clarify — empty answer rejected ────────────────────────


def test_post_clarify_empty_answer_returns_422_or_400():
    """Pydantic constrains min_length=1, so the body fails validation."""
    owner = _fake_user()
    query_id = uuid4()
    pc = _fake_pc(user_id=owner.id, qid=query_id)

    app.dependency_overrides[get_current_user] = lambda: owner

    mock_repo = MagicMock()
    mock_repo.get_open_for_query = AsyncMock(return_value=pc)
    with patch(
        "app.api.v1.queries.ClarificationRepository", return_value=mock_repo
    ):
        client = TestClient(app)
        # Whitespace-only ⇒ passes Pydantic min_length but is stripped to
        # empty in the handler ⇒ 400.
        response = client.post(
            f"/api/v1/queries/{query_id}/clarify",
            json={"answer": "   "},
        )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_stream_replays_open_clarification_from_database():
    """SSE buffers are in-memory, so reloads/reconnects can miss events.

    If the durable database state says the query is pending with an open
    clarification, `/stream` must replay `needs_clarification` immediately.
    """
    from app.api.v1 import queries as q
    from app.db.models import QueryStatus

    owner = _fake_user()
    query_id = uuid4()
    pc = _fake_pc(user_id=owner.id, qid=query_id, turn=2)
    pc.id = uuid4()
    pc.clarification_question = "What delivery or capacity requirements matter most?"
    q._sse_events[str(query_id)] = []

    query = SimpleNamespace(
        id=query_id,
        user_id=owner.id,
        status=QueryStatus.pending,
        results=[],
        execution_time_ms=None,
        error_message=None,
    )

    mock_query_repo = MagicMock()
    mock_query_repo.get_by_id = AsyncMock(return_value=query)
    mock_clarification_repo = MagicMock()
    mock_clarification_repo.get_open_for_query = AsyncMock(return_value=pc)

    with patch(
        "app.core.security.decode_access_token",
        return_value={"sub": str(owner.id)},
    ), patch(
        "app.api.v1.queries.QueryRepository", return_value=mock_query_repo
    ), patch(
        "app.api.v1.queries.ClarificationRepository", return_value=mock_clarification_repo
    ), patch.object(
        q.settings, "SSE_TIMEOUT_SECONDS", 0
    ):
        client = TestClient(app)
        with client.stream(
            "GET", f"/api/v1/queries/{query_id}/stream?token=test-token"
        ) as response:
            body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: needs_clarification" in body
    assert str(pc.id) in body
    assert pc.clarification_question in body


# ── 4. resume_pipeline — max-turns guardrail ─────────────────────────


@pytest.mark.asyncio
async def test_resume_pipeline_raises_when_next_turn_exceeds_cap():
    """Spec D-4: when an answer would push the dialogue to turn 4, the
    orchestrator refuses (the DB CHECK is a hard backstop; this is the
    code-level enforcement that runs first)."""
    from app.agents.orchestrator import resume_pipeline

    pc = _fake_pc(user_id=uuid4(), turn=3)  # next would be 4

    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)

    with patch(
        "app.db.session.SyncSessionLocal", return_value=fake_session
    ), patch(
        "app.db.repositories.clarification_repo.get_pending_clarification_sync",
        return_value=pc,
    ):
        with pytest.raises(MaxTurnsReached):
            await resume_pipeline(str(pc.id), "any answer")


# ── 5. resume_pipeline — already-resolved guardrail ──────────────────


@pytest.mark.asyncio
async def test_resume_pipeline_raises_when_already_resolved():
    from datetime import datetime, timezone

    from app.agents.orchestrator import resume_pipeline
    from app.db.repositories.clarification_repo import ClarificationAlreadyResolved

    pc = _fake_pc(user_id=uuid4(), turn=1)
    pc.resolved_at = datetime.now(timezone.utc)
    pc.user_answer = "already answered"

    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)

    with patch(
        "app.db.session.SyncSessionLocal", return_value=fake_session
    ), patch(
        "app.db.repositories.clarification_repo.get_pending_clarification_sync",
        return_value=pc,
    ):
        with pytest.raises(ClarificationAlreadyResolved):
            await resume_pipeline(str(pc.id), "any answer")


# ── 6. degraded clarification must not strand the query ──────────────


@pytest.mark.asyncio
async def test_degraded_clarification_fails_query_instead_of_stranding_it():
    """Task 3.4 smoke regression: a degraded Parser run (max_iterations /
    llm_error fallback) sets needs_clarification=True but persists NO
    pending_clarifications row (clarification_id=None). Pausing there
    leaves the query in `pending` forever with no /clarify target.

    The background task must instead fail the query gracefully with the
    clarification text as the error message, and must NOT emit a
    needs_clarification SSE event."""
    from app.api.v1 import queries as q

    query_id = str(uuid4())
    events: list[dict] = []
    q._sse_events[query_id] = events  # keep our own reference; finally() pops the dict key

    degraded_state = {
        "needs_clarification": True,
        "clarification_id": None,  # degraded path: no resumable row
        "clarification_question": "What product are you sourcing?",
        "react_terminated_by": "max_iterations",
        "audit_log": [],
        "ranked_suppliers": [],
        "parsed_constraints": {"product_type": None},
        "detected_language": "en",
        "error": None,
    }

    fake_session = AsyncMock()
    fake_session.add = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.db.session.AsyncSessionLocal", MagicMock(return_value=cm)
    ), patch.object(
        q, "run_pipeline", AsyncMock(return_value=degraded_state)
    ), patch.object(
        q.asyncio, "sleep", AsyncMock()  # skip the SSE cleanup delay
    ):
        await q._run_pipeline_background(
            query_id=query_id,
            raw_query="we need things for our project",
            user_id=str(uuid4()),
            search_scope="approved_only",
        )

    event_types = [e.get("type") for e in events]
    assert "needs_clarification" not in event_types, (
        "degraded path must not pause: there is no row to answer"
    )
    error_events = [e for e in events if e.get("type") == "error"]
    assert error_events, f"expected an error event, got: {event_types}"
    assert "What product" in error_events[0]["message"]

    # The query row must reach a terminal state (failed), not stay pending.
    update_params = [
        stmt.compile().params
        for (stmt,), _ in fake_session.execute.call_args_list
        if hasattr(stmt, "compile")
    ]
    statuses = [p.get("status") for p in update_params if "status" in p]
    from app.db.models import QueryStatus
    assert QueryStatus.failed in statuses, f"expected failed status update, got: {statuses}"


@pytest.mark.asyncio
async def test_resumed_pipeline_reclarification_emits_needs_clarification_event():
    """Regression: after a user answers turn 1, the Parser may ask turn 2.

    The frontend listens for the `needs_clarification` SSE event type. Emitting
    this as a generic `agent_update` leaves the UI spinning until the 300s SSE
    timeout even though a pending_clarifications row exists.
    """
    from app.api.v1 import queries as q

    query_id = str(uuid4())
    clarification_id = str(uuid4())
    events: list[dict] = []
    q._sse_events[query_id] = events

    final_state = {
        "needs_clarification": True,
        "clarification_id": clarification_id,
        "clarification_question": "What delivery or capacity requirements matter most?",
        "turn_number": 2,
        "audit_log": [],
    }

    fake_session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.db.session.AsyncSessionLocal", MagicMock(return_value=cm)
    ), patch.object(
        q, "resume_pipeline", AsyncMock(return_value=final_state)
    ):
        await q._resume_pipeline_background(
            clarification_id=str(uuid4()),
            user_answer="Machinery tools",
            query_id=query_id,
        )

    clarification_events = [
        event for event in events if event.get("type") == "needs_clarification"
    ]
    assert clarification_events == [
        {
            "type": "needs_clarification",
            "query_id": query_id,
            "clarification_id": clarification_id,
            "question": "What delivery or capacity requirements matter most?",
            "turn_number": 2,
        }
    ]
