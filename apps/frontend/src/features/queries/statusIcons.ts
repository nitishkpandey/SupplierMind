import { AlertCircle, CheckCircle, Clock, XCircle } from "lucide-react";

// Single source of truth for query-status icon + color (Dashboard, History).
export const QUERY_STATUS_ICONS = {
  completed: { icon: CheckCircle, color: "text-green-500" },
  failed: { icon: XCircle, color: "text-red-500" },
  pending: { icon: Clock, color: "text-yellow-500" },
  processing: { icon: Clock, color: "text-blue-500" },
  needs_clarification: { icon: AlertCircle, color: "text-amber-500" },
} as const;

export function queryStatusIcon(status: string) {
  return (
    QUERY_STATUS_ICONS[status as keyof typeof QUERY_STATUS_ICONS] ??
    QUERY_STATUS_ICONS.pending
  );
}
