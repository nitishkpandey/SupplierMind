"""Regression guard for the SupplierBench runner's user_id.

The runner used to pass user_id="eval-runner" into the pipeline. Discovery
casts user_id to a UUID in the user-saves subquery, so a non-UUID label raised
a SQL error, zeroed every candidate set, and silently gave SupplierMind P@5=0
across the whole benchmark — which is why its row was never captured.
"""

import inspect
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.evaluation import runner
from app.evaluation.baselines import keyword_baseline_search
from app.platform.ai.context import current_ai_request_context


def test_eval_user_id_is_a_valid_uuid():
    uuid.UUID(runner.EVAL_USER_ID)  # raises if not a real UUID


def test_runner_never_passes_the_eval_runner_label():
    src = inspect.getsource(runner)
    assert "eval-runner" not in src


@pytest.mark.asyncio
async def test_full_runner_binds_internal_context(
    monkeypatch,
    tmp_path,
) -> None:
    benchmark_file = tmp_path / "benchmark.json"
    benchmark_file.write_text("[]", encoding="utf-8")
    observed = []

    def probe_supplier_ids():
        observed.append(current_ai_request_context())
        return []

    monkeypatch.setattr(runner, "BENCHMARK_FILE", benchmark_file)
    monkeypatch.setattr(
        runner,
        "RESULTS_FILE",
        tmp_path / "results.json",
    )
    monkeypatch.setattr(
        runner,
        "CHECKPOINT_FILE",
        tmp_path / "checkpoint.json",
    )
    monkeypatch.setattr(
        runner,
        "benchmark_supplier_ids",
        probe_supplier_ids,
    )

    await runner.run_full_evaluation(
        run_suppliermind=False,
        run_baselines=False,
    )

    assert observed[0].purpose == "evaluation.runner"
    assert observed[0].classification.value == "internal"
    assert observed[0].user_id is None


@pytest.mark.asyncio
async def test_baseline_logs_omit_raw_query(caplog) -> None:
    secret = "CUSTOMER-EVAL-SECRET-983A"
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    with caplog.at_level(
        logging.DEBUG,
        logger="app.evaluation.baselines",
    ):
        await keyword_baseline_search(
            f"Find metal suppliers for {secret}",
            db,
        )

    assert secret not in caplog.text
    assert "query_length=" in caplog.text
