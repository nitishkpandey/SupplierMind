# Appendices

These appendices contain material that supports the dissertation but is not
essential to the main argument: the full benchmark query sets, extended diagnostic
results, the reproducibility details, and selected implementation specifics. All
data is taken directly from the released artefacts in the project repository.

## Appendix A — The SupplierBench-25 query set

Table A.1 lists the twenty-five benchmark queries in full, with their difficulty
tier and the number of suppliers in the ground-truth set (the count of corpus
suppliers that satisfy all of the query's constraints). The queries are grouped into
eight simple (one to two constraints), ten medium (three to four), and seven hard
(five to six) queries, and every query is verified to have at least three
ground-truth matches so that no metric is zero by construction.

| # | Tier | Ground truth | Query |
|---|---|---|---|
| 1 | simple | 106 | metals suppliers in Germany |
| 2 | simple | 507 | ISO 9001 certified electronics suppliers |
| 3 | simple | 29 | logistics suppliers in Germany |
| 4 | simple | 25 | software services suppliers in Germany |
| 5 | simple | 295 | ISO 14001 certified textiles suppliers |
| 6 | simple | 252 | REACH certified chemicals suppliers |
| 7 | simple | 81 | packaging suppliers in Germany |
| 8 | simple | 101 | ISO 22000 certified food ingredients suppliers |
| 9 | medium | 6 | ISO 9001 certified metals suppliers in Germany with capacity over 10,000 kg/month |
| 10 | medium | 4 | ISO 9001 certified electronics suppliers in Germany, lead time under 14 days |
| 11 | medium | 8 | logistics suppliers in Germany with capacity over 50,000 tonnes/month |
| 12 | medium | 13 | ISO 27001 certified software services suppliers in Germany |
| 13 | medium | 6 | REACH certified chemicals suppliers in Germany with capacity over 100,000 kg/month |
| 14 | medium | 6 | packaging suppliers in Germany with capacity over 100,000 units/month |
| 15 | medium | 5 | CE certified machinery suppliers in Germany, lead time under 14 days |
| 16 | medium | 35 | ISO 9001 certified textiles suppliers in Germany |
| 17 | medium | 8 | ISO 22000 certified food ingredients suppliers with capacity over 200,000 tonnes/month |
| 18 | medium | 8 | CE certified construction materials suppliers in Germany with capacity over 20,000 tonnes/month |
| 19 | hard | 5 | ISO 9001 certified metals suppliers in Germany with capacity over 50,000 kg/month |
| 20 | hard | 5 | ISO 9001 certified electronics suppliers in Germany with capacity over 100,000 units/month, lead time under 60 days |
| 21 | hard | 4 | ISO 27001 certified software services suppliers in Germany, lead time under 21 days |
| 22 | hard | 6 | REACH certified chemicals suppliers in Germany with capacity over 100,000 kg/month |
| 23 | hard | 5 | ISO 9001 certified packaging suppliers in Germany with capacity over 5,000 units/month, lead time under 30 days |
| 24 | hard | 5 | ISO 9001 certified textiles suppliers in Germany with capacity over 100,000 meters/month |
| 25 | hard | 5 | food ingredients suppliers in Germany with capacity over 100,000 tonnes/month, lead time under 45 days |

*Table A.1 — The SupplierBench-25 query set.*

## Appendix B — The Abstention-5 query set

Table B.1 lists the five abstention queries, each of which has no satisfying
supplier in the corpus by construction and is used to test whether a system
correctly returns nothing rather than inventing a match. Each is unsatisfiable for a
different reason — an incompatible certification for the category, a certificate
combination that no supplier holds, a country with no such supplier, or an
impossible capacity threshold.

| # | Query | Why it is unsatisfiable |
|---|---|---|
| A1 | AS9100 aerospace-certified logistics providers in Germany | aerospace certification does not apply to logistics providers |
| A2 | ISO 27001 and IATF 16949 automotive-certified software services in Germany | no software supplier holds both certificates |
| A3 | IATF 16949 automotive-certified food ingredient suppliers in Germany | automotive certification does not apply to food suppliers |
| A4 | ISO 9001 metal suppliers in Germany with capacity over 999,999,999 kg/month | impossible capacity threshold |
| A5 | ISO 14001 certified textile suppliers in Iceland | no textile supplier is located in Iceland |

*Table B.1 — The Abstention-5 query set.*

## Appendix C — Extended results and diagnostics

This appendix collects supporting numbers referenced in Chapter 5. All values are
means over five instrumented runs of the full benchmark (three runs for the
ablation), computed by the analysis scripts in the repository.

**Run-to-run variance.** The agentic system is mildly stochastic because its parser
runs at a non-zero temperature; the retrieval baseline is deterministic. Table C.1
reports the standard deviation of the headline metrics across the five runs, which
confirms that the reported differences are not artefacts of a single run.

| Metric | P3 mean (SD across runs) | P2 mean (SD across runs) |
|---|---|---|
| Precision@5 | 0.731 (0.031) | 0.504 (0.000) |
| MRR | 0.984 (0.022) | 0.793 (0.000) |
| CSR (native) | 0.954 (0.006) | 0.877 (0.002) |
| Answer rate | 0.984 (0.022) | 1.000 (0.000) |

*Table C.1 — Run-to-run variance of the headline metrics.*

**Parser error taxonomy.** Pooled over the 125 query-runs, the failure categories
(which may overlap) occur as shown in Table C.2. The common issue is cosmetic,
because retrieval filters on the structured constraints rather than the affected
free-text field; the genuinely harmful failures are rare.

| Failure category | Count | Share |
|---|---|---|
| Polluted product string (stray unit words in a free-text field) | 21 | 16.8% |
| Parse failure / maximum iterations reached | 4 | 3.2% |
| Clean parse but zero precision | 2 | 1.6% |
| Missed a constraint | 1 | 0.8% |

*Table C.2 — Parser error taxonomy (125 query-runs).*

**Tool usage.** Table C.3 reports how often each parser tool was called and the mean
Precision@5 on the queries where it fired, over the 125 query-runs (mean 3.1 tool
calls per query).

| Tool | Used in (of 125) | Mean P@5 when used |
|---|---|---|
| infer_industry_context | 111 | 0.753 |
| geocode_location | 103 | 0.713 |
| parse_quantity_unit | 75 | 0.600 |
| canonicalize_certification | 73 | 0.668 |
| lookup_past_query | 2 | 1.000 |

*Table C.3 — Parser tool usage.*

## Appendix D — Reproducibility

Every reported number can be regenerated from the public repository at
<https://github.com/nitishkpandey/SupplierMind>. The steps below outline the process;
the deterministic analyses require no API keys, while running the paradigms requires
the infrastructure services and provider keys.

The free, deterministic analyses (no API keys, no cost) rebuild and verify the
benchmark and recompute the metrics from the archived run outputs:

```bash
python thesis/scripts/build_benchmark_10k.py     # build and verify the benchmark
python thesis/scripts/compute_all_metrics.py     # headline metrics, CIs, significance test
python thesis/scripts/analyze_diagnostics.py     # intent resolution, error taxonomy, tools, latency
python thesis/scripts/analyze_ablation.py        # the component-ablation ladder
python thesis/scripts/analyze_abstention.py      # abstention scoring
```

Running the paradigms (requires Docker and provider keys) executes the full
benchmark five times, then the ablation, then the abstention set:

```bash
docker compose -f infra/docker/docker-compose.yml up -d
cd apps/backend
uv run python ../../thesis/scripts/run_10k_benchmark.py --p1 --p2 --p3 --runs 5
uv run python ../../thesis/scripts/run_10k_benchmark.py --p3 --ablation no_compliance --runs 3
uv run python ../../thesis/scripts/run_10k_benchmark.py --p1 --p2 --p3 --abstention
```

Reproducibility rests on three properties: the corpus is generated from a fixed
random seed (`random.seed(42)`), the language model is pinned to a dated snapshot,
and the benchmark queries and their ground truth are stored in versioned files. The
embedding provider's free-tier rate limit is respected by a proactive rate limiter,
which makes long runs slow but stable without a paid plan.

> **📷 Figure D.1 — [screenshot placeholder]**
> **Attach:** the GitHub repository landing page, showing the project structure and
> the `thesis/` folder with the scripts and released artefacts.
> **Relevance:** provides a visual anchor for the reproducibility claim and the
> public availability of the code and data.
> **Priority:** Optional.

## Appendix E — Selected implementation specifics

**Parser tool registry.** The parser draws on five tools: `geocode_location`
(place name to coordinates, via Nominatim/OpenStreetMap), `canonicalize_certification`
(mapping certificate strings to a canonical form via a taxonomy),
`infer_industry_context` (a small model call inferring a category from vague
wording), `parse_quantity_unit` (a deterministic regular-expression parser for a
capacity value and unit), and `lookup_past_query` (a per-user semantic-memory
lookup). The loop runs for at most six iterations with a per-tool execution budget
of two.

**Compliance thresholds.** The quote-or-fail rule uses a minimum quote length of
twelve characters (below which a quote is too generic to verify) and a confidence
floor of 0.75 (below which a PASS is treated as hedging and downgraded to PARTIAL).
Certificate equivalences resolved deterministically through the taxonomy are
assigned a confidence of 0.95, and only genuinely ambiguous equivalences trigger a
language-model call.

**Ranking weights.** The default ranking weights are 0.40 for constraint
satisfaction, 0.25 for semantic similarity, 0.25 for proximity, and 0.10 for data
completeness, with a preference term added when the query expresses one. For a
compliance-critical query the constraint weight rises to 0.50, and for a
location-driven query the proximity weight rises to 0.40; a supplier carrying a
high-confidence FAIL is additionally multiplied by a penalty factor.

**Model and infrastructure.** The language model is OpenAI `gpt-4o-mini-2024-07-18`
(temperature 0.0 for extraction and compliance, 0.2 in the parser loop); embeddings
are Voyage `voyage-3-lite` at 512 dimensions; vectors are indexed in Milvus 2.4 with
HNSW (M = 16, efConstruction = 256, ef = 128) under cosine similarity; and supplier
data, constraints, and audit logs are stored in PostgreSQL 16 with PostGIS.
