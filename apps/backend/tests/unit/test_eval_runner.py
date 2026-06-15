"""Regression guard for the SupplierBench runner's user_id.

The runner used to pass user_id="eval-runner" into the pipeline. Discovery
casts user_id to a UUID in the user-saves subquery, so a non-UUID label raised
a SQL error, zeroed every candidate set, and silently gave SupplierMind P@5=0
across the whole benchmark — which is why its row was never captured.
"""

import inspect
import uuid

from app.evaluation import runner


def test_eval_user_id_is_a_valid_uuid():
    uuid.UUID(runner.EVAL_USER_ID)  # raises if not a real UUID


def test_runner_never_passes_the_eval_runner_label():
    src = inspect.getsource(runner)
    assert "eval-runner" not in src
