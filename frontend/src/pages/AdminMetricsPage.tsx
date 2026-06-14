import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { metricsService, type AdminMetrics } from "@/services/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { RefreshCcw, Activity, AlertTriangle, Gauge, Users } from "lucide-react";

const WINDOW_OPTIONS: Array<{ label: string; hours: number }> = [
  { label: "Last 1h", hours: 1 },
  { label: "Last 6h", hours: 6 },
  { label: "Last 24h", hours: 24 },
  { label: "Last 7d", hours: 168 },
];

function formatMs(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)} min`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${ms} ms`;
}

function p95ClassName(ms: number): string {
  if (ms > 30_000) return "text-destructive font-semibold";
  if (ms > 10_000) return "text-amber-600 font-semibold";
  return "";
}

function SummaryCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
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
            <p className="text-2xl font-semibold tabular-nums mt-1">
              {value.toLocaleString()}
            </p>
          </div>
          <Icon className="w-5 h-5 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

export default function AdminMetricsPage() {
  const [windowHours, setWindowHours] = useState(24);

  const { data, isLoading, isFetching, refetch, error } = useQuery<AdminMetrics>({
    queryKey: ["adminMetrics", windowHours],
    queryFn: () => metricsService.get(windowHours).then((r) => r.data),
    refetchOnWindowFocus: false,
  });

  const chartData =
    data?.agent_latency.map((row) => ({
      name: row.agent_name,
      mean: row.mean_ms,
    })) ?? [];

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">Operational Metrics</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Per-agent latency, throttle activity, and recent errors aggregated from{" "}
            <code className="bg-muted px-1 rounded">audit_logs</code>.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex border rounded-md overflow-hidden">
            {WINDOW_OPTIONS.map((opt) => (
              <button
                key={opt.hours}
                onClick={() => setWindowHours(opt.hours)}
                className={`px-3 py-1.5 text-xs ${
                  windowHours === opt.hours
                    ? "bg-primary text-primary-foreground"
                    : "bg-background hover:bg-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-1.5"
          >
            <RefreshCcw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {data?.as_of && (
        <p className="text-xs text-muted-foreground">
          Last updated {new Date(data.as_of).toLocaleString()} · window{" "}
          {data.window_hours}h
        </p>
      )}

      {isLoading && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            Loading metrics…
          </CardContent>
        </Card>
      )}

      {error && (
        <Card>
          <CardContent className="py-6 text-center text-destructive">
            Failed to load metrics. Try Refresh.
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <SummaryCard
              label="Total queries"
              value={data.summary.total_queries}
              icon={Activity}
            />
            <SummaryCard
              label="Agent invocations"
              value={data.summary.total_agent_invocations}
              icon={Gauge}
            />
            <SummaryCard
              label="Human decisions"
              value={data.summary.total_human_decisions}
              icon={Users}
            />
            <SummaryCard
              label="Queries with errors"
              value={data.summary.queries_with_errors}
              icon={AlertTriangle}
            />
          </div>

          {/* Agent latency table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Agent latency</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {data.agent_latency.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No audit_logs entries in this window.
                </p>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs text-muted-foreground">
                          <th className="text-left py-2 font-medium">Agent</th>
                          <th className="text-right py-2 font-medium">p50</th>
                          <th className="text-right py-2 font-medium">p95</th>
                          <th className="text-right py-2 font-medium">Mean</th>
                          <th className="text-right py-2 font-medium">Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.agent_latency.map((row) => (
                          <tr key={row.agent_name} className="border-b last:border-0">
                            <td className="py-2 font-mono text-xs">
                              {row.agent_name}
                            </td>
                            <td className="py-2 text-right tabular-nums">
                              {formatMs(row.p50_ms)}
                            </td>
                            <td
                              className={`py-2 text-right tabular-nums ${p95ClassName(
                                row.p95_ms,
                              )}`}
                            >
                              {formatMs(row.p95_ms)}
                            </td>
                            <td className="py-2 text-right tabular-nums">
                              {formatMs(row.mean_ms)}
                            </td>
                            <td className="py-2 text-right tabular-nums">
                              {row.count.toLocaleString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="text-xs text-muted-foreground mt-2">
                      p95 highlighted amber &gt; 10s, red &gt; 30s.
                    </p>
                  </div>

                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis
                        dataKey="name"
                        tick={{ fontSize: 11 }}
                        interval={0}
                        angle={-15}
                        textAnchor="end"
                        height={50}
                      />
                      <YAxis
                        tickFormatter={(v) => formatMs(v)}
                        tick={{ fontSize: 11 }}
                      />
                      <Tooltip formatter={(v: number) => formatMs(v)} />
                      <Bar dataKey="mean" fill="#3b82f6" name="Mean latency" />
                    </BarChart>
                  </ResponsiveContainer>
                </>
              )}
            </CardContent>
          </Card>

          {/* Throttle + errors */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Throttle activity</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-muted-foreground">
                    Throttle pacing events
                  </span>
                  <span className="text-lg font-semibold tabular-nums">
                    {data.throttle_events.throttle_pacing_events.toLocaleString()}
                  </span>
                </div>
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-muted-foreground">
                    Throttle 429 occurrences
                  </span>
                  <span
                    className={`text-lg font-semibold tabular-nums ${
                      data.throttle_events.throttle_429_count > 0
                        ? "text-amber-600"
                        : ""
                    }`}
                  >
                    {data.throttle_events.throttle_429_count.toLocaleString()}
                  </span>
                </div>
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-muted-foreground">
                    Suppliers in sanctions pending review
                  </span>
                  <span className="text-lg font-semibold tabular-nums">
                    {data.throttle_events.sanctions_pending_review.toLocaleString()}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground pt-2">
                  Sanctions count is current-state, not window-scoped.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Recent errors</CardTitle>
              </CardHeader>
              <CardContent>
                {data.recent_errors.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No errors in this window.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {data.recent_errors.map((err, i) => (
                      <li
                        key={i}
                        className="border-b last:border-0 pb-2 last:pb-0 text-xs"
                      >
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono">{err.agent_name}</span>
                          <span className="text-muted-foreground">·</span>
                          <span>{err.action}</span>
                          {err.timestamp && (
                            <>
                              <span className="text-muted-foreground">·</span>
                              <span className="text-muted-foreground">
                                {new Date(err.timestamp).toLocaleString()}
                              </span>
                            </>
                          )}
                        </div>
                        {err.reasoning && (
                          <p className="text-muted-foreground mt-1 line-clamp-2">
                            {err.reasoning}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
