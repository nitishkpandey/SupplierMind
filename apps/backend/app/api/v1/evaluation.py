"""
app/api/v1/evaluation.py — Evaluation endpoints for the admin dashboard.

These endpoints let admins trigger evaluations and view results
through the web UI (Phase 4 will build the frontend for this).
"""

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import require_admin
from app.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter()

RESULTS_FILE = Path(__file__).parent.parent.parent.parent / "data" / "evaluation_results.json"
REPORT_FILE = Path(__file__).parent.parent.parent.parent / "data" / "thesis_report.json"


@router.post(
    "/run",
    summary="Trigger a SupplierBench evaluation run [admin only]",
)
async def trigger_evaluation(
    background_tasks: BackgroundTasks,
    baselines_only: bool = False,
    query_limit: int | None = None,
    current_user: Annotated[User, Depends(require_admin)] = None,
) -> dict:
    """
    Triggers a full evaluation run in the background.
    Check /eval/results after completion.
    Full run takes ~15 minutes. Baselines-only takes ~5 seconds.
    """
    background_tasks.add_task(
        _run_evaluation_background,
        baselines_only=baselines_only,
        query_limit=query_limit,
    )
    return {
        "message": "Evaluation started in background",
        "baselines_only": baselines_only,
        "estimated_time": "~5 seconds" if baselines_only else "~15 minutes",
        "check_results_at": "/api/v1/eval/results",
    }


@router.get("/results", summary="Get latest evaluation results")
async def get_results(
    current_user: Annotated[User, Depends(require_admin)] = None,
) -> dict:
    """Returns the most recent evaluation results."""
    if not RESULTS_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="No evaluation results found. Run POST /api/v1/eval/run first.",
        )
    with open(RESULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


@router.get("/report", summary="Get thesis report from latest results")
async def get_report(
    current_user: Annotated[User, Depends(require_admin)] = None,
) -> dict:
    """Returns the formatted thesis report."""
    if not REPORT_FILE.exists():
        # Try to generate it
        if RESULTS_FILE.exists():
            from app.evaluation.report import generate_thesis_report
            return generate_thesis_report()
        raise HTTPException(
            status_code=404,
            detail="No report found. Run evaluation first.",
        )
    with open(REPORT_FILE, encoding="utf-8") as f:
        return json.load(f)


async def _run_evaluation_background(
    baselines_only: bool = False,
    query_limit: int | None = None,
) -> None:
    """Background task for running evaluation."""
    try:
        from app.core.cache import InMemoryCache, set_cache_instance
        from app.evaluation.runner import run_full_evaluation
        from app.evaluation.report import generate_thesis_report

        if not baselines_only:
            from app.core.vector_store import create_vector_store, set_vector_store_instance
            set_cache_instance(InMemoryCache())
            vs = create_vector_store()
            set_vector_store_instance(vs)

        await run_full_evaluation(
            run_suppliermind=not baselines_only,
            run_baselines=True,
            query_limit=query_limit,
        )
        generate_thesis_report()
        logger.info("Background evaluation completed")
    except Exception as e:
        logger.exception("Background evaluation failed: %s", e)
