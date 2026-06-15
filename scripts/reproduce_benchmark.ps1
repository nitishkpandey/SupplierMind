# Reproduce the SupplierBench-25 three-paradigm benchmark from a clean checkout.
# Prerequisites: Docker Desktop running, Python 3.11 + uv installed,
# API keys in apps/backend/.env (VOYAGE_API_KEY for embeddings; OPENAI_API_KEY +
# LLM_PROVIDER=openai for the canonical GPT-4o-mini run).
#
# Usage (from the repository root):
#     ./scripts/reproduce_benchmark.ps1                    # full run, regenerates the corpus (seed 42)
#     ./scripts/reproduce_benchmark.ps1 -UseExistingCorpus # run on the committed corpus (no regeneration)
#
# Outputs land in apps/backend/data/evaluation_results.json and
# apps/backend/data/thesis_report.json; archived under results/run_YYYYMMDD/.

param([switch]$UseExistingCorpus)

$ErrorActionPreference = "Stop"

# Force UTF-8 so emoji / diagnostic prints don't crash under a redirected cp1252
# console on Windows (UnicodeEncodeError). Corpus files are written with explicit
# utf-8 regardless, so this only affects console output, not data.
$env:PYTHONUTF8 = "1"

$root = Split-Path -Parent $PSScriptRoot

# $ErrorActionPreference = "Stop" does NOT catch a native command's non-zero exit
# code, so a crashed `uv run ...` step would otherwise be ignored and the script
# would carry on against stale data and still report success. Gate every native
# step on its exit code explicitly.
function Invoke-Step([string]$label, [scriptblock]$cmd) {
    Write-Host $label
    & $cmd
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed (exit $LASTEXITCODE): $label"
    }
}

Write-Host "[1/6] Starting infrastructure (Postgres, Milvus, Redis)..."
Set-Location $root
docker compose -f infra/docker/docker-compose.yml up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed (exit $LASTEXITCODE)" }
Start-Sleep -Seconds 25

Set-Location "$root\apps\backend"
Invoke-Step "[2/6] Syncing pinned Python dependencies..." { uv sync }
Invoke-Step "[3/6] Applying database schema..." { uv run alembic upgrade head }

if ($UseExistingCorpus) {
    Write-Host "[4/6] Using the committed corpus (regeneration skipped: -UseExistingCorpus)."
} else {
    Invoke-Step "[4/6] Generating the synthetic corpus + benchmark queries (seed 42)..." {
        uv run python data/generate_dataset.py
    }
}

Invoke-Step "[5/6] Embedding + indexing suppliers into Milvus..." {
    uv run python scripts/ingest_suppliers.py
}
Invoke-Step "[6/6] Running the three-paradigm benchmark (this is the long part)..." {
    uv run python scripts/run_evaluation.py --paradigms
}

$stamp = Get-Date -Format "yyyyMMdd"
$dest = "$root\results\run_$stamp"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item "$root\apps\backend\data\evaluation_results.json" $dest -Force
if (Test-Path "$root\apps\backend\data\thesis_report.json") {
    Copy-Item "$root\apps\backend\data\thesis_report.json" $dest -Force
}
Write-Host "Done. Results archived to $dest"
