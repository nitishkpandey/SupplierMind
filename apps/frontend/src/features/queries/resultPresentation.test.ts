import assert from "node:assert/strict";
import test from "node:test";

import {
  agentStepsForScope,
  buildResultsCsv,
  zeroResultMessage,
} from "./resultPresentation.ts";
import type { QueryResult, QueryWithResults } from "../../types/index.ts";


test("approved-only progress omits external discovery", () => {
  assert.equal(
    agentStepsForScope("approved_only").some((step) => step.id === "external_discovery"),
    false,
  );
});


test("CSV labels and escapes constraint score", () => {
  const result = {
    rank: 1,
    supplier_id: "supplier-1",
    supplier_name: "Example GmbH",
    total_score: 0.9,
    constraint_score: 0.8,
    explanation: 'A, "quoted" value',
  } as QueryResult;

  const csv = buildResultsCsv([result]);

  assert.match(csv, /Constraint Score/);
  assert.match(csv, /"A, ""quoted"" value"/);
});


test("zero-result message uses backend diagnostic", () => {
  const query = {
    diagnostics: { message: "No verified suppliers satisfied all hard constraints." },
  } as QueryWithResults;

  assert.equal(
    zeroResultMessage(query),
    "No verified suppliers satisfied all hard constraints.",
  );
});
