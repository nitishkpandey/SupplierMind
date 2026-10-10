from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
THESIS = ROOT / "thesis"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_paths() -> list[Path]:
    paths = [ROOT / "apps" / "backend" / "data" / "suppliers_synthetic_10k.json"]
    paths.extend(sorted((THESIS / "benchmark").glob("*.json")))
    paths.append(THESIS / "EXCLUSION.json")
    for directory in ("main", "ablation", "abstention"):
        paths.extend(sorted((THESIS / "results" / directory).glob("run_*.json")))
    for name in (
        "METRICS.json",
        "EXTRA_METRICS.json",
        "DIAGNOSTICS.txt",
        "ABLATION.txt",
        "ABSTENTION.txt",
    ):
        paths.append(THESIS / "results" / name)
    paths.extend(sorted((THESIS / "scripts").glob("*.py")))
    return paths


def main() -> None:
    files = {}
    for path in manifest_paths():
        if not path.is_file():
            raise SystemExit(f"Missing provenance input: {path.relative_to(ROOT)}")
        files[path.relative_to(ROOT).as_posix()] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }

    provenance = {
        "schema_version": 1,
        "study": "SupplierBench-24 on the 10,000-supplier synthetic corpus",
        "analysis_type": "Post hoc removal of one exact duplicate query followed by offline recomputation",
        "source_repository_commit": "9820863add00c82515d53b3537a562a707123913",
        "production_base_commit": "d7db1d39f29539fda3190b93dd3456147dc6fd77",
        "excluded_query_id": "49554c47-ef51-554a-8404-be6b6761b6ca",
        "duplicate_of_query_id": "56c444e6-f04e-5334-a964-dfb03810507a",
        "model_identifiers": {
            "language_model": "gpt-4o-mini-2024-07-18",
            "embedding_model": "voyage-3-lite",
        },
        "archive_counts": {
            "main_runs": 5,
            "ablation_runs": 3,
            "abstention_runs": 1,
        },
        "files": files,
    }
    (THESIS / "PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n"
    )


if __name__ == "__main__":
    main()
