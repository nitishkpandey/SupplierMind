import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { AuditEntry } from "@/types";
import { ListTree } from "lucide-react";

const AGENT_ORDER = [
  "parser",
  "clarification_handler",
  "external_discovery",
  "discovery",
  "compliance",
  "ranking",
  "evaluator",
  "memory_service",
  "orchestrator",
];

const AGENT_LABELS: Record<string, string> = {
  parser: "Parser",
  clarification_handler: "Clarification",
  external_discovery: "External Discovery",
  discovery: "Internal Search",
  compliance: "Compliance",
  ranking: "Ranking",
  evaluator: "Evaluator",
  memory_service: "Memory",
  orchestrator: "Orchestrator",
};

const AGENT_COLORS: Record<string, string> = {
  parser: "bg-blue-100 text-blue-800 border-blue-200",
  clarification_handler: "bg-yellow-100 text-yellow-800 border-yellow-200",
  external_discovery: "bg-cyan-100 text-cyan-800 border-cyan-200",
  discovery: "bg-purple-100 text-purple-800 border-purple-200",
  compliance: "bg-orange-100 text-orange-800 border-orange-200",
  ranking: "bg-green-100 text-green-800 border-green-200",
  evaluator: "bg-teal-100 text-teal-800 border-teal-200",
  memory_service: "bg-zinc-100 text-zinc-800 border-zinc-200",
  orchestrator: "bg-slate-100 text-slate-800 border-slate-200",
};

interface AuditTrailProps {
  entries: AuditEntry[];
}

export function AuditTrail({ entries }: AuditTrailProps) {
  const { t } = useTranslation();
  const orderedEntries = entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => {
      const ao = AGENT_ORDER.indexOf(a.entry.agent_name);
      const bo = AGENT_ORDER.indexOf(b.entry.agent_name);
      const ai = ao === -1 ? AGENT_ORDER.length : ao;
      const bi = bo === -1 ? AGENT_ORDER.length : bo;
      return ai - bi || a.index - b.index;
    });

  if (!entries.length) {
    return (
      <Card>
        <CardContent className="py-6 text-center text-muted-foreground text-sm">
          No audit log entries found.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ListTree className="w-4 h-4" />
          {t("audit.title")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="relative space-y-0">
          {orderedEntries.map(({ entry }, i) => {
            const inputSummary = entry.input_snapshot?.summary != null
              ? String(entry.input_snapshot.summary)
              : "";
            const outputSummary = entry.output_snapshot?.summary != null
              ? String(entry.output_snapshot.summary)
              : "";
            return (
            <div key={`${entry.agent_name}-${entry.action}-${i}`} className="flex gap-4 pb-4">
              {/* Timeline line */}
              <div className="flex flex-col items-center">
                <div className="w-7 h-7 rounded-full bg-background border border-border text-xs font-semibold flex items-center justify-center flex-shrink-0">
                  {i + 1}
                </div>
                {i < orderedEntries.length - 1 && (
                  <div className="w-px flex-1 bg-border mt-1" />
                )}
              </div>

              {/* Content */}
              <div className="flex-1 pb-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge
                    variant="outline"
                    className={`text-xs ${AGENT_COLORS[entry.agent_name] ?? "bg-muted"}`}
                  >
                    {AGENT_LABELS[entry.agent_name] ?? entry.agent_name}
                  </Badge>
                  <span className="text-xs font-medium">{entry.action}</span>
                  {entry.duration_ms != null && (
                    <span className="text-xs text-muted-foreground ml-auto">
                      {entry.duration_ms}ms
                    </span>
                  )}
                </div>

                {(inputSummary || outputSummary) && (
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    {inputSummary && (
                      <div className="rounded-md border border-border/60 bg-muted/30 p-2">
                        <p className="text-[11px] font-semibold uppercase tracking-normal text-muted-foreground">
                          Input
                        </p>
                        <p className="text-xs text-foreground mt-0.5">{String(inputSummary)}</p>
                      </div>
                    )}
                    {outputSummary && (
                      <div className="rounded-md border border-border/60 bg-muted/30 p-2">
                        <p className="text-[11px] font-semibold uppercase tracking-normal text-muted-foreground">
                          Output
                        </p>
                        <p className="text-xs text-foreground mt-0.5">{String(outputSummary)}</p>
                      </div>
                    )}
                  </div>
                )}

                {entry.reasoning && (
                  <div className="mt-2 p-2 bg-muted/50 rounded text-xs leading-relaxed border-l-2 border-primary/30">
                    <span className="font-medium text-primary">Reasoning </span>
                    {entry.reasoning}
                  </div>
                )}
              </div>
            </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
