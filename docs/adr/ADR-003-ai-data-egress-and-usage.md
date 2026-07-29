# ADR-003: Govern AI data egress and persist content-free usage

**Status:** Accepted (2026-07-29)

## Context

SupplierMind sends text to OpenAI for agent reasoning and to Voyage AI for
embeddings. Direct provider calls made it possible to omit the business purpose,
send data without an explicit classification, exceed a query's intended cost,
or record incomplete operational evidence. Process-local cost counters also
disappeared on restart and could not support a multi-process production
deployment.

SupplierMind needs one enforceable boundary for model and embedding calls,
fail-closed behavior for unclassified data, and durable observability that does
not create a second store of prompts or model responses.

## Decision

All text and embedding access passes through a policy gateway. Provider
transports remain below the gateway: `OpenAIProvider` implements the text
transport and `EmbeddingClient` implements the Voyage transport. Agents,
evaluation code, ingestion scripts, and smoke checks receive a gateway rather
than constructing a transport.

Every call is associated with an `AIRequestContext` containing:

- a business `purpose` and `classification`;
- explicit `redaction_applied` and `excerpted` state;
- per-call token and cost limits plus a shared per-query budget ledger;
- the applicable query, user, job, source-document, and correlation
  identifiers. Identifiers that do not exist for a service operation remain
  null; a correlation identifier is still required for operational checks.

An unbound call receives the `restricted` fallback classification and is denied.
Unknown providers are denied. The default external allow list is
`public,internal`, configured by `AI_EXTERNAL_ALLOWED_CLASSIFICATIONS`.
`confidential` data may not be enabled for external processing without
documented Security and Legal approval, including provider terms and the
specific data flow. `restricted` data remains outside the external-provider
path.

The classifications are:

| Classification | Meaning |
|---|---|
| `public` | Information already public or intentionally approved for public disclosure. |
| `internal` | Ordinary Mercanis procurement queries and supplier metadata approved for the configured processors; no credentials, secrets, or restricted records. |
| `confidential` | Customer-confidential documents, contracts, commercial terms, or personal data requiring an approved processing basis and tighter controls. |
| `restricted` | Credentials, authentication material, regulated/high-impact data, or any unclassified context. External egress is denied. |

The configurable defaults are:

- `AI_MAX_CALL_TOKENS=32000` for text and embedding input enforcement;
- `AI_MAX_CALL_COST_USD=0.10` for a text call;
- `AI_MAX_QUERY_COST_USD=0.50` across a query, including resumed turns.

Text calls reserve estimated cost before transport invocation and settle the
reservation to actual reported cost. A resumed query seeds its ledger from
known cost already persisted for that query. Calls that would cross a token,
per-call cost, or per-query cost limit fail before the transport is invoked and
produce a `budget_exceeded` event. Voyage usage reports input units but this
integration has no authoritative price calculation, so embedding `cost_usd`
remains null. Unknown cost must be visible; it must never be silently converted
to zero.

Each policy decision or provider attempt writes an `ai_usage_events` row in
PostgreSQL. This table is the operational source of truth for call counts,
known cost, unknown-cost coverage, denials, failures, latency, provider/model,
purpose, classification, and correlation. It must never store prompts,
responses, source excerpts, document bodies, or credentials. The admin metrics
API and dashboard aggregate only this content-free record.

CI uses deterministic fake transports and asserts that policy and budget
denials never invoke them. Credentialed provider connectivity remains a
separate, explicit live check.

## Consequences

- External AI egress is fail-closed and consistently classified.
- Query budgets remain effective across concurrent calls and pause/resume
  boundaries.
- Usage survives process restarts and can be aggregated across workers.
- Operators can distinguish measured spend from calls with unknown cost.
- A usage-persistence error is logged without content, but it does not discard
  a successful provider response. Operators must treat that error as an
  observability incident.
- Adding a provider requires a transport, a policy allow-list decision, usage
  reporting, boundary tests, and Security/Legal review where applicable.
- This ADR refines ADR-002: OpenAI remains the only text provider, but it is now
  always reached through `AIGateway`, not returned as a bare transport.

## Alternatives considered

- **Rely on call-site discipline.** Rejected because a new script or agent could
  bypass classification, budgets, or usage reporting.
- **Log prompts and responses for debugging.** Rejected because operational
  telemetry would become a high-risk duplicate content store.
- **Treat unknown embedding cost as zero.** Rejected because it understates
  spend and makes the dashboard misleading.
- **Use only process-local counters.** Rejected because they reset on restart
  and cannot represent multiple application workers.
