/**
 * Custom hook for Server-Sent Events with JWT as URL query param.
 *
 * WHY URL PARAM?
 * EventSource (browser API) doesn't support custom headers.
 * Passing JWT in URL is the standard workaround for SSE + JWT auth.
 * Security note: URL params are logged by servers — use short-lived tokens
 * in production. For thesis prototype, this is acceptable.
 */

import { useEffect, useRef, useState } from "react";
import type { SSEEvent } from "@/types";
import { useAuthStore } from "@/store/authStore";

export interface ClarificationSignal {
  clarification_id: string;
  question: string;
  turn_number: number;
}

export function useSSE(queryId: string | null, resumeKey = 0) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarification, setClarification] = useState<ClarificationSignal | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const { accessToken } = useAuthStore();
  const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

  useEffect(() => {
    if (!queryId) return;

    // Reset state for new query
    setEvents([]);
    setIsComplete(false);
    setError(null);
    setClarification(null);

    // Close any existing connection
    if (sourceRef.current) {
      sourceRef.current.close();
    }

    // Include token as query param (SSE can't use headers)
    const tokenParam = accessToken ? `?token=${encodeURIComponent(accessToken)}` : "";
    const url = `${apiBaseUrl}/api/v1/queries/${queryId}/stream${tokenParam}`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.addEventListener("connected", () => {
      console.log("[SSE] Connected to query stream:", queryId);
    });

    source.addEventListener("agent_update", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent;
        setEvents((prev) => [...prev, data]);
      } catch {
        console.warn("[SSE] Failed to parse event:", e.data);
      }
    });

    source.addEventListener("complete", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent;
        setEvents((prev) => [...prev, { ...data, type: "complete" }]);
      } catch {
        // Ignored empty catch block
      }
      setIsComplete(true);
      source.close();
    });

    source.addEventListener("needs_clarification", (e: MessageEvent) => {
      // Task 3.3 — pipeline paused waiting for user reply. Surface the
      // question to the page so it can render the ClarificationCard.
      try {
        const data = JSON.parse(e.data);
        setClarification({
          clarification_id: data.clarification_id,
          question: data.question,
          turn_number: data.turn_number || 1,
        });
      } catch {
        console.warn("[SSE] Failed to parse needs_clarification:", e.data);
      }
      setIsComplete(true);
      source.close();
    });

    source.addEventListener("error", (e: MessageEvent) => {
      try {
        const msg = e.data ? JSON.parse(e.data).message : "Pipeline failed";
        setError(msg);
      } catch {
        setError("Pipeline failed");
      }
      setIsComplete(true);
      source.close();
    });

    // onerror fires when connection drops (not when server sends error event)
    source.onerror = (e) => {
      // If already complete, this is just cleanup
      if (!isComplete) {
        console.warn("[SSE] Connection error:", e);
        // Don't set error here — the pipeline might still be running
        // Poll for results as fallback
        setIsComplete(true);
      }
      source.close();
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryId, accessToken, resumeKey]);

  const reset = () => {
    setEvents([]);
    setIsComplete(false);
    setError(null);
    setClarification(null);
  };

  return { events, isComplete, error, clarification, reset };
}
