# Contributing

Research artefact for a master's thesis; light process, strict hygiene.

## Code style

- Python 3.11, type hints throughout, British spelling in prose and comments,
  no em-dashes in text that may be cited.
- Frontend: TypeScript strict, Tailwind utility classes, components under
  `apps/frontend/src/features/`.
- Comments explain constraints the code cannot show — not what the next line does.

## Tests

```bash
cd apps/backend
uv run pytest tests/unit -q        # deterministic; no live LLM/API needed
```

- TDD where practical: failing test first, then the fix.
- The LLM is the one external boundary that may be stubbed (`_FakeLLM`
  pattern in the test suite). Milvus-backed tests use disposable
  per-test collections.
- Frontend type-check: `cd apps/frontend && npx tsc --noEmit`.

## Commits

Conventional prefixes: `feat:`, `fix:`, `test:`, `bench:`, `docs:`, `chore:`.
Atomic commits at each working state. Milestone tags:
`groq-baseline-v0`, `provider-migration-complete`, `baselines-built`,
`benchmark-final-v1`, `repro-ready`.

## Benchmark discipline

Locked results are never overwritten — archive under `results/run_YYYYMMDD/`.
Negative results are reported unchanged.
