import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setCsrf, type Conflict, type Grid, type User } from "./api";

interface Toast { id: number; msg: string; err?: boolean }
interface Ctx {
  user: User | null;
  authChecked: boolean;              // false until /api/auth/me has answered
  login: (user: User, csrf: string) => void;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  month: string;
  setMonth: (m: string) => void;
  grid: Grid | null;
  gridLoading: boolean;
  rosterId: string | null;          // explicit version being viewed (null = current)
  setRosterId: (id: string | null) => void;
  reload: () => Promise<void>;
  toast: (msg: string, err?: boolean) => void;
  toasts: Toast[];
  conflict: Conflict | null;
  openConflict: (c: Conflict | null) => void;
  search: string;
  setSearch: (s: string) => void;
}

const C = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(C);

const initialMonth = () => {
  const d = new Date();
  const next = new Date(d.getFullYear(), d.getMonth() + 1, 1);   // plan ahead: next month
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
};

export function AppProvider({ children }: { children: ReactNode }) {
  // No profile or token in localStorage: the httpOnly session cookie is the
  // only credential, and who-am-I always comes from the server.
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [month, setMonth] = useState(() => {
    try { return localStorage.getItem("rosteros.month") || initialMonth(); } catch { return initialMonth(); }
  });
  const [grid, setGrid] = useState<Grid | null>(null);
  const [gridLoading, setGridLoading] = useState(false);
  const [rosterId, setRosterId] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [conflict, openConflict] = useState<Conflict | null>(null);
  const [search, setSearch] = useState("");

  const toast = useCallback((msg: string, err = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, err }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), err ? 6000 : 3500);
  }, []);

  const clearSession = useCallback(() => { setCsrf(""); setUser(null); setGrid(null); }, []);
  const logout = useCallback(async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } catch { /* already signed out */ }
    clearSession();
  }, [clearSession]);
  const refreshUser = useCallback(async () => {
    try { setUser(await api<User>("/api/auth/me")); } catch { clearSession(); } finally { setAuthChecked(true); }
  }, [clearSession]);
  useEffect(() => { refreshUser(); }, [refreshUser]);
  useEffect(() => {
    const out = () => clearSession();
    const must = () => setUser((u) => (u ? { ...u, must_change_password: true } : u));
    window.addEventListener("rosteros:logout", out);
    window.addEventListener("rosteros:must-change", must);
    return () => { window.removeEventListener("rosteros:logout", out); window.removeEventListener("rosteros:must-change", must); };
  }, [clearSession]);

  const reload = useCallback(async () => {
    if (!user || user.must_change_password) return;
    setGridLoading(true);
    try {
      const g = rosterId ? await api<Grid>(`/api/rosters/${rosterId}/grid`)
                         : await api<Grid | { roster: null }>(`/api/rosters/current?month=${month}`);
      setGrid(g.roster ? (g as Grid) : null);
    } catch (e: any) {
      toast(e.message, true);
      setGrid(null);
    } finally {
      setGridLoading(false);
    }
  }, [user, month, rosterId, toast]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { try { localStorage.setItem("rosteros.month", month); } catch { /* storage off */ } setRosterId(null); }, [month]);

  const value = useMemo<Ctx>(() => ({
    user, authChecked,
    login: (u, c) => { setCsrf(c); setUser(u); setAuthChecked(true); },
    logout, refreshUser, month, setMonth, grid, gridLoading, rosterId, setRosterId, reload, toast, toasts,
    conflict, openConflict, search, setSearch,
  }), [user, authChecked, logout, refreshUser, month, grid, gridLoading, rosterId, reload, toast, toasts, conflict, search]);

  return <C.Provider value={value}>{children}</C.Provider>;
}
