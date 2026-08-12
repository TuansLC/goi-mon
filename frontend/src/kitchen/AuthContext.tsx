/** Kitchen auth context — stores JWT and slug in memory/localStorage */

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

interface AuthState {
  token: string | null;
  slug: string | null;
}

interface AuthContextValue {
  token: string | null;
  slug: string | null;
  setAuth: (token: string | null, slug: string) => void;
  logout: () => void;
}

const STORAGE_KEY = "qorder_kitchen_auth";

function loadFromStorage(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { token: parsed.token || null, slug: parsed.slug || null };
    }
  } catch { /* ignore */ }
  return { token: null, slug: null };
}

function saveToStorage(state: AuthState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function KitchenAuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<AuthState>(loadFromStorage);

  const setAuth = useCallback((token: string | null, slug: string) => {
    const state = { token, slug };
    setAuthState(state);
    saveToStorage(state);
  }, []);

  const logout = useCallback(() => {
    setAuthState({ token: null, slug: null });
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <AuthContext.Provider value={{ token: auth.token, slug: auth.slug, setAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useKitchenAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useKitchenAuth must be used inside KitchenAuthProvider");
  return ctx;
}
