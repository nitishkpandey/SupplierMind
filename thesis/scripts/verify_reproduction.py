from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
THESIS = ROOT / "thesis"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contains_key(value: Any, key_name: str) -> bool:
    if isinstance(value, dict):
        return key_name in value or any(contains_key(item, key_name) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key_name) for item in value)
    return False


def main() -> None:
    benchmark = json.loads(
        (THESIS / "benchmark" / "supplierbench24_10k.json").read_text()
    )
    if len(benchmark) != 24:
        raise SystemExit("SupplierBench-24 does not contain 24 queries")
    if len({query["id"] for query in benchmark}) != 24:
        raise SystemExit("SupplierBench-24 contains duplicate query identifiers")
    if len({query["raw_query"].strip().casefold() for query in benchmark}) != 24:
        raise SystemExit("SupplierBench-24 contains duplicate query text")
    if any(query["ground_truth_count"] < 3 for query in benchmark):
        raise SystemExit("A satisfiable query has fewer than three ground truth matches")
    print("24 unique satisfiable queries")

    abstention = json.loads((THESIS / "benchmark" / "abstention5_10k.json").read_text())
    if len(abstention) != 5 or any(query["ground_truth_count"] != 0 for query in abstention):
        raise SystemExit("Abstention benchmark integrity check failed")
    print("5 verified unsatisfiable queries")

    run_files = []
    for directory, expected in (("main", 5), ("ablation", 3), ("abstention", 1)):
        files = sorted((THESIS / "results" / directory).glob("run_*.json"))
        if len(files) != expected:
            raise SystemExit(f"Expected {expected} {directory} runs, found {len(files)}")
        run_files.extend(files)

    sensitive = re.compile(
        r"(?:sk-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,}|tvly-[A-Za-z0-9_-]{20,}|"
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|https?://)",
        re.IGNORECASE,
    )
    for path in run_files:
        text = path.read_text()
        data = json.loads(text)
        if contains_key(data, "reasoning"):
            raise SystemExit(f"Free text reasoning remains in {path.relative_to(ROOT)}")
        if sensitive.search(text):
            raise SystemExit(f"Sensitive pattern found in {path.relative_to(ROOT)}")
    print("9 sanitized archived runs")

    metrics = json.loads((THESIS / "results" / "METRICS.json").read_text())
    expected_metrics = {
        ("suppliermind", "mean"): 0.7467,
        ("p2_rag", "mean"): 0.5167,
        ("suppliermind", "hard"): 0.6133,
        ("p2_rag", "hard"): 0.2333,
    }
    for (system, field), expected in expected_metrics.items():
        if field == "mean":
            actual = metrics["systems"][system]["p5"]["mean"]
        else:
            actual = metrics["systems"][system]["p5_by_tier"][field]
        if actual != expected:
            raise SystemExit(f"Unexpected {system} {field}: {actual}")
    significance = metrics["sig_p3_vs_p2_p5"]
    if significance["n_queries"] != 24 or significance["mean_diff"] != 0.23:
        raise SystemExit("Paired significance output does not match SupplierBench-24")
    print("expected SupplierBench-24 metrics")

    provenance = json.loads((THESIS / "PROVENANCE.json").read_text())
    for relative, metadata in provenance["files"].items():
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"Missing provenance file: {relative}")
        if sha256(path) != metadata["sha256"]:
            raise SystemExit(f"Checksum mismatch: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise SystemExit(f"Size mismatch: {relative}")
    print("all provenance checksums match")


if __name__ == "__main__":
    main()
