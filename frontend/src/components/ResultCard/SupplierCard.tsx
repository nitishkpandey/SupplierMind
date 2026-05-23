import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { supplierService } from "@/services/api";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  ChevronDown,
  ChevronUp,
  MapPin,
  Clock,
  Package,
  ExternalLink,
  CheckCircle,
  XCircle,
  AlertCircle,
  Star,
} from "lucide-react";
import type { QueryResult } from "@/types";

interface SupplierCardProps {
  result: QueryResult;
  hasProximity: boolean;
}

function ComplianceBadge({ status }: { status: "PASS" | "FAIL" | "PARTIAL" }) {
  const config = {
    PASS: { icon: CheckCircle, color: "text-green-600", bg: "bg-green-50 border-green-200" },
    FAIL: { icon: XCircle, color: "text-red-600", bg: "bg-red-50 border-red-200" },
    PARTIAL: { icon: AlertCircle, color: "text-yellow-600", bg: "bg-yellow-50 border-yellow-200" },
  }[status];

  const Icon = config.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border ${config.bg} ${config.color}`}>
      <Icon className="w-3 h-3" />
      {status}
    </span>
  );
}

function ScoreBar({ label, value, color = "bg-primary" }: { label: string; value: number; color?: string }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">{(value * 100).toFixed(0)}%</span>
      </div>
      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all`}
          style={{ width: `${value * 100}%` }}
        />
      </div>
    </div>
  );
}

export function SupplierCard({ result, hasProximity: _ }: SupplierCardProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  // Fetch supplier details
  const { data: supplier } = useQuery({
    queryKey: ["supplier", result.supplier_id],
    queryFn: () => supplierService.getById(result.supplier_id).then((r) => r.data as any),
  });

  const scorePercent = Math.round(result.total_score * 100);
  const scoreColor =
    scorePercent >= 80 ? "text-green-600" : scorePercent >= 60 ? "text-yellow-600" : "text-red-600";

  const rankBg = result.rank === 1
    ? "bg-yellow-400"
    : result.rank === 2
    ? "bg-slate-300"
    : result.rank === 3
    ? "bg-amber-600"
    : "bg-muted";

  return (
    <Card className="overflow-hidden transition-shadow hover:shadow-md">
      <CardHeader className="pb-3">
        <div className="flex items-start gap-4">
          {/* Rank badge */}
          <div
            className={`w-9 h-9 rounded-full ${rankBg} flex items-center justify-center font-bold text-sm flex-shrink-0`}
          >
            #{result.rank}
          </div>

          {/* Name + location */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-base">
                {supplier?.name ?? result.supplier_id.slice(0, 8) + "..."}
              </h3>
              {supplier?.category && (
                <Badge variant="secondary" className="text-xs">
                  {supplier.category}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground flex-wrap">
              {supplier?.city && (
                <span className="flex items-center gap-1">
                  <MapPin className="w-3.5 h-3.5" />
                  {supplier.city}, {supplier.country}
                </span>
              )}
              {result.distance_km != null && (
                <span className="flex items-center gap-1 text-primary font-medium">
                  <MapPin className="w-3.5 h-3.5" />
                  {t("supplier_card.distance", { km: result.distance_km.toFixed(1) })}
                </span>
              )}
              {supplier?.lead_time_days && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  {t("supplier_card.lead_time", { days: supplier.lead_time_days })}
                </span>
              )}
              {supplier?.capacity_value && (
                <span className="flex items-center gap-1">
                  <Package className="w-3.5 h-3.5" />
                  {t("supplier_card.capacity", {
                    value: supplier.capacity_value.toLocaleString(),
                    unit: supplier.capacity_unit ?? "",
                  })}
                </span>
              )}
            </div>
          </div>

          {/* Score */}
          <div className="text-right flex-shrink-0">
            <div className={`text-3xl font-bold tabular-nums ${scoreColor}`}>
              {scorePercent}%
            </div>
            <div className="text-xs text-muted-foreground">{t("supplier_card.score")}</div>
          </div>
        </div>

        {/* Certifications */}
        {supplier?.certifications && supplier.certifications.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {supplier.certifications.map((cert: string) => (
              <Badge key={cert} variant="outline" className="text-xs">
                {cert}
              </Badge>
            ))}
          </div>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Compliance matrix */}
        {Object.keys(result.compliance_matrix).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(result.compliance_matrix).map(([constraint, status]) => (
              <div key={constraint} className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground capitalize">
                  {constraint.replace(/_/g, " ")}:
                </span>
                <ComplianceBadge status={status as any} />
              </div>
            ))}
          </div>
        )}

        {/* Explanation */}
        {result.explanation && (
          <p className="text-sm text-muted-foreground leading-relaxed bg-muted/50 p-3 rounded-lg">
            {result.explanation}
          </p>
        )}

        {/* Expandable scores */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          Score breakdown
        </button>

        {expanded && (
          <div className="space-y-2 pt-1">
            <ScoreBar label="Constraint satisfaction" value={result.constraint_score} color="bg-blue-500" />
            <ScoreBar label="Semantic relevance" value={result.semantic_score} color="bg-purple-500" />
            {result.proximity_score != null && (
              <ScoreBar label="Proximity" value={result.proximity_score} color="bg-green-500" />
            )}
            <ScoreBar label="Profile completeness" value={result.completeness_score} color="bg-slate-400" />
            <Separator />
            <ScoreBar label="Overall match" value={result.total_score} />
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-1">
          {supplier?.website && (
            <Button variant="outline" size="sm" asChild>
              <a href={supplier.website} target="_blank" rel="noreferrer" className="gap-1.5">
                <ExternalLink className="w-3.5 h-3.5" />
                {t("supplier_card.visit_website")}
              </a>
            </Button>
          )}
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <Star className="w-3.5 h-3.5" />
            {t("supplier_card.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
