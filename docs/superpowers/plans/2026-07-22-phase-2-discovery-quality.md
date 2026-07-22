# Phase 2 Discovery Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep buyer order quantities out of the supplier-capacity tool path and generate compact, distinct supplier-search queries from overlapping parser terms.

**Architecture:** Make quantity-tool availability deterministic from the original query: the Parser hides and refuses `parse_quantity_unit` unless the query contains an explicit capacity/rate signal, while existing normalization remains the final defense against bad capacity fields. Keep Tavily construction pure by compacting product phrases before building separate manufacturer, distributor/wholesaler, certification, and country-domain families; pass industry context explicitly from external discovery and preserve the global result cap after all families run.

**Tech Stack:** Python 3.11, ReAct parser/tool registry, Tavily HTTP search service, pytest, Ruff, mypy.

## Global Constraints

- Work only in `/Users/nitishkumarpandey/Desktop/SupplierMind` on `production/agentic-suppliermind`.
- Keep Phase 2 in commits separate from Phase 1; do not merge to `main`.
- The behavior must be generic across products, industries, countries, and languages; do not hard-code beer, breweries, Helles, Pilsner, Germany, or benchmark query text.
- Buyer order quantities and package sizes are demand context, not supplier capacity.
- Explicit capacity/rate phrases such as `capacity`, `throughput`, and per-period units must continue to populate `capacity_min` and `capacity_unit`.
- Do not add a buyer-order quantity schema, localized query vocabulary, demo seed data, or relax compliance/location validation.
- All Tavily query families must execute before the final global result cap is applied.

---

### Task 1: Enforce capacity-only quantity tool use

**Files:**
- Modify: `apps/backend/app/agents/tools/registry.py`
- Modify: `apps/backend/app/agents/tools/quantity_parser.py`
- Modify: `apps/backend/app/agents/parser_agent.py`
- Test: `apps/backend/tests/unit/test_parser_react.py`
- Test: `apps/backend/tests/unit/test_tools.py`

**Interfaces:**
- Consumes: `_raw_query_states_capacity(raw_query) -> bool` and the registered `parse_quantity_unit` tool.
- Produces: `ToolRegistry.list_for_prompt(*, exclude_names: Collection[str] = ()) -> str`; `_build_system_prompt(..., allow_quantity_tool: bool) -> str`; a deterministic `quantity_tool_not_applicable` observation for hallucinated order-quantity calls.

- [ ] **Step 1: Write failing tests for buyer-order and explicit-capacity paths**

Add a counting `parse_quantity_unit` tool to `test_parser_react.py`. For `buy 1000 bottles of sparkling water`, script the LLM to request `parse_quantity_unit` and then finish. Assert the tool callable was never invoked, the first trace observation has `error == "quantity_tool_not_applicable"`, and the system prompt does not advertise `- parse_quantity_unit:`. For `supplier capacity of 10k bottles/month`, assert the prompt advertises the tool, the callable receives `10k bottles/month`, and normalized constraints retain `10000` plus `bottles/month`.

Add a registry unit test that `list_for_prompt(exclude_names={"parse_quantity_unit"})` omits only that tool while retaining the other registered tools. Update the quantity tool description test to require capacity-only wording and reject lead-time/order wording.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd apps/backend
.venv/bin/pytest tests/unit/test_parser_react.py tests/unit/test_tools.py -q
```

Expected: the new registry signature is rejected and the order-quantity callable is invoked because no deterministic guard exists.

- [ ] **Step 3: Implement the minimal capacity-only prompt and dispatch guard**

Update `ToolRegistry.list_for_prompt` to accept an optional excluded-name collection. Change the quantity tool description to say it is only for explicit supplier capacity/throughput/rate phrases and never for buyer order quantity, package size, or lead time.

In `ParserAgent.execute`, compute `allow_quantity_tool = _raw_query_states_capacity(raw_query)`, omit `parse_quantity_unit` from the rendered tool list when false, and intercept any hallucinated `parse_quantity_unit` action before tool dispatch with:

```python
{
    "error": "quantity_tool_not_applicable",
    "detail": (
        "The query has no explicit supplier capacity or rate requirement. "
        "Treat purchase quantities and package sizes as demand context and finish."
    ),
}
```

Do not call the tool or increment its execution budget in that branch. Keep `_clear_non_capacity_quantity` unchanged as defense in depth.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all parser and tool tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add apps/backend/app/agents/parser_agent.py apps/backend/app/agents/tools/registry.py apps/backend/app/agents/tools/quantity_parser.py apps/backend/tests/unit/test_parser_react.py apps/backend/tests/unit/test_tools.py
git commit -m "fix: reserve quantity parsing for supplier capacity"
```

