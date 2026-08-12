/** Admin auth context — stores JWT in localStorage */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";

interface AuthState {
  token: string | null;
}

interface AdminAuthContextValue {
  token: string | null;
  setToken: (token: string | null) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const STORAGE_KEY = "qorder_admin_auth";

function loadFromStorage(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { token: parsed.token || null };
    }
  } catch {
    /* ignore */
  }
  return { token: null };
}

function saveToStorage(state: AuthState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

const AdminAuthContext = createContext<AdminAuthContextValue | null>(null);

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<AuthState>(loadFromStorage);

  const setToken = useCallback((token: string | null) => {
    const state = { token };
    setAuthState(state);
    saveToStorage(state);
  }, []);

  const logout = useCallback(() => {
    setAuthState({ token: null });
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <AdminAuthContext.Provider
      value={{ token: auth.token, setToken, logout, isAuthenticated: !!auth.token }}
    >
      {children}
    </AdminAuthContext.Provider>
  );
}

export function useAdminAuth(): AdminAuthContextValue {
  const ctx = useContext(AdminAuthContext);
  if (!ctx)
    throw new Error("useAdminAuth must be used inside AdminAuthProvider");
  return ctx;
}
