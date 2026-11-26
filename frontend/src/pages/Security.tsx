import { useEffect, useState } from "react";
import { Fingerprint, Globe, KeyRound, LockKeyhole, ShieldCheck, Timer, UserCog } from "lucide-react";
import { api, ROLE_LABEL } from "../api";
import { useApp } from "../ctx";

const ACTION: Record<string, { label: string; tone: string }> = {
  LOGIN_SUCCEEDED: { label: "Signed in", tone: "ok" }, LOGIN_FAILED: { label: "Failed sign-in", tone: "soft" },
  LOGIN_THROTTLED: { label: "Rate limited", tone: "hard" }, ACCOUNT_LOCKED: { label: "Account locked", tone: "hard" },
  ACCOUNT_UNLOCKED: { label: "Unlocked", tone: "info" }, PASSWORD_CHANGED: { label: "Password changed", tone: "info" },
  PASSWORD_RESET: { label: "Password reset", tone: "info" }, USER_CREATED: { label: "Member added", tone: "info" },
  USER_UPDATED: { label: "Member changed", tone: "info" }, USER_DEACTIVATED: { label: "Deactivated", tone: "neutral" },
  USER_ACTIVATED: { label: "Reactivated", tone: "info" }, SESSIONS_REVOKED: { label: "Sessions ended", tone: "neutral" },
  LOGOUT: { label: "Signed out", tone: "neutral" }, EXPORT_DOWNLOADED: { label: "Export", tone: "neutral" },
  ASSISTANT_QUERY: { label: "Assistant query", tone: "neutral" },
};
const RULE_ORDER = ["length", "lower", "upper", "digit", "symbol", "personal", "common", "pattern"];

export default function SecurityPage() {
  const { toast } = useApp();
  const [o, setO] = useState<any>(null);
  useEffect(() => { api("/api/security/overview").then(setO).catch((e) => toast(e.message, true)); }, []);
  if (!o) return <div className="card empty"><span className="spinner" /></div>;
  const ev = o.events_24h;
  const detail = (e: any) => {
    const d = e.detail || {};
    return [d.username, d.reason?.replace("_", " "), d.format, d.role && ROLE_LABEL[d.role], d.ip].filter(Boolean).join(" · ");
  };
  return (
    <>
      <div className="page-head">
        <div><h1>Security</h1><p>The controls protecting this deployment, read live from its configuration and audit log.</p></div>
        <span className={`tag ${o.environment.production ? "ok" : "soft"}`}>{o.environment.production ? "Production mode" : "Development mode"}</span>
      </div>

      <div className="grid g4">
        <div className="card kpi hero"><span className="lab">Active accounts</span><span className="val">{o.accounts.active}</span>
          <span className="foot">{o.accounts.total} total · {o.accounts.disabled_no_password} without a password</span></div>
        <div className="card kpi"><span className="lab">Sign-ins, 24 h</span><span className="val">{ev.LOGIN_SUCCEEDED}</span>
          <span className="foot">{ev.LOGOUT} sign-outs</span></div>
        <div className="card kpi"><span className="lab">Failed sign-ins, 24 h</span><span className="val" style={{ color: ev.LOGIN_FAILED ? "var(--warn)" : undefined }}>{ev.LOGIN_FAILED}</span>
          <span className="foot">{ev.LOGIN_THROTTLED} rate-limited</span></div>
        <div className="card kpi"><span className="lab">Locked now</span><span className="val" style={{ color: o.accounts.locked ? "var(--crit)" : undefined }}>{o.accounts.locked}</span>
          <span className="foot">{ev.ACCOUNT_LOCKED} lockouts in 24 h · {o.accounts.must_change} awaiting first sign-in</span></div>
      </div>

      <div className="grid g3">
        <div className="card control"><KeyRound size={20} /><h3>Password storage</h3>
          <p><b>{o.hashing.algorithm}</b>, memory {Math.round(o.hashing.memory_kib / 1024)} MiB, {o.hashing.time_cost} iterations, parallelism {o.hashing.parallelism}. Unique salt per password; plaintext is never stored or logged.</p>
          <span className={`tag ${o.hashing.legacy_hashes ? "soft" : "ok"}`}>{o.hashing.legacy_hashes ? `${o.hashing.legacy_hashes} legacy hash(es) upgrade at next sign-in` : "All hashes current"}</span></div>
        <div className="card control"><Fingerprint size={20} /><h3>Password policy</h3>
          <ul className="ticks">{RULE_ORDER.map((id) => o.policy.rules.find((r: any) => r.id === id)).filter(Boolean).map((r: any) => <li key={r.id}>{r.label}</li>)}</ul></div>
        <div className="card control"><Timer size={20} /><h3>Brute-force protection</h3>
          <p>Accounts lock for <b>{o.lockout.minutes} minutes</b> after <b>{o.lockout.max_failures}</b> failed attempts. Each network gets {o.lockout.ip_rate_per_minute} sign-in attempts a minute. Unknown usernames get the same answer and timing as wrong passwords.</p></div>
        <div className="card control"><LockKeyhole size={20} /><h3>Sessions</h3>
          <p>Cookie: <b>{o.sessions.cookie}</b>. {o.sessions.csrf}. Lifetime {o.sessions.ttl_minutes / 60} h.</p><p className="subtle">{o.sessions.revocation}.</p></div>
        <div className="card control"><Globe size={20} /><h3>HTTP hardening</h3>
          <ul className="ticks">{o.headers.map((h: string) => <li key={h}>{h}</li>)}</ul>
          <p className="subtle">API docs {o.environment.api_docs_public ? "visible (development only)" : "disabled"}.</p></div>
        <div className="card control"><UserCog size={20} /><h3>Least privilege</h3>
          <p>{Object.entries(o.accounts.by_role).map(([r, n]) => `${n} ${ROLE_LABEL[r]}`).join(" · ")}.</p>
          <p className="subtle">Nobody grants a role at or above their own; the last active super admin can't be demoted or deactivated; role changes end existing sessions.</p></div>
      </div>

      <div className="grid g-dash">
        <div className="card">
          <div className="card-head"><h2>Recent security events</h2><span className="subtle">IP addresses are stored as keyed hashes</span></div>
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table className="data">
              <thead><tr><th>When</th><th>Event</th><th>Who</th><th>Detail</th></tr></thead>
              <tbody>
                {o.recent.map((e: any) => (
                  <tr key={e.id}>
                    <td className="subtle">{new Date(e.at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                    <td><span className={`tag ${ACTION[e.action]?.tone || "neutral"}`}>{ACTION[e.action]?.label || e.action}</span></td>
                    <td className="mono">{e.actor}</td>
                    <td className="subtle">{detail(e)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Privacy commitments</h2><ShieldCheck size={18} color="var(--g-700)" /></div>
          <ul className="ticks">{o.privacy.map((p: string) => <li key={p}>{p}</li>)}</ul>
        </div>
      </div>
    </>
  );
}
