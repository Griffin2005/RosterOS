// Thin typed client for the RosterOS API.
export type Status = "WORK" | "WEEK_OFF" | "HOLIDAY" | "LEAVE" | "COMP_OFF";

export interface CellT { status: Status; covers: Record<string, boolean>; source: string; locked: boolean; holiday: boolean }
export interface EmployeeRow {
  id: string; code: string; name: string; pod_id: string; is_lead: boolean; preferred_off: number[];
  cells: (CellT | null)[]; assignments: { line_id: string; role: string; load: number }[];
}
export interface CoverageRow {
  line_id: string; label: string; brand_id: string; brand: string; process: string; pod_id: string; calendar: string;
  days: { req: number; heads: string[] }[]; assignees: { employee_id: string; role: string; load: number }[];
}
export interface Conflict {
  code: string; name: string; severity: "HARD" | "SOFT" | "INFO"; title: string; detail: string; key: string;
  date: string | null; line_id: string | null; employee_id: string | null; brand_id: string | null;
  explanation: any; acknowledged?: { reason: string; by: string } | null;
}
export interface RosterMeta {
  id: string; month: string; version: number; status: string; kind: string; note: string; parent_id: string | null;
  rule_set_version: number | null; created_by: string | null; created_at: string | null; published_at: string | null;
  stats: any;
}
export interface Grid {
  roster: RosterMeta; days: string[]; pods: { id: string; name: string; lead_id: string | null }[];
  employees: EmployeeRow[]; coverage: CoverageRow[]; conflicts: Conflict[];
  summary: { HARD: number; SOFT: number; INFO: number }; risks: Conflict[]; impossible: any[]; holidays: string[];
  scoped?: boolean;
}
export interface User { id: string; username: string; role: string; scope_level: string; scope_id: string | null; employee_id: string | null }
export interface Suggestion { employee_id: string; name: string; verdict: string; covers: string[]; cost: number; reasons: string[]; actions: any[]; same_pod: boolean }

let token = localStorage.getItem("rosteros.token") || "";
export const setToken = (t: string) => { token = t; t ? localStorage.setItem("rosteros.token", t) : localStorage.removeItem("rosteros.token"); };

export class ApiError extends Error { status: number; constructor(s: number, m: string) { super(m); this.status = s; } }

export async function api<T = any>(path: string, opts: { method?: string; body?: any } = {}): Promise<T> {
  const res = await fetch(path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && path !== "/api/auth/login") { setToken(""); window.dispatchEvent(new Event("rosteros:logout")); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* not json */ }
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export async function download(path: string, filename: string) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function waitJob(id: string): Promise<{ status: string; roster_id: string | null; error: string | null }> {
  for (let i = 0; i < 400; i++) {
    const j = await api(`/api/jobs/${id}`);
    if (j.status === "DONE" || j.status === "FAILED") return j;
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error("The solver is taking longer than expected.");
}

export const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const weekday = (iso: string) => (new Date(iso + "T00:00:00").getDay() + 6) % 7;
export const fmtDay = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" });
export const STATUS_LABEL: Record<Status, string> = { WORK: "Working", WEEK_OFF: "Weekly off", HOLIDAY: "Holiday", LEAVE: "Leave", COMP_OFF: "Comp-off" };
export const STATUS_SHORT: Record<Status, string> = { WORK: "W", WEEK_OFF: "WO", HOLIDAY: "PH", LEAVE: "L", COMP_OFF: "CO" };
export const ROLE_LABEL: Record<string, string> = {
  SUPER_ADMIN: "Super Admin", OPS_MANAGER: "Ops Manager", POD_LEAD: "Pod Lead", BRAND_OWNER: "Brand Owner", EMPLOYEE: "Employee", AUDITOR: "Auditor",
};
export const canManage = (u: User | null) => !!u && ["SUPER_ADMIN", "OPS_MANAGER"].includes(u.role);
export const canEditRoster = (u: User | null) => !!u && ["SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD"].includes(u.role);
