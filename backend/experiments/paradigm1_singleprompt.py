"""Paradigm 1 — single-prompt LLM baseline (Development Plan, Phase 2).

ONE prompt, NO corpus access, NO tools, NO retrieval. The model answers the
procurement query from parametric knowledge alone. This is the deliberate
weak baseline: it cannot ground its answers in the benchmark corpus, so any
corpus-overlap metric (P@5, MRR) measures exactly how far parametric
knowledge gets you — the design decision is documented in
experiments/README.md.

Output shape matches Paradigm 3: top-5 supplier names + reasoning text.

Run on a sample query:
    uv run python -m experiments.paradigm1_singleprompt "ISO 9001 packaging supplier in Germany"
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PROMPT_SYSTEM = (
    "You are a procurement sourcing assistant. The user describes what they "
    "need; you suggest up to 5 plausible real-world suppliers from your own "
    "knowledge. You have NO database access — do not pretend to cite one. "
    "Respond with json only, in the shape: "
    '{"suppliers": [{"name": "...", "reasoning": "..."}]}'
)


@dataclass
class ParadigmResult:
    """Common output shape for all three paradigms (see experiments/README.md)."""

    paradigm: str
    raw_query: str
    supplier_names: list[str]
    supplier_ids: list[str]          # P1 has no corpus access: always []
    reasoning: list[str]
    exec_ms: int
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def run_paradigm1(raw_query: str, llm: Any = None) -> ParadigmResult:
    """Run one query through the single-prompt baseline.

    `llm` is injectable for tests; defaults to the application provider
    (GPT-4o-mini when LLM_PROVIDER=openai).
    """
    query = (raw_query or "").strip()
    if not query:
        raise ValueError("raw_query must be a non-empty string")

    if llm is None:
        from app.core.llm import get_llm_client

        llm = get_llm_client()

    start = time.time()
    try:
        raw = llm.complete_json(
            [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": query},
            ],
            max_tokens=1024,
            temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001 — a provider failure is a recorded outcome
        return ParadigmResult(
            paradigm="P1-singleprompt",
            raw_query=query,
            supplier_names=[],
            supplier_ids=[],
            reasoning=[],
            exec_ms=int((time.time() - start) * 1000),
            error=f"{type(e).__name__}: {e}",
        )
    exec_ms = int((time.time() - start) * 1000)

    names: list[str] = []
    reasons: list[str] = []
    parse_error: str | None = None
    try:
        payload = json.loads(raw)
        for item in (payload.get("suppliers") or [])[:5]:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]).strip())
                reasons.append(str(item.get("reasoning") or "").strip())
    except (json.JSONDecodeError, AttributeError) as e:
        parse_error = f"unparseable model output: {e}"

    return ParadigmResult(
        paradigm="P1-singleprompt",
        raw_query=query,
        supplier_names=names,
        supplier_ids=[],  # parametric-only: cannot reference corpus IDs
        reasoning=reasons,
        exec_ms=exec_ms,
        error=parse_error,
        extra={"raw_response_head": raw[:300]},
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    query = " ".join(sys.argv[1:]) or "ISO 9001 certified packaging supplier in Germany"
    result = run_paradigm1(query)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
