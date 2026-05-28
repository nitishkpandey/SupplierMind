import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { queryService } from "@/services/api";
import type { SearchScope } from "@/types";
import { isAxiosError } from "axios";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Brain, Sparkles, AlertCircle, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";

const ALL_EXAMPLE_QUERIES = [
  "ISO 9001 certified bronze supplier within 25km of Bremen, capacity above 5000 kg/month",
  "Electronics supplier in Germany with RoHS certification, lead time under 14 days",
  "ISO 27001 certified software services company in Netherlands",
  "Packaging manufacturer with 100,000+ units/month capacity near Berlin",
  "AS9100 certified aerospace machining suppliers in Bavaria",
  "IATF 16949 certified automotive stamping supplier near Stuttgart",
  "Custom plastic injection molding factory in Poland with ISO 14001 certification",
  "Aluminum die casting manufacturer in Northern Italy with capacity over 50 tons/month",
  "High precision CNC milling workshop in Czech Republic with tolerances under 5 microns",
  "Eco-friendly corrugated box packaging suppliers in France or Belgium",
  "Medical device contract manufacturer with ISO 13485 cleanroom class 7 in Denmark",
  "Sheet metal fabrication shop with laser cutting capability in Slovakia",
  "PCB assembly (PCBA) manufacturer with prototype and low-volume capabilities in Sweden",
  "Sustainable textile and garment supplier in Portugal with OEKO-TEX certification",
  "Cable and wire harness assembly supplier with UL certification in Hungary"
];

export default function QueryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<SearchScope>("approved_only");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [examples, setExamples] = useState<string[]>(() => {
    const shuffled = [...ALL_EXAMPLE_QUERIES].sort(() => 0.5 - Math.random());
    return shuffled.slice(0, 4);
  });
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    setExamples((prev) => {
      const remaining = ALL_EXAMPLE_QUERIES.filter((q) => !prev.includes(q));
      const shuffled = remaining.sort(() => 0.5 - Math.random());
      const selected = shuffled.slice(0, 4);
      if (selected.length < 4) {
        const fallback = ALL_EXAMPLE_QUERIES.filter((q) => !selected.includes(q));
        const additional = fallback.sort(() => 0.5 - Math.random()).slice(0, 4 - selected.length);
        return [...selected, ...additional];
      }
      return selected;
    });
    setTimeout(() => setIsRefreshing(false), 500);
  }, []);

  const charCount = query.length;
  const isValid = charCount >= 10 && charCount <= 1000;

  const handleSubmit = useCallback(async () => {
    if (!isValid || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);

    try {
      const res = await queryService.submit(query.trim(), scope);
      navigate(`/query/${res.data.id}/results`);
    } catch (err) {
      const msg = isAxiosError(err) ? err.response?.data?.detail ?? t("errors.server") : t("errors.server");
      setError(msg);
      setIsSubmitting(false);
    }
  }, [query, scope, isValid, isSubmitting, navigate, t]);

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

      {/* Search Scope */}
      <div className="space-y-2">
        <label className="text-sm font-medium">Search Scope</label>
        <div className="grid grid-cols-2 gap-3">
          <button
            type="button"
            onClick={() => setScope("approved_only")}
            className={cn(
              "flex flex-col items-start p-4 border rounded-xl text-left transition-all",
              scope === "approved_only"
                ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                : "border-border hover:border-primary/50 hover:bg-muted/50"
            )}
          >
            <span className="font-semibold text-sm">Approved Suppliers Only</span>
            <span className="text-xs text-muted-foreground mt-1">Search within company-approved and your saved suppliers.</span>
          </button>
          <button
            type="button"
            onClick={() => setScope("both")}
            className={cn(
              "flex flex-col items-start p-4 border rounded-xl text-left transition-all",
              scope === "both"
                ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                : "border-border hover:border-primary/50 hover:bg-muted/50"
            )}
          >
            <span className="font-semibold text-sm">Discover New Suppliers</span>
            <span className="text-xs text-muted-foreground mt-1">Search approved suppliers and search the web for new candidates.</span>
          </button>
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
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="inline-flex items-center justify-center p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
            title="Refresh example queries"
          >
            <RotateCw className={cn("w-3.5 h-3.5", isRefreshing && "animate-spin")} />
          </button>
          <div className="h-px flex-1 bg-border" />
        </div>
        <div className="grid gap-2">
          {examples.map((ex, i) => (
            <button
              key={i}
              onClick={() => setQuery(ex)}
              className="text-left text-sm p-3 rounded-lg border border-dashed border-zinc-200 dark:border-zinc-800 hover:border-zinc-400 dark:hover:border-zinc-600 hover:bg-zinc-50 dark:hover:bg-zinc-900/50 transition-colors text-muted-foreground hover:text-foreground"
            >
              "{ex}"
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
