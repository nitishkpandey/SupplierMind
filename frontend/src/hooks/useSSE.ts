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

export function useSSE(queryId: string | null) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const { accessToken } = useAuthStore();

  useEffect(() => {
    if (!queryId) return;

    // Close any existing connection
    if (sourceRef.current) {
      sourceRef.current.close();
    }

    // Include token as query param (SSE can't use headers)
    const tokenParam = accessToken ? `?token=${encodeURIComponent(accessToken)}` : "";
    const url = `http://localhost:8000/api/v1/queries/${queryId}/stream${tokenParam}`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.addEventListener("connected", () => {
      console.log("[SSE] Connected to query stream:", queryId);
    });

    source.addEventListener("agent_update", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent;
        setEvents((prev) => [...prev, data]);
      } catch (err) {
        console.warn("[SSE] Failed to parse event:", e.data);
      }
    });

    source.addEventListener("complete", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent;
        setEvents((prev) => [...prev, { type: "complete", ...data }]);
      } catch {}
      setIsComplete(true);
      source.close();
    });

    source.addEventListener("error", (e: MessageEvent) => {
      const msg = e.data ? JSON.parse(e.data).message : "Pipeline failed";
      setError(msg);
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
  }, [queryId]);

  return { events, isComplete, error };
}
