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
export interface User {
  id: string; username: string; full_name: string; role: string; scope_level: string; scope_id: string | null; employee_id: string | null;
  must_change_password: boolean; last_login_at: string | null; password_changed_at: string | null;
}
export interface Suggestion { employee_id: string; name: string; verdict: string; covers: string[]; cost: number; reasons: string[]; actions: any[]; same_pod: boolean }

// Sessions live in an httpOnly cookie the page can't read. State-changing
// requests echo the CSRF token, which the server binds to that session.
const readCookie = (name: string) => document.cookie.split("; ").find((c) => c.startsWith(name + "="))?.split("=")[1] ?? "";
let csrf = "";
export const setCsrf = (t: string) => { csrf = t; };
const csrfToken = () => csrf || decodeURIComponent(readCookie("rosteros_csrf"));

export class ApiError extends Error {
  status: number; code?: string; failed?: string[];
  constructor(s: number, m: string, code?: string, failed?: string[]) { super(m); this.status = s; this.code = code; this.failed = failed; }
}

const PUBLIC = new Set(["/api/auth/login", "/api/auth/me", "/api/auth/password-policy"]);

export async function api<T = any>(path: string, opts: { method?: string; body?: any } = {}): Promise<T> {
  const method = opts.method || (opts.body ? "POST" : "GET");
  const res = await fetch(path, {
    method, credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(method !== "GET" ? { "X-CSRF-Token": csrfToken() } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && !PUBLIC.has(path)) window.dispatchEvent(new Event("rosteros:logout"));
  if (!res.ok) {
    let msg = res.statusText, code: string | undefined, failed: string[] | undefined;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") msg = j.detail;
      else if (Array.isArray(j.detail)) msg = j.detail.map((d: any) => d.msg).join("; ");
      else if (j.detail) { msg = j.detail.message || JSON.stringify(j.detail); code = j.detail.code; failed = j.detail.failed; }
    } catch { /* not json */ }
    if (code === "PASSWORD_CHANGE_REQUIRED") window.dispatchEvent(new Event("rosteros:must-change"));
    throw new ApiError(res.status, msg, code, failed);
  }
  return res.json();
}

export async function download(path: string, filename: string) {
  const res = await fetch(path, { credentials: "same-origin" });
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
export const canSeeTeam = (u: User | null) => !!u && ["SUPER_ADMIN", "OPS_MANAGER", "AUDITOR"].includes(u.role);
export const canSeeSecurity = canSeeTeam;
export const ROLE_HELP: Record<string, string> = {
  SUPER_ADMIN: "Everything, including team, solver settings and other admins",
  OPS_MANAGER: "Plans, generates and publishes rosters; manages leads, brand owners and employees",
  POD_LEAD: "Edits schedules and approves leave inside one pod",
  BRAND_OWNER: "Read-only view of one brand's coverage",
  EMPLOYEE: "Own schedule, requests leave",
  AUDITOR: "Read-only: rosters, audit log and security overview",
};

// Mirrors the server policy for instant feedback; the server stays the judge
// (it also checks a common-password list the browser never sees).
export interface Rule { id: string; label: string }
export function checkPassword(pw: string, minLength: number, username = "", fullName = ""): Set<string> {
  const failed = new Set<string>();
  if (pw.length < minLength) failed.add("length");
  if (pw.length > 128) failed.add("max");
  if (!/[a-z]/.test(pw)) failed.add("lower");
  if (!/[A-Z]/.test(pw)) failed.add("upper");
  if (!/\d/.test(pw)) failed.add("digit");
  if (!/[^A-Za-z0-9]/.test(pw)) failed.add("symbol");
  const low = pw.toLowerCase();
  const parts = `${username} ${fullName}`.toLowerCase().split(/[\s._@-]+/).filter((p) => p.length >= 3);
  if (parts.some((p) => low.includes(p))) failed.add("personal");
  if (/(.)\1{3,}/.test(low) || ["abcdefghijklmnopqrstuvwxyz", "qwertyuiopasdfghjklzxcvbnm", "01234567890"].some((seq) => {
    for (let i = 0; i < seq.length - 3; i++) { const c = seq.slice(i, i + 4); if (low.includes(c) || low.includes([...c].reverse().join(""))) return true; }
    return false;
  })) failed.add("pattern");
  return failed;
}
/** Rough strength (0-4) from length and character variety, for the meter only. */
export function strength(pw: string): number {
  if (!pw) return 0;
  const pool = (/[a-z]/.test(pw) ? 26 : 0) + (/[A-Z]/.test(pw) ? 26 : 0) + (/\d/.test(pw) ? 10 : 0) + (/[^A-Za-z0-9]/.test(pw) ? 33 : 0);
  const bits = pw.length * Math.log2(Math.max(pool, 1));
  return bits < 40 ? 1 : bits < 60 ? 2 : bits < 80 ? 3 : 4;
}
