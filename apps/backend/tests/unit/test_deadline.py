"""Shared query deadline regressions."""

import pytest

from app.agents.deadline import QueryDeadlineExceeded, remaining_seconds


def test_remaining_seconds_raises_after_deadline():
    with pytest.raises(QueryDeadlineExceeded):
        remaining_seconds({"deadline_at": 9.0}, monotonic=lambda: 10.0)


def test_remaining_seconds_reserves_cleanup_time():
    assert remaining_seconds(
        {"deadline_at": 20.0},
        reserve=2.0,
        monotonic=lambda: 10.0,
    ) == 8.0
