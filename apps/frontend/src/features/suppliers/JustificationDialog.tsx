import { useState } from "react";
import { isAxiosError } from "axios";
import { Button } from "@/components/ui/button";
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

const JUSTIFICATION_MIN = 20;
const JUSTIFICATION_MAX = 1000;

/**
 * HITL justification dialog for the approve/reject supplier workflow.
 * Owns the justification text, validation, and error state; the parent
 * performs the API call (and its success side effects) in `onSubmit`.
 */
export function JustificationDialog({
  action,
  supplierName,
  onClose,
  onSubmit,
}: {
  action: "approve" | "reject" | null;
  supplierName?: string | null;
  onClose: () => void;
  onSubmit: (justification: string) => Promise<void>;
}) {
  const [justification, setJustification] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  // Reset the form on every close, so the next open starts clean.
  const close = () => {
    if (isProcessing) return;
    setJustification("");
    setError(null);
    onClose();
  };

  const justificationLength = justification.trim().length;
  const submitDisabled =
    isProcessing || justificationLength < JUSTIFICATION_MIN || justificationLength > JUSTIFICATION_MAX;

  const submit = async () => {
    const text = justification.trim();
    if (text.length < JUSTIFICATION_MIN) return;
    setIsProcessing(true);
    setError(null);
    try {
      await onSubmit(text);
      setJustification("");
      onClose();
    } catch (e: unknown) {
      const msg = isAxiosError(e) ? e.response?.data?.detail ?? "Request failed. Try again." : "Request failed. Try again.";
      setError(typeof msg === "string" ? msg : "Request failed.");
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Dialog
      open={action !== null}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {action === "approve" ? "Approve" : "Reject"} {supplierName ?? "supplier"}?
          </DialogTitle>
          <DialogDescription>
            {action === "approve"
              ? "Promotes to Tier 1 (approved) and surfaces this supplier in every user's search."
              : "Removes from discovery results for every user."}{" "}
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
            <span className={justificationLength < JUSTIFICATION_MIN ? "text-destructive" : ""}>
              Minimum {JUSTIFICATION_MIN} characters
              {justificationLength < JUSTIFICATION_MIN && ` (${JUSTIFICATION_MIN - justificationLength} more)`}
            </span>
            <span>{justificationLength}/{JUSTIFICATION_MAX}</span>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={close} disabled={isProcessing}>
            Cancel
          </Button>
          <Button
            variant={action === "reject" ? "destructive" : "default"}
            onClick={submit}
            disabled={submitDisabled}
          >
            {action === "approve" ? "Approve supplier" : "Reject supplier"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
