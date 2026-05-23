/**
 * Zustand auth store — JWT stored in MEMORY, not localStorage.
 *
 * WHY NOT localStorage?
 * localStorage is accessible by any JavaScript on the page.
 * If a 3rd-party script is compromised (XSS attack), it reads your token.
 * In-memory storage disappears when the tab closes — safer for auth tokens.
 *
 * Tradeoff: User must re-login after closing the browser tab.
 * Mitigated by: refresh token flow (handled in api.ts interceptor).
 */

import { create } from "zustand";
import type { AuthState, User } from "@/types";

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,

  setAuth: (token: string, user: User) =>
    set({ accessToken: token, user, isAuthenticated: true }),

  clearAuth: () =>
    set({ accessToken: null, user: null, isAuthenticated: false }),
}));
