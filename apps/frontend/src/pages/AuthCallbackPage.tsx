/**
 * Handles the OAuth callback redirect from the backend.
 *
 * Backend redirects here after OAuth success:
 * /auth/callback?access_token=XXX&refresh_token=YYY&role=ZZZ
 *
 * This page:
 * 1. Extracts tokens from URL params
 * 2. Fetches user profile from /auth/me
 * 3. Stores in Zustand + sessionStorage
 * 4. Redirects to dashboard
 */

import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { api } from "@/services/api";
import type { User } from "@/types";

export default function AuthCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();

  useEffect(() => {
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");
    const error = params.get("error");

    if (error || !accessToken) {
      navigate("/login?error=" + (error || "no_token"));
      return;
    }

    // Store refresh token in sessionStorage (survives page refresh, not tab close)
    if (refreshToken) {
      sessionStorage.setItem("sm_refresh_token", refreshToken);
    }

    // Set temporary auth so /auth/me call has a token
    api.defaults.headers.common["Authorization"] = `Bearer ${accessToken}`;

    // Fetch user profile
    api.get<User>("/auth/me")
      .then((res) => {
        setAuth(accessToken, res.data);
        navigate("/dashboard", { replace: true });
      })
      .catch(() => {
        navigate("/login?error=profile_failed");
      });
  }, [navigate, params, setAuth]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900">
      <div className="text-center space-y-3">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-slate-400 text-sm">Signing you in...</p>
      </div>
    </div>
  );
}
