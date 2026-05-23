import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { queryService } from "@/services/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckCircle, XCircle, Clock, Search, ExternalLink } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export default function HistoryPage() {
  const { t } = useTranslation();

  const { data, isLoading } = useQuery({
    queryKey: ["queryHistory"],
    queryFn: () => queryService.getHistory(1).then((r) => r.data),
  });

  const queries = data?.items ?? [];

  const statusConfig = {
    completed: { icon: CheckCircle, color: "text-green-500", label: t("history.status_completed") },
    failed: { icon: XCircle, color: "text-red-500", label: t("history.status_failed") },
    pending: { icon: Clock, color: "text-yellow-500", label: t("history.status_pending") },
    processing: { icon: Clock, color: "text-blue-500", label: "Processing" },
  } as const;

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t("history.title")}</h1>
        <p className="text-muted-foreground mt-1">
          {data?.total ?? 0} total discoveries
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : queries.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Search className="w-10 h-10 mx-auto mb-3 opacity-40" />
            <p>{t("history.no_history")}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {queries.map((query: any) => {
            const status = statusConfig[query.status as keyof typeof statusConfig]
              ?? statusConfig.pending;
            const Icon = status.icon;

            return (
              <Link
                key={query.id}
                to={`/query/${query.id}/results`}
                className="block"
              >
                <Card className="hover:shadow-sm transition-shadow cursor-pointer">
                  <CardContent className="p-4">
                    <div className="flex items-center gap-3">
                      <Icon className={`w-5 h-5 flex-shrink-0 ${status.color}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{query.raw_query}</p>
                        <div className="flex items-center gap-3 mt-1">
                          <span className="text-xs text-muted-foreground">
                            {formatDistanceToNow(new Date(query.created_at), { addSuffix: true })}
                          </span>
                          {query.execution_time_ms && (
                            <span className="text-xs text-muted-foreground">
                              {(query.execution_time_ms / 1000).toFixed(1)}s
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {query.results?.length > 0 && (
                          <Badge variant="secondary">
                            {query.results.length} results
                          </Badge>
                        )}
                        <ExternalLink className="w-4 h-4 text-muted-foreground" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