---

### Task 2: Build compact and distinct Tavily query families

**Files:**
- Modify: `apps/backend/app/services/web_search.py`
- Modify: `apps/backend/app/agents/external_discovery_agent.py`
- Test: `apps/backend/tests/unit/test_production_quality_regressions.py`

**Interfaces:**
- Consumes: ordered product terms where `product_type` is first, parsed `industry_context`, category, country/city, and explicit certifications.
- Produces: `WebSearchService._compact_product_terms(values, max_terms=3) -> list[str]`; `search_suppliers(..., industry_context: str | None = None, ...)`; compact query families with no concatenated keyword soup.

- [ ] **Step 1: Write failing pure-query and wiring tests**

Add tests proving:

- `['beer', 'beer', 'bottled beer', 'Helles', 'Pilsner', 'German beer']` compacts to `['beer', 'Helles', 'Pilsner']` by exact deduplication and containment removal, without any product-specific rule;
- office-furniture queries never concatenate `office furniture`, `furniture`, `desk`, and `chair` into one product phrase;
- every built query contains the requested city and country;
- at least one query includes `hospitality beverages` when supplied as industry context;
- manufacturer and distributor/wholesaler families are distinct;
- certification families still run even when `max_results` is smaller than the number of query families; and
- `ExternalDiscoveryAgent.execute` forwards `parsed_constraints['industry_context']` into `search_suppliers`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd apps/backend
.venv/bin/pytest tests/unit/test_production_quality_regressions.py -q
```

Expected: compact-term helper and industry-context argument do not exist, and current queries contain overlapping product terms.

- [ ] **Step 3: Implement compact term selection and query families**

Implement `_compact_product_terms` as a pure ordered selector: normalize whitespace, remove exact duplicates, retain the first term as the primary product, drop later terms whose token set contains or is contained by an already selected term, and keep at most three distinct phrases.

Build each query from one product phrase rather than joining all phrases. Use compact families in this order when inputs permit:

1. country-domain supplier query;
2. primary-product manufacturer query;
3. distinctive-variant distributor/wholesaler query;
4. certification query; and
5. category/industry fallback query.

Each family includes the full city/country location. Industry context is a separate compact phrase, not another list of keywords. Preserve URL deduplication, per-query result limits, execution of all families, score sorting, and the final `all_results[:target_results]` cap.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all production-quality regressions pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add apps/backend/app/services/web_search.py apps/backend/app/agents/external_discovery_agent.py apps/backend/tests/unit/test_production_quality_regressions.py
git commit -m "fix: compact external supplier search queries"
```

---

### Task 3: Verify Phase 2 and republish the presentation branch

**Files:**
- No production changes expected.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: a verified, pushed `production/agentic-suppliermind` branch and updated draft PR.

- [ ] **Step 1: Run backend verification**

```bash
cd apps/backend
.venv/bin/pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app
```

Expected: full suite passes; Ruff and mypy report no errors.

- [ ] **Step 2: Run the live regression**

Submit the original procurement request, answer `Munich`, and confirm the resumed parser no longer executes `parse_quantity_unit`; confirm compact Tavily queries enter external discovery. Repeat or inspect the already-green `all of Germany` path without weakening country validation.

- [ ] **Step 3: Push and update the draft PR**

```bash
git push origin production/agentic-suppliermind
```

Keep the PR draft and do not merge.
