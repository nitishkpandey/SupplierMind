import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation } from "@tanstack/react-query";
import { evalService } from "@/services/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { Play, Loader2 } from "lucide-react";

export default function AdminPage() {
  const { t } = useTranslation();
  const [evalTriggered, setEvalTriggered] = useState(false);

  const { data: report, isLoading: reportLoading, refetch } = useQuery({
    queryKey: ["evalReport"],
    queryFn: () => evalService.getReport().then((r) => r.data),
    retry: false,
  });

  const triggerMutation = useMutation({
    mutationFn: (baselinesOnly: boolean) => evalService.triggerRun(baselinesOnly),
    onSuccess: () => {
      setEvalTriggered(true);
      setTimeout(() => refetch(), 30000); // Refetch after 30s for baselines
    },
  });

  // Build chart data from report
  const comparisonData = report?.rq2_performance_comparison
    ? Object.entries(report.rq2_performance_comparison).map(([key, metricsRaw]) => {
        const metrics = metricsRaw as Record<string, { mean: number }>;
        return {
          name: key === "suppliermind" ? "SupplierMind" : key === "manual_simulation" ? "Manual Sim" : "Keyword SQL",
          "P@5": parseFloat((metrics.precision_at_5?.mean * 100).toFixed(1)),
          CSR: parseFloat((metrics.constraint_satisfaction_rate?.mean * 100).toFixed(1)),
          MRR: parseFloat((metrics.mean_reciprocal_rank?.mean * 100).toFixed(1)),
        };
      })
    : [];

  const difficultyData = report?.difficulty_breakdown?.suppliermind
    ? [
        { difficulty: "Simple", P5: parseFloat((report.difficulty_breakdown.suppliermind.simple_p5 * 100).toFixed(1)) },
        { difficulty: "Medium", P5: parseFloat((report.difficulty_breakdown.suppliermind.medium_p5 * 100).toFixed(1)) },
        { difficulty: "Hard", P5: parseFloat((report.difficulty_breakdown.suppliermind.hard_p5 * 100).toFixed(1)) },
      ]
    : [];

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t("admin.title")}</h1>
        <p className="text-muted-foreground mt-1">Evaluation dashboard and system management</p>
      </div>

      <Tabs defaultValue="evaluation">
        <TabsList>
          <TabsTrigger value="evaluation">{t("admin.evaluation_tab")}</TabsTrigger>
          <TabsTrigger value="suppliers">{t("admin.suppliers_tab")}</TabsTrigger>
        </TabsList>

        <TabsContent value="evaluation" className="space-y-6">
          {/* Run controls */}
          <Card>
            <CardHeader>
              <CardTitle>SupplierBench Evaluation</CardTitle>
              <CardDescription>
                Run the full evaluation against 25 benchmark queries
              </CardDescription>
            </CardHeader>
            <CardContent className="flex gap-3">
              <Button
                onClick={() => triggerMutation.mutate(false)}
                disabled={triggerMutation.isPending || evalTriggered}
                className="gap-2"
              >
                {triggerMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                {t("admin.run_eval")} (all systems, ~15 min)
              </Button>
              <Button
                variant="outline"
                onClick={() => triggerMutation.mutate(true)}
                disabled={triggerMutation.isPending}
                className="gap-2"
              >
                <Play className="w-4 h-4" />
                {t("admin.baselines_only")} (~5s)
              </Button>
              {evalTriggered && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t("admin.eval_running")}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Results charts */}
          {reportLoading ? (
            <Card>
              <CardContent className="py-12 text-center text-muted-foreground">
                Loading evaluation results...
              </CardContent>
            </Card>
          ) : !report ? (
            <Card>
              <CardContent className="py-12 text-center text-muted-foreground">
                No evaluation results yet. Run an evaluation first.
              </CardContent>
            </Card>
          ) : (
            <>
              {/* Comparison bar chart */}
              <Card>
                <CardHeader>
                  <CardTitle>System Comparison (P@5, CSR, MRR)</CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={comparisonData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" />
                      <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                      <Tooltip formatter={(v) => `${v}%`} />
                      <Legend />
                      <Bar dataKey="P@5" fill="#3b82f6" />
                      <Bar dataKey="CSR" fill="#8b5cf6" />
                      <Bar dataKey="MRR" fill="#10b981" />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Difficulty breakdown */}
              {difficultyData.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>SupplierMind P@5 by Query Difficulty</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={difficultyData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="difficulty" />
                        <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                        <Tooltip formatter={(v) => `${v}%`} />
                        <Bar dataKey="P5" name="Precision@5" fill="#3b82f6" />
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}

              {/* Failure analysis */}
              {report.rq3_failure_analysis?.observations?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>RQ3: Failure Analysis</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {report.rq3_failure_analysis.observations.map((obs: string, i: number) => (
                        <li key={i} className="flex gap-2 text-sm">
                          <span className="text-primary font-medium mt-0.5">•</span>
                          {obs}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="suppliers">
          <Card>
            <CardHeader>
              <CardTitle>Supplier Database</CardTitle>
              <CardDescription>Active supplier count is read from the database</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Supplier management UI — add, edit, re-index via the API at{" "}
                <code className="bg-muted px-1 rounded">POST /api/v1/suppliers/bulk</code>
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
