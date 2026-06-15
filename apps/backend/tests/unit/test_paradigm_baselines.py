"""Unit tests for the P1/P2 baseline scripts (Development Plan, Phase 2).

No live services: LLM, vector store and DB access are all injected fakes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from experiments.paradigm1_singleprompt import run_paradigm1
from experiments.paradigm2_rag import build_prompt, run_paradigm2, select_top5


class _FakeLLM:
    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[list[dict]] = []

    def complete_json(self, messages, **kwargs):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.response or "{}"


@dataclass
class _Hit:
    supplier_id: str
    similarity_score: float = 0.9
    distance: float = 0.1


class _FakeVectorStore:
    def __init__(self, ids: list[str]):
        self.ids = ids
        self.calls: list[tuple[str, int]] = []

    def search(self, query_text: str, top_k: int = 20):
        self.calls.append((query_text, top_k))
        return [_Hit(supplier_id=i) for i in self.ids[:top_k]]


def _fake_fetch(suppliers: list[dict]):
    async def fetch(ids: list[str]) -> list[dict]:
        by_id = {s["id"]: s for s in suppliers}
        return [by_id[i] for i in ids if i in by_id]
    return fetch


def _supplier(i: int) -> dict:
    return {
        "id": f"id-{i}",
        "name": f"Supplier {i}",
        "city": "Munich",
        "country": "Germany",
        "certifications": ["ISO 9001"],
        "capacity_value": 1000.0,
        "capacity_unit": "units/month",
        "description": f"Supplier number {i} making packaging.",
    }


# -- Paradigm 1 ---------------------------------------------------------------


def test_p1_happy_path_parses_names_and_reasoning():
    llm = _FakeLLM(json.dumps({
        "suppliers": [
            {"name": "Acme Packaging GmbH", "reasoning": "German packaging maker"},
            {"name": "BoxCo", "reasoning": "ISO 9001 certified"},
        ]
    }))
    result = run_paradigm1("ISO 9001 packaging supplier in Germany", llm=llm)

    assert result.paradigm == "P1-singleprompt"
    assert result.supplier_names == ["Acme Packaging GmbH", "BoxCo"]
    assert result.supplier_ids == []  # parametric only: no corpus ids, ever
    assert result.error is None
    assert len(result.reasoning) == 2


def test_p1_empty_query_raises():
    with pytest.raises(ValueError):
        run_paradigm1("   ", llm=_FakeLLM("{}"))


def test_p1_malformed_model_output_is_recorded_not_raised():
    llm = _FakeLLM("this is not json")
    result = run_paradigm1("packaging supplier", llm=llm)
    assert result.supplier_names == []
    assert "unparseable" in (result.error or "")


def test_p1_provider_failure_is_recorded_not_raised():
    llm = _FakeLLM(error=RuntimeError("provider down"))
    result = run_paradigm1("packaging supplier", llm=llm)
    assert result.supplier_names == []
    assert "RuntimeError" in (result.error or "")


# -- Paradigm 2 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2_retrieval_returns_k_and_prompt_contains_candidates():
    suppliers = [_supplier(i) for i in range(1, 11)]
    vs = _FakeVectorStore([s["id"] for s in suppliers])
    llm = _FakeLLM(json.dumps({
        "suppliers": [{"index": 1, "reasoning": "best match"},
                      {"index": 3, "reasoning": "also good"}]
    }))

    result = await run_paradigm2(
        "packaging supplier in Munich",
        top_k=10,
        llm=llm,
        vector_store=vs,
        fetch_suppliers=_fake_fetch(suppliers),
    )

    assert vs.calls == [("packaging supplier in Munich", 10)]
    # The prompt the LLM saw lists all 10 candidates.
    user_msg = llm.calls[0][1]["content"]
    assert "1. Supplier 1" in user_msg and "10. Supplier 10" in user_msg
    # Index picks map back to records.
    assert result.supplier_ids == ["id-1", "id-3"]
    assert result.supplier_names == ["Supplier 1", "Supplier 3"]
    assert result.error is None


@pytest.mark.asyncio
async def test_p2_empty_corpus_records_error():
    vs = _FakeVectorStore([])
    result = await run_paradigm2(
        "anything",
        llm=_FakeLLM("{}"),
        vector_store=vs,
        fetch_suppliers=_fake_fetch([]),
    )
    assert result.supplier_ids == []
    assert "empty retrieval" in (result.error or "")


@pytest.mark.asyncio
async def test_p2_out_of_range_indices_are_ignored():
    suppliers = [_supplier(1), _supplier(2)]
    llm = _FakeLLM(json.dumps({
        "suppliers": [{"index": 1, "reasoning": "ok"},
                      {"index": 99, "reasoning": "hallucinated"},
                      {"index": 0, "reasoning": "also invalid"}]
    }))
    result = await run_paradigm2(
        "q",
        llm=llm,
        vector_store=_FakeVectorStore([s["id"] for s in suppliers]),
        fetch_suppliers=_fake_fetch(suppliers),
    )
    assert result.supplier_ids == ["id-1"]


def test_p2_prompt_and_selection_helpers():
    suppliers = [_supplier(1)]
    prompt = build_prompt("need boxes", suppliers)
    assert "User query: need boxes" in prompt
    assert "ISO 9001" in prompt

    picked, reasons, err = select_top5("not json at all", suppliers)
    assert picked == [] and "unparseable" in (err or "")


@pytest.mark.asyncio
async def test_p2_duplicate_indices_are_deduplicated():
    suppliers = [_supplier(1), _supplier(2), _supplier(3)]
    llm = _FakeLLM(json.dumps({
        "suppliers": [{"index": 2, "reasoning": "good"},
                      {"index": 2, "reasoning": "repeated pick"},
                      {"index": 3, "reasoning": "also good"}]
    }))
    result = await run_paradigm2(
        "q",
        llm=llm,
        vector_store=_FakeVectorStore([s["id"] for s in suppliers]),
        fetch_suppliers=_fake_fetch(suppliers),
    )
    assert result.supplier_ids == ["id-2", "id-3"]
