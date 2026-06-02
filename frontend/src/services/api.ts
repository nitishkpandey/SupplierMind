/**
 * Axios instance with JWT injection and auto-refresh.
 *
 * INTERCEPTOR PATTERN:
 * Instead of manually adding "Authorization: Bearer ..." to every request,
 * the request interceptor runs automatically before EVERY API call.
 * Single point of JWT management — DRY principle.
 *
 * REFRESH FLOW:
 * If a request fails with 401 (token expired):
 * 1. Try to refresh using the refresh token (stored in httpOnly cookie ideally,
 *    but for this prototype stored in sessionStorage)
 * 2. If refresh succeeds: retry the original request with new token
 * 3. If refresh fails: redirect to login
 */

import axios from "axios";
import type { AxiosInstance, InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "@/store/authStore";

const BASE_URL = "/api/v1";

export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 320000, // 320s — backend pipeline timeout is 300s, frontend gives it a small margin
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor: inject JWT on every call
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = useAuthStore.getState().accessToken;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: handle 401 with token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      // Attempt refresh
      const refreshToken = sessionStorage.getItem("sm_refresh_token");
      if (refreshToken) {
        try {
          const res = await axios.post(`${BASE_URL}/auth/refresh`, {
            refresh_token: refreshToken,
          });
          const newToken = res.data.access_token;
          useAuthStore.getState().setAuth(newToken, res.data);
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
          return api(originalRequest);
        } catch {
          // Refresh failed → logout
          useAuthStore.getState().clearAuth();
          sessionStorage.removeItem("sm_refresh_token");
          window.location.href = "/login";
        }
      } else {
        useAuthStore.getState().clearAuth();
        window.location.href = "/login";
      }
    }

    return Promise.reject(error);
  }
);

// Query service methods
export const queryService = {
  submit: (rawQuery: string, scope: 'approved_only' | 'both' = 'approved_only') =>
    api.post<{ id: string; status: string }>("/queries", { raw_query: rawQuery, search_scope: scope }),

  getResult: (queryId: string) =>
    api.get(`/queries/${queryId}`),

  getHistory: (page = 1) =>
    api.get(`/queries?offset=${(page - 1) * 20}&limit=20`),

  getAuditTrail: (queryId: string) =>
    api.get(`/queries/${queryId}/audit`),
};

// Supplier service methods
export const supplierService = {
  getById: (id: string) => api.get<{ id: string }>(`/suppliers/${id}`),
  list: (page = 1) => api.get(`/suppliers?offset=${(page - 1) * 20}&limit=20`),
};

// Production v2: Tier workflow service
export const supplierWorkflowService = {
  getMyList: (page = 1) => api.get(`/suppliers/my-list?offset=${(page - 1) * 20}&limit=20`),
  save: (id: string) => api.post(`/suppliers/${id}/save`),
  unsave: (id: string) => api.delete(`/suppliers/${id}/save`),
  approve: (id: string, justification: string) =>
    api.post(`/suppliers/${id}/approve`, { justification }),
  reject: (id: string, justification: string) =>
    api.post(`/suppliers/${id}/reject`, { justification }),
};

// Auth service methods
export const authService = {
  getMe: () => api.get("/auth/me"),
  logout: () => {
    useAuthStore.getState().clearAuth();
    sessionStorage.removeItem("sm_refresh_token");
  },
};

// Evaluation service
export const evalService = {
  getResults: () => api.get("/eval/results"),
  getReport: () => api.get("/eval/report"),
  triggerRun: (baselinesOnly = false) =>
    api.post("/eval/run", null, { params: { baselines_only: baselinesOnly } }),
};

// Task 2.5 — admin operational metrics
export interface AgentLatency {
  agent_name: string;
  p50_ms: number;
  p95_ms: number;
  mean_ms: number;
  count: number;
}

export interface AdminMetrics {
  window_hours: number;
  as_of: string;
  summary: {
    total_queries: number;
    total_agent_invocations: number;
    total_human_decisions: number;
    queries_with_errors: number;
  };
  agent_latency: AgentLatency[];
  throttle_events: {
    groq_429_count: number;
    groq_pacing_events: number;
    sanctions_pending_review: number;
  };
  recent_errors: Array<{
    timestamp: string | null;
    agent_name: string;
    action: string;
    query_id: string | null;
    reasoning: string;
  }>;
}

export const metricsService = {
  get: (windowHours: number) =>
    api.get<AdminMetrics>(`/admin/metrics?window_hours=${windowHours}`),
};
