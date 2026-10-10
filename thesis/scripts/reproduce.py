from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "thesis" / "scripts"
RESULTS = ROOT / "thesis" / "results"
BENCHMARK = ROOT / "thesis" / "benchmark" / "supplierbench24_10k.json"


def _run(script: str, *arguments: str, capture: Path | None = None) -> None:
    command = [sys.executable, str(SCRIPTS / script), *arguments]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        raise SystemExit((completed.stdout or "") + (completed.stderr or ""))
    if capture is not None:
        capture.write_text(completed.stdout)
    elif completed.stdout:
        print(completed.stdout, end="")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    _run(
        "compute_all_metrics.py",
        "--dir",
        str(RESULTS / "main"),
        "--benchmark",
        str(BENCHMARK),
        "--out",
        str(RESULTS / "METRICS.json"),
    )
    _run(
        "compute_extra_metrics.py",
        "--benchmark",
        str(BENCHMARK),
        "--out",
        str(RESULTS / "EXTRA_METRICS.json"),
    )
    _run(
        "analyze_diagnostics.py",
        "--dir",
        str(RESULTS / "main"),
        "--benchmark",
        str(BENCHMARK),
        capture=RESULTS / "DIAGNOSTICS.txt",
    )
    _run(
        "analyze_ablation.py",
        "--benchmark",
        str(BENCHMARK),
        capture=RESULTS / "ABLATION.txt",
    )
    _run("analyze_abstention.py", capture=RESULTS / "ABSTENTION.txt")
    with tempfile.TemporaryDirectory(prefix="suppliermind-matplotlib-") as cache:
        previous = os.environ.get("MPLCONFIGDIR")
        previous_xdg = os.environ.get("XDG_CACHE_HOME")
        previous_backend = os.environ.get("MPLBACKEND")
        os.environ["MPLCONFIGDIR"] = cache
        os.environ["XDG_CACHE_HOME"] = cache
        os.environ["MPLBACKEND"] = "Agg"
        try:
            _run("make_figures.py")
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = previous
            if previous_xdg is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = previous_xdg
            if previous_backend is None:
                os.environ.pop("MPLBACKEND", None)
            else:
                os.environ["MPLBACKEND"] = previous_backend
    _run("verify_reproduction.py")
    print("SupplierBench-24 reproduction verified")


if __name__ == "__main__":
    main()
