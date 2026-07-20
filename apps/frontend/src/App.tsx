import axios from "axios";
import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { AppLayout } from "@/features/layout/AppLayout";
import LoginPage from "@/pages/LoginPage";
import AuthCallbackPage from "@/pages/AuthCallbackPage";
import DashboardPage from "@/pages/DashboardPage";
import QueryPage from "@/pages/QueryPage";
import ResultsPage from "@/pages/ResultsPage";
import HistoryPage from "@/pages/HistoryPage";
import AdminPage from "@/pages/AdminPage";
import AdminMetricsPage from "@/pages/AdminMetricsPage";
import MySuppliersPage from "@/pages/MySuppliersPage";
import type { User } from "@/types";

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

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, setAuth, clearAuth } = useAuthStore();
  const [isCheckingSession, setIsCheckingSession] = useState(
    () => !isAuthenticated && Boolean(sessionStorage.getItem("sm_refresh_token"))
  );

  useEffect(() => {
    if (isAuthenticated) {
      setIsCheckingSession(false);
      return;
    }

    const refreshToken = sessionStorage.getItem("sm_refresh_token");
    if (!refreshToken) {
      setIsCheckingSession(false);
      return;
    }

    let cancelled = false;
    setIsCheckingSession(true);
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
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
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
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/callback" element={<AuthCallbackPage />} />

        {/* Protected routes */}
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
    </BrowserRouter>
  );
}
