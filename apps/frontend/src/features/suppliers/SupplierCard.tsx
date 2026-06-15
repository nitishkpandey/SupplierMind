import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  CheckCircle2,
  Trash2,
  ShieldCheck,
  Bookmark,
  Gavel,
} from "lucide-react";
import type { QueryResult } from "@/types";
import { supplierWorkflowService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";

const JUSTIFICATION_MIN = 20;
const JUSTIFICATION_MAX = 1000;

interface SupplierCardProps {
  result: QueryResult;
  hasProximity?: boolean;
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

export function SupplierCard({ result }: SupplierCardProps) {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const [expanded, setExpanded] = useState(false);

  // Local state for optimistic UI updates on workflows
  const [tier, setTier] = useState(result.tier || result.supplier_status);
  const [isProcessing, setIsProcessing] = useState(false);

  // Task 2.4 — HITL justification modal state
  const [pendingDecision, setPendingDecision] = useState<'approve' | 'reject' | null>(null);
  const [justification, setJustification] = useState("");
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [recordedJustification, setRecordedJustification] = useState<string | null>(
    result.approval_justification ?? null
  );
  const [recordedAction, setRecordedAction] = useState<'approved' | 'rejected' | null>(
    result.approval_action ?? null
  );

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

  const isAdmin = user?.role === "admin";

  const handleAction = async (action: 'save' | 'unsave') => {
    if (isProcessing) return;
    setIsProcessing(true);
    try {
      if (action === 'save') {
        await supplierWorkflowService.save(result.supplier_id);
        setTier('saved');
      } else if (action === 'unsave') {
        await supplierWorkflowService.unsave(result.supplier_id);
        setTier('discovered');
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsProcessing(false);
    }
  };

  const openDecisionDialog = (decision: 'approve' | 'reject') => {
    setPendingDecision(decision);
    setJustification("");
    setDecisionError(null);
  };

  const closeDecisionDialog = () => {
    if (isProcessing) return;
    setPendingDecision(null);
    setJustification("");
    setDecisionError(null);
  };

  const submitDecision = async () => {
    if (!pendingDecision) return;
    const text = justification.trim();
    if (text.length < JUSTIFICATION_MIN) return;
    setIsProcessing(true);
    setDecisionError(null);
    try {
      if (pendingDecision === 'approve') {
        await supplierWorkflowService.approve(result.supplier_id, text);
        setTier('approved');
        setRecordedAction('approved');
      } else {
        await supplierWorkflowService.reject(result.supplier_id, text);
        setTier('rejected');
        setRecordedAction('rejected');
      }
      setRecordedJustification(text);
      setPendingDecision(null);
      setJustification("");
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? "Request failed. Try again.";
      setDecisionError(typeof msg === 'string' ? msg : "Request failed.");
    } finally {
      setIsProcessing(false);
    }
  };

  const justificationLength = justification.trim().length;
  const submitDisabled =
    isProcessing || justificationLength < JUSTIFICATION_MIN || justificationLength > JUSTIFICATION_MAX;

  if (tier === 'rejected') return null; // Hide rejected from view

  return (
    <Card className={`overflow-hidden transition-all hover:shadow-md ${tier === 'approved' ? 'border-primary/50 shadow-sm' : ''}`}>
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
                {result.supplier_name ?? result.supplier_id.slice(0, 8) + "..."}
              </h3>
              
              {/* Tier Badges */}
              {tier === "approved" && (
                <Badge variant="default" className="text-xs bg-primary hover:bg-primary gap-1">
                  <ShieldCheck className="w-3 h-3" />
                  Approved
                </Badge>
              )}
              {tier === "saved" && (
                <Badge variant="secondary" className="text-xs bg-purple-100 text-purple-700 hover:bg-purple-100 gap-1 border-purple-200">
                  <Bookmark className="w-3 h-3" />
                  Saved to Shortlist
                </Badge>
              )}
              {(tier === "discovered" || !tier) && (
                <Badge variant="outline" className="text-xs border-emerald-200 bg-emerald-50 text-emerald-700 gap-1">
                  <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse inline-block" />
                  New Discovery
                </Badge>
              )}
              {result.sanctions_status === "pending_review" && (
                <Badge variant="outline" className="text-xs border-amber-200 bg-amber-50 text-amber-700 gap-1">
                  <AlertCircle className="w-3 h-3" />
                  Sanctions check pending
                </Badge>
              )}
            </div>
            
            <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground flex-wrap">
              {result.supplier_city && (
                <span className="flex items-center gap-1">
                  <MapPin className="w-3.5 h-3.5" />
                  {result.supplier_city}{result.supplier_country ? `, ${result.supplier_country}` : ""}
                </span>
              )}
              {result.distance_km != null && (
                <span className="flex items-center gap-1 text-primary font-medium">
                  <MapPin className="w-3.5 h-3.5" />
                  {t("supplier_card.distance", { km: result.distance_km.toFixed(1) })}
                </span>
              )}
              {result.supplier_lead_time_days != null && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  {t("supplier_card.lead_time", { days: result.supplier_lead_time_days })}
                </span>
              )}
              {result.supplier_capacity_value != null && (
                <span className="flex items-center gap-1">
                  <Package className="w-3.5 h-3.5" />
                  {t("supplier_card.capacity", {
                    value: result.supplier_capacity_value.toLocaleString(),
                    unit: result.supplier_capacity_unit ?? "",
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
        {result.supplier_certifications && result.supplier_certifications.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {result.supplier_certifications.map((cert: string) => (
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
                <ComplianceBadge status={status as "PASS" | "FAIL" | "PARTIAL"} />
              </div>
            ))}
          </div>
        )}

        {/* Explanation — Task 1.5: structured, data-derived (no LLM free text) */}
        {result.explanation_detail ? (
          <div className="bg-muted/50 p-3 rounded-lg border border-border/50 space-y-2.5">
            {result.explanation_detail.summary && (
              <p className="text-sm font-medium">{result.explanation_detail.summary}</p>
            )}
            {result.explanation_detail.match_reasons.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-semibold text-green-700">Why it matches</p>
                <ul className="space-y-0.5">
                  {result.explanation_detail.match_reasons.map((reason, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
                      <CheckCircle className="w-3.5 h-3.5 text-green-600 flex-shrink-0 mt-0.5" />
                      <span>{reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.explanation_detail.concerns.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-semibold text-amber-700">Things to check</p>
                <ul className="space-y-0.5">
                  {result.explanation_detail.concerns.map((concern, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
                      <AlertCircle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
                      <span>{concern}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          result.explanation && (
            <p className="text-sm text-muted-foreground leading-relaxed bg-muted/50 p-3 rounded-lg border border-border/50">
              {result.explanation}
            </p>
          )
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

        <Separator />

        {/* Actions - Production v2 Workflows */}
        <div className="flex gap-2 pt-1 justify-between items-center">
          <div>
            {result.supplier_website && (
              <Button variant="outline" size="sm" asChild>
                <a href={result.supplier_website} target="_blank" rel="noreferrer" className="gap-1.5">
                  <ExternalLink className="w-3.5 h-3.5" />
                  Visit Site
                </a>
              </Button>
            )}
          </div>
          
          <div className="flex gap-2">
            {tier === 'saved' ? (
              <Button 
                variant="secondary" 
                size="sm" 
                className="gap-1.5 bg-purple-100 text-purple-700 hover:bg-purple-200"
                onClick={() => handleAction('unsave')}
                disabled={isProcessing}
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                Saved
              </Button>
            ) : tier !== 'approved' && (
              <Button 
                variant="outline" 
                size="sm" 
                className="gap-1.5"
                onClick={() => handleAction('save')}
                disabled={isProcessing}
              >
                <Star className="w-3.5 h-3.5" />
                Save to Shortlist
              </Button>
            )}

            {isAdmin && tier !== 'approved' && (
              <Button
                variant="default"
                size="sm"
                className="gap-1.5"
                onClick={() => openDecisionDialog('approve')}
                disabled={isProcessing}
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Approve
              </Button>
            )}

            {isAdmin && tier !== 'approved' && (
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => openDecisionDialog('reject')}
                disabled={isProcessing}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            )}
          </div>
        </div>

        {/* Task 2.4 — HITL rationale on approved/rejected suppliers */}
        {recordedJustification && recordedAction === 'approved' && (
          <div className="rounded-lg border border-border/60 bg-muted/30 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
              <Gavel className="w-3.5 h-3.5" />
              Approval rationale
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {recordedJustification}
            </p>
          </div>
        )}
      </CardContent>

      {/* HITL justification dialog — admin approve/reject flow */}
      <Dialog
        open={pendingDecision !== null}
        onOpenChange={(open) => {
          if (!open) closeDecisionDialog();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {pendingDecision === 'approve' ? 'Approve' : 'Reject'}{' '}
              {result.supplier_name ?? 'supplier'}?
            </DialogTitle>
            <DialogDescription>
              {pendingDecision === 'approve'
                ? 'Promotes to Tier 1 (approved) and surfaces this supplier in every user\'s search.'
                : 'Removes from discovery results for every user.'}{' '}
              Record why this decision is correct — the rationale is persisted in the audit log.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="justification">Justification</Label>
            <Textarea
              id="justification"
              value={justification}
              onChange={(e) => setJustification(e.target.value.slice(0, JUSTIFICATION_MAX))}
              placeholder="e.g. Verified AS9100 certification via cert body lookup; confirmed Bavaria facility matches query."
              rows={5}
              disabled={isProcessing}
              autoFocus
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span
                className={
                  justificationLength < JUSTIFICATION_MIN ? 'text-destructive' : ''
                }
              >
                Minimum {JUSTIFICATION_MIN} characters
                {justificationLength < JUSTIFICATION_MIN &&
                  ` (${JUSTIFICATION_MIN - justificationLength} more)`}
              </span>
              <span>
                {justificationLength}/{JUSTIFICATION_MAX}
              </span>
            </div>
            {decisionError && (
              <p className="text-xs text-destructive">{decisionError}</p>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="ghost"
              onClick={closeDecisionDialog}
              disabled={isProcessing}
            >
              Cancel
            </Button>
            <Button
              variant={pendingDecision === 'reject' ? 'destructive' : 'default'}
              onClick={submitDecision}
              disabled={submitDisabled}
            >
              {pendingDecision === 'approve' ? 'Approve supplier' : 'Reject supplier'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
