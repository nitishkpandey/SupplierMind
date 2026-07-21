import axios from "axios";
import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { AppLayout } from "@/features/layout/AppLayout";
import type { User } from "@/types";

const LoginPage = lazy(() => import("@/pages/LoginPage"));
const AuthCallbackPage = lazy(() => import("@/pages/AuthCallbackPage"));
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const QueryPage = lazy(() => import("@/pages/QueryPage"));
const ResultsPage = lazy(() => import("@/pages/ResultsPage"));
const HistoryPage = lazy(() => import("@/pages/HistoryPage"));
const AdminPage = lazy(() => import("@/pages/AdminPage"));
const AdminMetricsPage = lazy(() => import("@/pages/AdminMetricsPage"));
const MySuppliersPage = lazy(() => import("@/pages/MySuppliersPage"));

function toUser(payload: {
  user_id: string;
  email: string;
  name: string;
  role: User["role"];
}): User {
  return {
    id: payload.user_id,
    email: payload.email,
    name: payload.name,
    role: payload.role,
  };
}

function PageSpinner() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, setAuth, clearAuth } = useAuthStore();
  const [isCheckingSession, setIsCheckingSession] = useState(
    () => !isAuthenticated && Boolean(sessionStorage.getItem("sm_refresh_token"))
  );

  useEffect(() => {
    if (isAuthenticated) {
      return;
    }

    const refreshToken = sessionStorage.getItem("sm_refresh_token");
    if (!refreshToken) {
      return;
    }

    let cancelled = false;
    axios
      .post("/api/v1/auth/refresh", { refresh_token: refreshToken })
      .then((res) => {
        if (cancelled) return;
        setAuth(res.data.access_token, toUser(res.data));
      })
      .catch(() => {
        if (cancelled) return;
        clearAuth();
        sessionStorage.removeItem("sm_refresh_token");
      })
      .finally(() => {
        if (!cancelled) {
          setIsCheckingSession(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [clearAuth, isAuthenticated, setAuth]);

  if (isCheckingSession) {
    return <PageSpinner />;
  }

  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
}

function AdminRoute({ children }: { children: ReactNode }) {
  const { user } = useAuthStore();
  return user?.role === "admin" ? (
    <>{children}</>
  ) : (
    <Navigate to="/dashboard" replace />
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageSpinner />}>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />

          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="query" element={<QueryPage />} />
            <Route path="query/:queryId/results" element={<ResultsPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="my-suppliers" element={<MySuppliersPage />} />
            <Route
              path="admin"
              element={
                <AdminRoute>
                  <AdminPage />
                </AdminRoute>
              }
            />
            <Route
              path="admin/metrics"
              element={
                <AdminRoute>
                  <AdminMetricsPage />
                </AdminRoute>
              }
            />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
