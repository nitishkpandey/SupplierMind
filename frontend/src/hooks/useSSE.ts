/**
 * Custom hook for Server-Sent Events.
 * Connects to /queries/{id}/stream and emits live agent progress.
 */

import { useEffect, useState } from "react";
import type { SSEEvent } from "@/types";

export function useSSE(queryId: string | null, accessToken: string | null) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!queryId || !accessToken) return;

    // EventSource doesn't support custom headers — use URL param token for SSE
    // In production, use a short-lived SSE token. For prototype, this works.
    const url = `http://localhost:8000/api/v1/queries/${queryId}/stream`;
    const source = new EventSource(url);

    source.addEventListener("connected", (e) => {
      console.log("SSE connected:", e.data);
    });

    source.addEventListener("agent_update", (e) => {
      const data = JSON.parse(e.data) as SSEEvent;
      setEvents((prev) => [...prev, data]);
    });

    source.addEventListener("complete", (e) => {
      const data = JSON.parse(e.data) as SSEEvent;
      setEvents((prev) => [...prev, { ...data, type: "complete" }]);
      setIsComplete(true);
      source.close();
    });

    source.addEventListener("error", (e: any) => {
      const msg = e.data ? JSON.parse(e.data).message : "Connection error";
      setError(msg);
      setIsComplete(true);
      source.close();
    });

    source.onerror = () => {
      // SSE closed normally after completion
      source.close();
    };

    return () => source.close();
  }, [queryId, accessToken]);

  return { events, isComplete, error };
}
