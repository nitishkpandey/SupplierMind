import { useTranslation } from "react-i18next";
import type { QueryWithResults } from "@/types";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { queryService } from "@/services/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Search, Clock, CheckCircle, XCircle, Brain } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export default function DashboardPage() {
  const { t } = useTranslation();
  const { user } = useAuthStore();

  const { data: historyData, isLoading } = useQuery({
    queryKey: ["queryHistory"],
    queryFn: () => queryService.getHistory(1).then((r) => r.data),
  });

  const recentQueries = historyData?.items?.slice(0, 5) ?? [];

  const statusIcon = (status: string) => {
    if (status === "completed") return <CheckCircle className="w-4 h-4 text-green-500" />;
    if (status === "failed") return <XCircle className="w-4 h-4 text-red-500" />;
    return <Clock className="w-4 h-4 text-yellow-500 animate-pulse" />;
  };

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            {t("dashboard.welcome", { name: user?.name?.split(" ")[0] })}
          </h1>
          <p className="text-muted-foreground mt-1">
            AI-powered supplier discovery ready to use
          </p>
        </div>
        <Link to="/query">
          <Button size="lg" className="gap-2">
            <Brain className="w-5 h-5" />
            {t("dashboard.new_discovery")}
          </Button>
        </Link>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-zinc-200 dark:border-zinc-800 shadow-none hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              {t("dashboard.total_suppliers")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">100</p>
            <p className="text-xs text-muted-foreground mt-1">In SupplierBench database</p>
          </CardContent>
        </Card>
        <Card className="border-zinc-200 dark:border-zinc-800 shadow-none hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              {t("dashboard.your_queries")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">
              {historyData?.total ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground mt-1">Total discoveries run</p>
          </CardContent>
        </Card>
        <Card className="border-zinc-200 dark:border-zinc-800 shadow-none hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Active Agents</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">5</p>
            <p className="text-xs text-muted-foreground mt-1">
              Parser, Discovery, Compliance, Ranking, Orchestrator
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Recent queries */}
      <Card className="border-zinc-200 dark:border-zinc-800 shadow-none">
        <CardHeader>
          <CardTitle>{t("dashboard.recent_queries")}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : recentQueries.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Search className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>{t("history.no_history")}</p>
              <Link to="/query">
                <Button variant="link" className="mt-2">
                  {t("dashboard.new_discovery")}
                </Button>
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {recentQueries.map((query: QueryWithResults) => (
                <Link
                  key={query.id}
                  to={`/query/${query.id}/results`}
                  className="flex items-center gap-3 p-3 rounded-md hover:bg-zinc-50 dark:hover:bg-zinc-900 transition-colors border border-transparent hover:border-zinc-200 dark:hover:border-zinc-800"
                >
                  {statusIcon(query.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm truncate">{query.raw_query}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatDistanceToNow(new Date(query.created_at), { addSuffix: true })}
                    </p>
                  </div>
                  <Badge
                    variant={query.status === "completed" ? "default" : "secondary"}
                    className="text-xs"
                  >
                    {query.results?.length ?? 0} results
                  </Badge>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
