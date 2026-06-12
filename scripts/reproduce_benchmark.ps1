# Reproduce the SupplierBench-25 three-paradigm benchmark from a clean checkout.
# Prerequisites: Docker Desktop running, Python 3.11 + uv installed,
# API keys in backend/.env (GROQ_API_KEY, VOYAGE_API_KEY; OPENAI_API_KEY +
# LLM_PROVIDER=openai for the canonical GPT-4o-mini run).
#
# Usage (from the repository root):
#     ./scripts/reproduce_benchmark.ps1
#
# Outputs land in backend/data/evaluation_results.json and
# backend/data/thesis_report.json; archive them under results/run_YYYYMMDD/.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "[1/6] Starting infrastructure (Postgres, Milvus, Redis)..."
Set-Location $root
docker compose up -d
Start-Sleep -Seconds 25

Write-Host "[2/6] Syncing pinned Python dependencies..."
Set-Location "$root\backend"
uv sync

Write-Host "[3/6] Applying database schema..."
uv run alembic upgrade head

Write-Host "[4/6] Generating the synthetic corpus + benchmark queries (seed 42)..."
uv run python data/generate_dataset.py

Write-Host "[5/6] Embedding + indexing suppliers into Milvus..."
uv run python scripts/ingest_suppliers.py

Write-Host "[6/6] Running the three-paradigm benchmark (this is the long part)..."
uv run python scripts/run_evaluation.py --paradigms

$stamp = Get-Date -Format "yyyyMMdd"
$dest = "$root\results\run_$stamp"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item "$root\backend\data\evaluation_results.json" $dest -Force
if (Test-Path "$root\backend\data\thesis_report.json") {
    Copy-Item "$root\backend\data\thesis_report.json" $dest -Force
}
Write-Host "Done. Results archived to $dest"
