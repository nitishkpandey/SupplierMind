import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { AuditEntry } from "@/types";
import { ListTree } from "lucide-react";

const AGENT_COLORS: Record<string, string> = {
  parser: "bg-blue-100 text-blue-800 border-blue-200",
  discovery: "bg-purple-100 text-purple-800 border-purple-200",
  compliance: "bg-orange-100 text-orange-800 border-orange-200",
  ranking: "bg-green-100 text-green-800 border-green-200",
  orchestrator: "bg-slate-100 text-slate-800 border-slate-200",
};

interface AuditTrailProps {
  entries: AuditEntry[];
}

export function AuditTrail({ entries }: AuditTrailProps) {
  const { t } = useTranslation();

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
          {entries.map((entry, i) => (
            <div key={i} className="flex gap-4 pb-4">
              {/* Timeline line */}
              <div className="flex flex-col items-center">
                <div className="w-2.5 h-2.5 rounded-full bg-primary mt-1.5 flex-shrink-0" />
                {i < entries.length - 1 && (
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
                    {entry.agent_name}
                  </Badge>
                  <span className="text-xs font-medium">{entry.action}</span>
                  {entry.duration_ms != null && (
                    <span className="text-xs text-muted-foreground ml-auto">
                      {entry.duration_ms}ms
                    </span>
                  )}
                </div>

                {entry.output_snapshot?.summary && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {entry.output_snapshot.summary}
                  </p>
                )}

                {entry.reasoning && (
                  <div className="mt-2 p-2 bg-muted/50 rounded text-xs leading-relaxed border-l-2 border-primary/30">
                    <span className="font-medium text-primary">Reasoning: </span>
                    {entry.reasoning}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
