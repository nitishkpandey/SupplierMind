import { useState, useMemo } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { queryService } from "@/services/api";
import { useSSE } from "@/hooks/useSSE";
import { SupplierCard } from "@/features/suppliers/SupplierCard";
import { SupplierMap } from "@/features/suppliers/SupplierMap";
import { AuditTrail } from "@/features/queries/AuditTrail";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Map, ListTree, Download, AlertCircle, Brain } from "lucide-react";
import type { QueryWithResults } from "@/types";

// Agent step display config
const AGENT_STEPS = [
  { id: "parser", label: "Parser Agent", desc: "Extracting constraints" },
  { id: "external_discovery", label: "External Discovery", desc: "Searching the web for new suppliers" },
  { id: "discovery", label: "Internal Search", desc: "Matching from database" },
  { id: "compliance", label: "Compliance Agent", desc: "Validating suppliers" },
  { id: "ranking", label: "Ranking Agent", desc: "Scoring results" },
];

export default function ResultsPage() {
  const { queryId } = useParams<{ queryId: string }>();
  const { t } = useTranslation();
  const [showMap, setShowMap] = useState(false);
  const [showAudit, setShowAudit] = useState(false);

  // SSE for live progress
  const { events, isComplete, error: sseError } = useSSE(queryId ?? null);

  // Derived state for completed agents
  const completedAgents = useMemo(() => {
    const agents = events
      .filter((e) => e.agent && e.status === "done")
      .map((e) => e.agent as string);
    return Array.from(new Set(agents));
  }, [events]);

  // Poll for results after SSE completes
  const { data: queryData, isLoading } = useQuery<QueryWithResults>({
    queryKey: ["queryResult", queryId],
    queryFn: () => queryService.getResult(queryId!).then((r) => r.data),
    enabled: isComplete && !sseError && !!queryId,
    refetchInterval: false,
  });

  const { data: auditData } = useQuery({
    queryKey: ["auditTrail", queryId],
    queryFn: () => queryService.getAuditTrail(queryId!).then((r) => r.data),
    enabled: showAudit && isComplete && !!queryId,
  });

  const handleExportCSV = () => {
    if (!queryData?.results) return;
    const headers = ["Rank", "Supplier ID", "Score", "CSR Score", "Explanation"];
    const rows = queryData.results.map((r) => [
      r.rank,
      r.supplier_id,
      r.total_score.toFixed(3),
      r.constraint_score.toFixed(3),
      `"${r.explanation.replace(/"/g, "'")}"`,
    ]);
    const csv = [headers, ...rows].map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `suppliermind_${queryId?.slice(0, 8)}.csv`;
    a.click();
  };

  // ── Processing state ─────────────────────────────────────────────
  if (!isComplete) {
    const progress = (completedAgents.length / AGENT_STEPS.length) * 100;

    return (
      <div className="p-8 max-w-2xl mx-auto">
        <div className="text-center space-y-6">
          {/* Animated brain */}
          <div className="relative mx-auto w-20 h-20">
            <div className="absolute inset-0 rounded-full bg-primary/20 animate-ping" />
            <div className="relative w-20 h-20 rounded-full bg-primary/10 border-2 border-primary flex items-center justify-center">
              <Brain className="w-10 h-10 text-primary" />
            </div>
          </div>

          <div>
            <h2 className="text-xl font-semibold">{t("processing.title")}</h2>
            <p className="text-muted-foreground text-sm mt-1">
              Agents are reasoning about your query...
            </p>
          </div>

          <Progress value={progress} className="h-2" />

          {/* Agent steps */}
          <div className="space-y-2 text-left">
            {AGENT_STEPS.map((step) => {
              const isDone = completedAgents.includes(step.id);
              const isActive =
                !isDone &&
                completedAgents.length === AGENT_STEPS.findIndex((s) => s.id === step.id);

              return (
                <div
                  key={step.id}
                  className={`flex items-center gap-3 p-3 rounded-lg transition-all ${isDone
                      ? "bg-green-500/10 border border-green-500/20"
                      : isActive
                        ? "bg-primary/10 border border-primary/30"
                        : "opacity-40"
                    }`}
                >
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${isDone
                        ? "bg-green-500 text-white"
                        : isActive
                          ? "bg-primary text-white"
                          : "bg-muted"
                      }`}
                  >
                    {isDone ? "✓" : AGENT_STEPS.findIndex((s) => s.id === step.id) + 1}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{step.label}</p>
                    <p className="text-xs text-muted-foreground">{step.desc}</p>
                  </div>
                  {isActive && (
                    <div className="ml-auto w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────
  if (sseError || queryData?.status === "failed") {
    return (
      <div className="p-8 max-w-2xl mx-auto text-center space-y-4">
        <AlertCircle className="w-12 h-12 text-destructive mx-auto" />
        <h2 className="text-xl font-semibold">Discovery failed</h2>
        <p className="text-muted-foreground">
          {sseError || queryData?.error_message || "Something went wrong"}
        </p>
        <Button onClick={() => window.history.back()}>Try again</Button>
      </div>
    );
  }

  // ── Loading results ──────────────────────────────────────────────
  if (isLoading || !queryData) {
    return (
      <div className="p-8 space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-48 w-full" />
          ))}
        </div>
      </div>
    );
  }

  const hasRadius = !!queryData.parsed_constraints?.location_radius_km;
  const execSecs = queryData.execution_time_ms
    ? (queryData.execution_time_ms / 1000).toFixed(1)
    : null;

  // ── Results ──────────────────────────────────────────────────────
  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">{t("results.title")}</p>
          <h1 className="text-xl font-bold mt-0.5 line-clamp-2">
            "{queryData.raw_query}"
          </h1>
          <div className="flex items-center gap-2 mt-2">
            <Badge variant="secondary">
              {t("results.found", { count: queryData.results.length })}
            </Badge>
            {execSecs && (
              <Badge variant="outline">
                {t("results.execution_time", { time: execSecs })}
              </Badge>
            )}
            {queryData.detected_language && queryData.detected_language !== "en" && (
              <Badge variant="outline">
                {queryData.detected_language.toUpperCase()} query
              </Badge>
            )}
          </div>
        </div>

        <div className="flex gap-2 flex-shrink-0">
          {hasRadius && (
            <Button
              variant={showMap ? "default" : "outline"}
              size="sm"
              onClick={() => setShowMap(!showMap)}
              className="gap-2"
            >
              <Map className="w-4 h-4" />
              {t("results.show_map")}
            </Button>
          )}
          <Button
            variant={showAudit ? "default" : "outline"}
            size="sm"
            onClick={() => setShowAudit(!showAudit)}
            className="gap-2"
          >
            <ListTree className="w-4 h-4" />
            {t("results.show_audit")}
          </Button>
          <Button variant="outline" size="sm" onClick={handleExportCSV} className="gap-2">
            <Download className="w-4 h-4" />
            {t("results.export_csv")}
          </Button>
        </div>
      </div>

      {/* Map view */}
      {showMap && queryData.results.length > 0 && (
        <SupplierMap
          results={queryData.results}
          constraints={queryData.parsed_constraints}
        />
      )}

      {/* Results list */}
      {queryData.results.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground space-y-2">
          <AlertCircle className="w-10 h-10 mx-auto opacity-50" />
          <p className="font-medium">{t("results.no_results")}</p>
          <p className="text-sm">{t("results.try_relaxing")}</p>
        </div>
      ) : (
        <div className="space-y-4">
          {queryData.results.map((result) => (
            <SupplierCard
              key={result.supplier_id}
              result={result}
              hasProximity={hasRadius}
            />
          ))}
        </div>
      )}

      {/* Audit trail */}
      {showAudit && auditData && (
        <AuditTrail entries={auditData.audit_entries ?? []} />
      )}
    </div>
  );
}
