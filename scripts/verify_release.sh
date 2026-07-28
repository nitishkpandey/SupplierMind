#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"
FRONTEND_DIR="${REPO_ROOT}/apps/frontend"
UV_CACHE_DIR="${TMPDIR:-/tmp}/suppliermind-uv-cache"
export UV_CACHE_DIR

PROTECTED_PATHS=(
  "apps/backend/data/queries_benchmark.json"
  "apps/backend/data/suppliers_synthetic.json"
  "apps/backend/data/suppliers_synthetic_10k.json"
  "apps/backend/data/generate_dataset.py"
  "apps/backend/data/thesis_report.json"
  "results"
)

usage() {
  echo "Usage: $0 [--live]"
}

LIVE=false
if [[ "${1:-}" == "--live" ]]; then
  LIVE=true
  shift
fi
if [[ "$#" -ne 0 ]]; then
  usage >&2
  exit 2
fi

cd "${REPO_ROOT}"
THESIS_BEFORE="$(git rev-parse thesis-experiments)"

if [[ -n "$(git status --porcelain -- "${PROTECTED_PATHS[@]}")" ]]; then
  echo "Protected benchmark or thesis-result paths have working-tree changes." >&2
  git status --short -- "${PROTECTED_PATHS[@]}" >&2
  exit 1
fi

mkdir -p "${UV_CACHE_DIR}"

echo "Running backend tests and static checks..."
cd "${BACKEND_DIR}"
uv run --no-sync pytest
uv run --no-sync ruff check app tests scripts
uv run --no-sync mypy app

echo "Running frontend tests, lint, build, and bundle checks..."
cd "${FRONTEND_DIR}"
npm test
npm run lint
npm run build
npm run check:bundle

cd "${REPO_ROOT}"
git diff --check

if [[ "${LIVE}" == true ]]; then
  echo "Running live clarification and discovery verification..."
  cd "${BACKEND_DIR}"
  uv run --no-sync python scripts/verify_live_discovery.py
  cd "${REPO_ROOT}"
fi

THESIS_AFTER="$(git rev-parse thesis-experiments)"
if [[ "${THESIS_BEFORE}" != "${THESIS_AFTER}" ]]; then
  echo "The thesis-experiments branch moved during verification." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain -- "${PROTECTED_PATHS[@]}")" ]]; then
  echo "Verification modified protected benchmark or thesis-result paths." >&2
  git status --short -- "${PROTECTED_PATHS[@]}" >&2
  exit 1
fi

echo "Release verification passed."
