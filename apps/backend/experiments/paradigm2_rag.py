"""Paradigm 2 — minimal RAG baseline.

Retrieve-then-read, nothing else: Voyage embeddings + Milvus top-k retrieval
over the existing supplier corpus, one templated prompt to the LLM, top-5
selection. Deliberately NO compliance gate, NO verification loop, NO
clarification dialogue, NO ranking heuristics — the minimalism IS the
baseline. Chunking strategy: one document per supplier (see
experiments/README.md).

Output shape matches P1/P3: top-5 supplier names + ids + reasoning text.

Run on a sample query (needs Milvus + Postgres up):
    uv run python -m experiments.paradigm2_rag "ISO 9001 packaging supplier in Germany"
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterable
from typing import Any

from experiments.paradigm1_singleprompt import ParadigmResult

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 10

PROMPT_SYSTEM = (
    "You are a procurement sourcing assistant. You are given a user query "
    "and a numbered list of candidate suppliers retrieved from a database. "
    "Pick the 5 best-matching candidates (fewer if fewer qualify). Use ONLY "
    "the provided candidates. Respond with json only, in the shape: "
    '{"suppliers": [{"index": 1, "reasoning": "..."}]}'
)


def _supplier_doc(s: dict) -> str:
    """Render one supplier as the retrieval document shown to the LLM.

    One document per supplier (no sub-chunking): supplier records are short
    and atomic, so per-supplier chunks keep citations unambiguous.
    """
    certs = ", ".join(s.get("certifications") or []) or "none listed"
    return (
        f"{s.get('name', 'unknown')} — {s.get('city', '?')}, {s.get('country', '?')}. "
        f"Certifications: {certs}. "
        f"Capacity: {s.get('capacity_value', '?')} {s.get('capacity_unit', '')}. "
        f"{(s.get('description') or '')[:300]}"
    )


async def _fetch_suppliers(
    ids: list[str],
    *,
    allowed_supplier_ids: Iterable[str] | None = None,
) -> list[dict]:
    """Load supplier rows for the retrieved ids, preserving retrieval order.

    Only approved + active suppliers are materialised: pending_review /
    discovered / quarantined (is_active=False) rows are dropped here so a vector
    that leaked into the ANN result can never become a P2 candidate. Callers
    over-fetch and truncate so this filtering does not shrink the top-k.
    """
    from sqlalchemy import select

    from app.db.models import Supplier, SupplierStatus
    from app.db.session import AsyncSessionLocal

    if not ids:
        return []
    allowed_ids_list = (
        list(dict.fromkeys(str(sid) for sid in allowed_supplier_ids if sid))
        if allowed_supplier_ids is not None
        else None
    )
    if allowed_supplier_ids is not None:
        allowed_ids = set(allowed_ids_list or [])
        ids = [sid for sid in ids if sid in allowed_ids]
        if not ids:
            return []

    async with AsyncSessionLocal() as db:
        filters = [
            Supplier.id.in_(ids),
            Supplier.status == SupplierStatus.approved,
            Supplier.is_active == True,  # noqa: E712
        ]
        if allowed_ids_list is not None:
            filters.append(Supplier.id.in_(allowed_ids_list))
        result = await db.execute(select(Supplier).where(*filters))
        rows = {str(s.id): s for s in result.scalars().all()}
    out = []
    for sid in ids:
        s = rows.get(sid)
        if s is None:
            continue
        out.append({
            "id": str(s.id),
            "name": s.name,
            "city": s.city,
            "country": s.country,
            "certifications": list(s.certifications or []),
            "capacity_value": s.capacity_value,
            "capacity_unit": s.capacity_unit,
            "description": s.description,
        })
    return out


def build_prompt(raw_query: str, suppliers: list[dict]) -> str:
    lines = [f"User query: {raw_query}", "", "Candidates:"]
    for i, s in enumerate(suppliers, start=1):
        lines.append(f"{i}. {_supplier_doc(s)}")
    return "\n".join(lines)


def select_top5(raw_llm_json: str, suppliers: list[dict]) -> tuple[list[dict], list[str], str | None]:
    """Map the LLM's index picks back to supplier records."""
    picked: list[dict] = []
    reasons: list[str] = []
    seen: set[int] = set()
    try:
        payload = json.loads(raw_llm_json)
        for item in payload.get("suppliers") or []:
            if len(picked) >= 5:
                break
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            # Dedup: the model sometimes picks the same index twice (observed
            # live 2026-06-11); a top-5 with duplicates is degenerate output.
            if isinstance(idx, int) and 1 <= idx <= len(suppliers) and idx not in seen:
                seen.add(idx)
                picked.append(suppliers[idx - 1])
                reasons.append(str(item.get("reasoning") or "").strip())
    except (json.JSONDecodeError, AttributeError) as e:
        return [], [], f"unparseable model output: {e}"
    return picked, reasons, None


