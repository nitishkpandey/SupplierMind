"""Task 1.6 Component B — per-model sliding-window throttle.

Deterministic tests with an injected fake clock — no real sleeping, no network.
The limiter paces requests to stay under per-model RPM/TPM so the pipeline
stops fighting 429s with reactive backoff.
"""

import logging

from app.core.llm import estimate_message_tokens
from app.core.rate_limiter import ModelRateLimiter


class FakeClock:
    """Controllable monotonic clock. sleep() just advances virtual time."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def monotonic(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        if dt > 0:
            self.t += dt


def make_limiter(rpm: int, tpm: int, clock: FakeClock, margin: float = 1.0) -> ModelRateLimiter:
    return ModelRateLimiter(
        limits={"m": {"rpm": rpm, "tpm": tpm}},
        default_limit={"rpm": rpm, "tpm": tpm},
        margin=margin,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


# ── basic pacing ─────────────────────────────────────────────────────
def test_under_limit_does_not_sleep():
    clock = FakeClock()
    rl = make_limiter(rpm=10, tpm=10_000, clock=clock)
    for _ in range(5):
        rl.acquire("m", 100)
    assert clock.t == 1000.0  # no time advanced → never slept


def test_rpm_cap_forces_sleep_until_oldest_ages_out(caplog):
    clock = FakeClock()
    rl = make_limiter(rpm=4, tpm=10_000_000, clock=clock)
    for _ in range(4):  # fill the per-minute request budget
        rl.acquire("m", 1)
    with caplog.at_level(logging.INFO, logger="app.core.rate_limiter"):
        rl.acquire("m", 1)  # 5th request must wait a full window
    assert clock.t == 1060.0  # slept 60s for the oldest to age out
    assert "Pacing call" in "\n".join(r.getMessage() for r in caplog.records)


def test_tpm_cap_forces_sleep():
    clock = FakeClock()
    rl = make_limiter(rpm=10_000, tpm=1_000, clock=clock)
    rl.acquire("m", 800)
    rl.acquire("m", 300)  # 800 + 300 > 1000 → must pace
    assert clock.t > 1000.0


def test_entries_older_than_window_are_pruned():
    clock = FakeClock()
    rl = make_limiter(rpm=4, tpm=10_000_000, clock=clock)
    for _ in range(4):
        rl.acquire("m", 1)
    clock.t += 61  # let the whole window age out naturally
    rl.acquire("m", 1)  # window empty again → no sleep needed
    assert clock.t == 1061.0


def test_update_actual_tokens_replaces_estimate():
    clock = FakeClock()
    rl = make_limiter(rpm=10_000, tpm=1_000, clock=clock)
    ts = rl.acquire("m", 100)  # estimate low
    rl.update_actual_tokens("m", ts, 900)  # real usage much higher
    rl.acquire("m", 200)  # 900 + 200 > 1000 → now blocks
    assert clock.t > 1000.0


def test_unknown_model_uses_default_limit():
    clock = FakeClock()
    rl = make_limiter(rpm=5, tpm=5_000, clock=clock)
    # Never configured "other" explicitly — must fall back to default, not crash.
    ts = rl.acquire("other-model", 10)
    assert isinstance(ts, float)


# ── token estimator ──────────────────────────────────────────────────
def test_estimate_message_tokens_scales_with_content():
    small = estimate_message_tokens([{"role": "user", "content": "x" * 35}])
    large = estimate_message_tokens([{"role": "user", "content": "x" * 350}])
    assert small >= 9
    assert large > small
