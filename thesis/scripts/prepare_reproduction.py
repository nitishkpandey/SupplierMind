from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


EXCLUDED_QUERY_ID = "49554c47-ef51-554a-8404-be6b6761b6ca"


def deduplicate_benchmark(
    queries: list[dict[str, Any]],
    excluded_query_id: str = EXCLUDED_QUERY_ID,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    excluded = [query for query in queries if query["id"] == excluded_query_id]
    if len(excluded) != 1:
        raise ValueError(f"Expected one excluded query, found {len(excluded)}")

    duplicate_text = excluded[0]["raw_query"].strip().casefold()
    matching_texts = [
        query for query in queries if query["raw_query"].strip().casefold() == duplicate_text
    ]
    if len(matching_texts) != 2:
        raise ValueError("Excluded query is not one member of an exact duplicate pair")

    corrected: list[dict[str, Any]] = []
    query_numbers: dict[str, int] = {}
    for query in queries:
        if query["id"] == excluded_query_id:
            continue
        revised = copy.deepcopy(query)
        revised["source_query_number"] = query["query_number"]
        revised["query_number"] = len(corrected) + 1
        query_numbers[revised["id"]] = revised["query_number"]
        corrected.append(revised)

    normalized_texts = [query["raw_query"].strip().casefold() for query in corrected]
    if len(corrected) != len(queries) - 1:
        raise ValueError("Corrected benchmark removed an unexpected number of queries")
    if len(set(normalized_texts)) != len(normalized_texts):
        raise ValueError("Corrected benchmark still contains duplicate query text")
    return corrected, query_numbers


def _remove_reasoning(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_reasoning(item)
            for key, item in value.items()
            if key != "reasoning"
        }
    if isinstance(value, list):
        return [_remove_reasoning(item) for item in value]
    return value


def sanitize_run(
    run: dict[str, Any],
    excluded_query_id: str | None,
    query_numbers: dict[str, int],
) -> dict[str, Any]:
    sanitized = _remove_reasoning(copy.deepcopy(run))
    sanitized.pop("aggregated", None)

    systems = sanitized.get("per_query_metrics")
    if not isinstance(systems, dict):
        raise ValueError("Run does not contain per_query_metrics by system")

    for records in systems.values():
        if not isinstance(records, list):
            raise ValueError("Each system must contain a list of query metrics")
        retained = []
        for record in records:
            query_id = record.get("query_id")
            if excluded_query_id is not None and query_id == excluded_query_id:
                continue
            if query_id not in query_numbers:
                raise ValueError(f"Unknown query id in run: {query_id}")
            record["query_number"] = query_numbers[query_id]
            retained.append(record)
        records[:] = retained

    expected_count = len(query_numbers)
    counts = {len(records) for records in systems.values()}
    if expected_count not in counts or not counts.issubset({0, expected_count}):
        raise ValueError(f"Expected {expected_count} records per system, found {sorted(counts)}")
    sanitized["query_count"] = expected_count
    return sanitized


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _prepare_runs(
    source_dir: Path,
    destination_dir: Path,
    excluded_query_id: str | None,
    query_numbers: dict[str, int],
) -> list[str]:
    written = []
    for source in sorted(source_dir.glob("run_*.json")):
        run = json.loads(source.read_text())
        sanitized = sanitize_run(run, excluded_query_id, query_numbers)
        destination = destination_dir / source.name
        _write_json(destination, sanitized)
        written.append(destination.name)
    if not written:
        raise ValueError(f"No run files found in {source_dir}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-thesis", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    source = args.source_thesis
    output = args.output_root / "thesis"
    original = json.loads((source / "benchmark" / "supplierbench25_10k.json").read_text())
    corrected, query_numbers = deduplicate_benchmark(original)
    if len(corrected) != 24:
        raise ValueError(f"Expected 24 corrected queries, found {len(corrected)}")
    abstention = json.loads((source / "benchmark" / "abstention5_10k.json").read_text())
    abstention_numbers = {query["id"]: query["query_number"] for query in abstention}

    _write_json(output / "benchmark" / "supplierbench24_10k.json", corrected)
    _write_json(output / "benchmark" / "abstention5_10k.json", abstention)

    runs = {
        "main": _prepare_runs(
            source / "results" / "10k",
            output / "results" / "main",
            EXCLUDED_QUERY_ID,
            query_numbers,
        ),
        "ablation": _prepare_runs(
            source / "results" / "10k_ablation_no_compliance",
            output / "results" / "ablation",
            EXCLUDED_QUERY_ID,
            query_numbers,
        ),
        "abstention": _prepare_runs(
            source / "results" / "10k_abstention",
            output / "results" / "abstention",
            None,
            abstention_numbers,
        ),
    }

    exclusion = {
        "reason": "Exact duplicate query removed before analysis",
        "excluded_query_id": EXCLUDED_QUERY_ID,
        "excluded_source_query_number": 22,
        "duplicate_of_query_id": "56c444e6-f04e-5334-a964-dfb03810507a",
        "duplicate_of_source_query_number": 13,
        "original_query_count": 25,
        "corrected_query_count": 24,
        "renumbering": "Source queries 23 to 25 become corrected queries 22 to 24",
        "runs": runs,
    }
    _write_json(output / "EXCLUSION.json", exclusion)


if __name__ == "__main__":
    main()
