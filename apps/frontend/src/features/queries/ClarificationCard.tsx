/**
 * ClarificationCard — Task 3.3 multi-turn clarification dialogue.
 *
 * Rendered when the Parser pauses the pipeline with a question. The user
 * types one short answer; on submit we POST to /queries/:id/clarify, which
 * marks the row resolved and resumes the pipeline. The parent page (e.g.
 * ResultsPage) is responsible for re-subscribing to the SSE stream so the
 * resumed pipeline's progress flows in.
 */

import { useState, type KeyboardEvent } from "react";
import { isAxiosError } from "axios";
import { queryService } from "@/services/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MessageCircleQuestion, AlertCircle } from "lucide-react";

interface Props {
  queryId: string;
  question: string;
  turnNumber: number;
  maxTurns?: number;
  onAnswered: () => void;
}

export function ClarificationCard({
  queryId,
  question,
  turnNumber,
  maxTurns = 3,
  onAnswered,
}: Props) {
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = answer.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await queryService.submitClarification(queryId, trimmed);
      onAnswered();
    } catch (err) {
      const msg = isAxiosError(err)
        ? err.response?.data?.detail ?? "Submission failed"
        : "Submission failed";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  return (
    <Card className="border-primary/40 bg-primary/5">
      <CardHeader className="space-y-3">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="gap-1">
            <MessageCircleQuestion className="w-3 h-3" />
            Quick question · Turn {turnNumber} of {maxTurns}
          </Badge>
        </div>
        <CardTitle className="text-base leading-relaxed">{question}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Your answer..."
          maxLength={500}
          disabled={submitting}
          autoFocus
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">
            {answer.length} / 500
          </span>
          <Button
            onClick={submit}
            disabled={submitting || !answer.trim()}
            size="sm"
          >
            {submitting ? "Working..." : "Continue"}
          </Button>
        </div>
        {error && (
          <div className="flex items-center gap-2 text-xs text-destructive bg-destructive/10 p-2 rounded">
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
            {error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
