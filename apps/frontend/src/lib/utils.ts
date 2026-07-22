import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { User } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Backend origin for absolute URLs (OAuth redirects, SSE) — "" in dev (Vite proxy). */
export const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

/** Approve/reject is manager-gated; analysts are read-only. */
export function canModerate(user: User | null | undefined): boolean {
  return user?.role === "admin" || user?.role === "procurement_manager";
}
