import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setToken, type Conflict, type Grid, type User } from "./api";

interface Toast { id: number; msg: string; err?: boolean }
interface Ctx {
  user: User | null;
  login: (token: string, user: User) => void;
  logout: () => void;
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
  const [user, setUser] = useState<User | null>(() => {
    try { return JSON.parse(localStorage.getItem("rosteros.user") || "null"); } catch { return null; }
  });
  const [month, setMonth] = useState(() => localStorage.getItem("rosteros.month") || initialMonth());
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

  const logout = useCallback(() => {
    setToken(""); localStorage.removeItem("rosteros.user"); setUser(null); setGrid(null);
  }, []);
  useEffect(() => {
    const h = () => logout();
    window.addEventListener("rosteros:logout", h);
    return () => window.removeEventListener("rosteros:logout", h);
  }, [logout]);

  const reload = useCallback(async () => {
    if (!user) return;
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
  useEffect(() => { localStorage.setItem("rosteros.month", month); setRosterId(null); }, [month]);

  const value = useMemo<Ctx>(() => ({
    user,
    login: (t, u) => { setToken(t); localStorage.setItem("rosteros.user", JSON.stringify(u)); setUser(u); },
    logout, month, setMonth, grid, gridLoading, rosterId, setRosterId, reload, toast, toasts,
    conflict, openConflict, search, setSearch,
  }), [user, logout, month, grid, gridLoading, rosterId, reload, toast, toasts, conflict, search]);

  return <C.Provider value={value}>{children}</C.Provider>;
}
