import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { queryService } from "@/services/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Brain, Sparkles, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const EXAMPLE_QUERIES = [
  "ISO 9001 certified bronze supplier within 25km of Bremen, capacity above 5000 kg/month",
  "Electronics supplier in Germany with RoHS certification, lead time under 14 days",
  "ISO 27001 certified software services company in Netherlands",
  "Packaging manufacturer with 100,000+ units/month capacity near Berlin",
];

export default function QueryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const charCount = query.length;
  const isValid = charCount >= 10 && charCount <= 1000;

  const handleSubmit = useCallback(async () => {
    if (!isValid || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);

    try {
      const res = await queryService.submit(query.trim());
      navigate(`/query/${res.data.id}/results`);
    } catch (err: any) {
      const msg = err.response?.data?.detail ?? t("errors.server");
      setError(msg);
      setIsSubmitting(false);
    }
  }, [query, isValid, isSubmitting, navigate, t]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      handleSubmit();
    }
  };

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 mb-4">
          <Brain className="w-7 h-7 text-primary" />
        </div>
        <h1 className="text-3xl font-bold">Discover Suppliers</h1>
        <p className="text-muted-foreground">
          Describe your procurement needs in plain language. In any language.
        </p>
      </div>

      {/* Query input */}
      <div className="space-y-2">
        <Textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t("query.placeholder")}
          className={cn(
            "min-h-[140px] text-base resize-none transition-colors",
            !isValid && charCount > 0 && "border-destructive focus-visible:ring-destructive"
          )}
          disabled={isSubmitting}
        />
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {charCount < 10 && charCount > 0 && (
              <span className="text-destructive flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                {t("query.too_short")}
              </span>
            )}
            {charCount > 1000 && (
              <span className="text-destructive">{t("query.too_long")}</span>
            )}
          </span>
          <span className={charCount > 950 ? "text-destructive" : ""}>
            {charCount} / 1000
          </span>
        </div>
      </div>

      {/* Submit button */}
      <Button
        onClick={handleSubmit}
        disabled={!isValid || isSubmitting}
        size="lg"
        className="w-full h-12 text-base gap-2"
      >
        {isSubmitting ? (
          <>
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Launching agents...
          </>
        ) : (
          <>
            <Sparkles className="w-5 h-5" />
            {t("query.submit")}
            <span className="text-xs opacity-70 ml-1">Ctrl+Enter</span>
          </>
        )}
      </Button>

      {error && (
        <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 p-3 rounded-lg">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Examples */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <div className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">Example queries</span>
          <div className="h-px flex-1 bg-border" />
        </div>
        <div className="grid gap-2">
          {EXAMPLE_QUERIES.map((ex, i) => (
            <button
              key={i}
              onClick={() => setQuery(ex)}
              className="text-left text-sm p-3 rounded-lg border border-dashed hover:border-primary hover:bg-primary/5 transition-colors text-muted-foreground hover:text-foreground"
            >
              "{ex}"
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