async def run_paradigm2(
    raw_query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    llm: Any = None,
    vector_store: Any = None,
    fetch_suppliers: Any = None,
    allowed_supplier_ids: Iterable[str] | None = None,
) -> ParadigmResult:
    """Run one query through the RAG baseline.

    All collaborators are injectable for tests; defaults use the real stack.
    """
    query = (raw_query or "").strip()
    if not query:
        raise ValueError("raw_query must be a non-empty string")

    if llm is None:
        from app.core.llm import get_llm_client

        llm = get_llm_client()
    if vector_store is None:
        from app.core.vector_store import get_vector_store

        vector_store = get_vector_store()
    if fetch_suppliers is None:
        fetch_suppliers = _fetch_suppliers
    allowed_ids_list = (
        list(dict.fromkeys(str(sid) for sid in allowed_supplier_ids if sid))
        if allowed_supplier_ids is not None
        else None
    )

    start = time.time()
    # Over-fetch, then filter to approved+active and truncate to top_k, so a
    # pending/discovered/quarantined vector can never occupy a top_k candidate
    # slot. Use a 3x buffer; raise if the index ever holds >2/3 non-approved.
    search_kwargs = {}
    if allowed_ids_list is not None:
        search_kwargs["allowed_supplier_ids"] = allowed_ids_list
    hits = vector_store.search(query, top_k=top_k * 3, **search_kwargs)
    retrieved_ids = [h.supplier_id for h in hits]
    if allowed_ids_list is not None:
        allowed_ids = set(allowed_ids_list)
        retrieved_ids = [sid for sid in retrieved_ids if sid in allowed_ids]
    if fetch_suppliers is _fetch_suppliers:
        suppliers = (
            await fetch_suppliers(
                retrieved_ids,
                allowed_supplier_ids=allowed_ids_list,
            )
        )[:top_k]
    else:
        suppliers = (await fetch_suppliers(retrieved_ids))[:top_k]
    ids = [s["id"] for s in suppliers]

    if not suppliers:
        return ParadigmResult(
            paradigm="P2-rag",
            raw_query=query,
            supplier_names=[],
            supplier_ids=[],
            reasoning=[],
            exec_ms=int((time.time() - start) * 1000),
            error="empty retrieval: no candidates in the corpus for this query",
        )

    prompt = build_prompt(query, suppliers)
    try:
        raw = llm.complete_json(
            [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001 — provider failure is a recorded outcome
        return ParadigmResult(
            paradigm="P2-rag",
            raw_query=query,
            supplier_names=[],
            supplier_ids=[],
            reasoning=[],
            exec_ms=int((time.time() - start) * 1000),
            error=f"{type(e).__name__}: {e}",
        )

    picked, reasons, parse_error = select_top5(raw, suppliers)
    return ParadigmResult(
        paradigm="P2-rag",
        raw_query=query,
        supplier_names=[s["name"] for s in picked],
        supplier_ids=[s["id"] for s in picked],
        reasoning=reasons,
        exec_ms=int((time.time() - start) * 1000),
        error=parse_error,
        extra={"retrieved_ids": ids, "top_k": top_k},
    )


def main() -> None:
    import asyncio

    logging.basicConfig(level=logging.INFO)
    query = " ".join(sys.argv[1:]) or "ISO 9001 certified packaging supplier in Germany"

    from app.core.cache import InMemoryCache, set_cache_instance
    from app.core.vector_store import create_vector_store, set_vector_store_instance

    set_cache_instance(InMemoryCache())
    set_vector_store_instance(create_vector_store())

    result = asyncio.run(run_paradigm2(query))
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
