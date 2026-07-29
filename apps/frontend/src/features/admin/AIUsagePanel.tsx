import { AlertTriangle, Ban, Bot, CircleDollarSign, XCircle } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AIUsageMetrics } from "@/services/api";

function formatCost(value: number): string {
  return `$${value.toFixed(4)}`;
}

function formatLatency(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${value} ms`;
}

function UsageSummaryCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              {label}
            </p>
            <p className="text-2xl font-semibold tabular-nums mt-1">{value}</p>
          </div>
          <Icon className="w-5 h-5 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

export function AIUsagePanel({ usage }: { usage: AIUsageMetrics }) {
  const { summary } = usage;

  return (
    <section aria-labelledby="ai-usage-heading" className="space-y-3">
      <div>
        <h2 id="ai-usage-heading" className="text-lg font-semibold">
          AI usage and budgets
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          Provider activity, measured cost, policy denials, and failures for this
          window.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <UsageSummaryCard
          label="AI calls"
          value={summary.calls.toLocaleString()}
          icon={Bot}
        />
        <UsageSummaryCard
          label="Known cost"
          value={formatCost(summary.known_cost_usd)}
          icon={CircleDollarSign}
        />
        <UsageSummaryCard
          label="Denied calls"
          value={summary.denied_calls.toLocaleString()}
          icon={Ban}
        />
        <UsageSummaryCard
          label="Failed calls"
          value={summary.failed_calls.toLocaleString()}
          icon={XCircle}
        />
      </div>

      {summary.unknown_cost_calls > 0 && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>
            {summary.unknown_cost_calls.toLocaleString()} calls have unknown cost.
            Known cost excludes those calls.
          </span>
        </div>
      )}

      {summary.calls === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No AI provider calls were recorded in this window.
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Provider usage</CardTitle>
            </CardHeader>
            <CardContent>
              {usage.providers.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No provider breakdown is available for this window.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-xs text-muted-foreground">
                        <th className="text-left py-2 font-medium">Provider</th>
                        <th className="text-left py-2 font-medium">Model</th>
                        <th className="text-left py-2 font-medium">Operation</th>
                        <th className="text-right py-2 font-medium">Calls</th>
                        <th className="text-right py-2 font-medium">p95</th>
                        <th className="text-right py-2 font-medium">Known cost</th>
                        <th className="text-right py-2 font-medium">Unknown</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.providers.map((row) => (
                        <tr
                          key={`${row.provider}:${row.model}:${row.operation}`}
                          className="border-b last:border-0"
                        >
                          <td className="py-2">{row.provider}</td>
                          <td className="py-2 font-mono text-xs">{row.model}</td>
                          <td className="py-2">{row.operation}</td>
                          <td className="py-2 text-right tabular-nums">
                            {row.calls.toLocaleString()}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {formatLatency(row.p95_ms)}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {formatCost(row.known_cost_usd)}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {row.unknown_cost_calls.toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Purpose and agent usage</CardTitle>
            </CardHeader>
            <CardContent>
              {usage.purposes.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No purpose breakdown is available for this window.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-xs text-muted-foreground">
                        <th className="text-left py-2 font-medium">Purpose</th>
                        <th className="text-right py-2 font-medium">Calls</th>
                        <th className="text-right py-2 font-medium">p95</th>
                        <th className="text-right py-2 font-medium">Known cost</th>
                        <th className="text-right py-2 font-medium">Denials</th>
                        <th className="text-right py-2 font-medium">Failures</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.purposes.map((row) => (
                        <tr key={row.purpose} className="border-b last:border-0">
                          <td className="py-2 font-mono text-xs">{row.purpose}</td>
                          <td className="py-2 text-right tabular-nums">
                            {row.calls.toLocaleString()}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {formatLatency(row.p95_ms)}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {formatCost(row.known_cost_usd)}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {row.denied_calls.toLocaleString()}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {row.failed_calls.toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Highest-cost queries</CardTitle>
            </CardHeader>
            <CardContent>
              {usage.top_queries.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No query-attributed AI cost is available for this window.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-xs text-muted-foreground">
                        <th className="text-left py-2 font-medium">Query</th>
                        <th className="text-right py-2 font-medium">Calls</th>
                        <th className="text-right py-2 font-medium">Known cost</th>
                        <th className="text-right py-2 font-medium">Unknown</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.top_queries.map((row) => (
                        <tr key={row.query_id} className="border-b last:border-0">
                          <td className="py-2">
                            <Link
                              to={`/query/${row.query_id}/results`}
                              className="font-mono text-xs text-primary hover:underline"
                            >
                              {row.query_id}
                            </Link>
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {row.calls.toLocaleString()}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {formatCost(row.known_cost_usd)}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {row.unknown_cost_calls.toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </section>
  );
}
