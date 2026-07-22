import type { QueryResult, QueryWithResults, SearchScope } from "../../types/index.ts";

export interface AgentStep {
  id: string;
  label: string;
  desc: string;
}

const AGENT_STEPS: AgentStep[] = [
  { id: "parser", label: "Parser Agent", desc: "Extracting constraints" },
  { id: "external_discovery", label: "External Discovery", desc: "Searching the web for new suppliers" },
  { id: "discovery", label: "Internal Search", desc: "Matching from database" },
  { id: "compliance", label: "Compliance Agent", desc: "Validating suppliers" },
  { id: "ranking", label: "Ranking Agent", desc: "Scoring results" },
];

export function agentStepsForScope(scope: SearchScope = "approved_only"): AgentStep[] {
  return scope === "both"
    ? AGENT_STEPS
    : AGENT_STEPS.filter((step) => step.id !== "external_discovery");
}

function csvCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function buildResultsCsv(results: QueryResult[]): string {
  const rows: unknown[][] = [
    ["Rank", "Supplier ID", "Supplier Name", "Total Score", "Constraint Score", "Explanation"],
    ...results.map((result) => [
      result.rank,
      result.supplier_id,
      result.supplier_name,
      result.total_score.toFixed(3),
      result.constraint_score.toFixed(3),
      result.explanation,
    ]),
  ];
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

export function zeroResultMessage(query: QueryWithResults): string {
  return query.diagnostics?.message
    || query.error_message
    || "No verified suppliers matched every requested constraint.";
}
