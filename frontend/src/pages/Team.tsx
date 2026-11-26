import { useEffect, useMemo, useState } from "react";
import { Copy, KeyRound, LockOpen, LogOut, Pencil, Plus, ShieldAlert, UserCheck, UserX } from "lucide-react";
import { api, ApiError, ROLE_HELP, ROLE_LABEL } from "../api";
import { useApp } from "../ctx";
import { Modal } from "../components/Modal";
import { PasswordField, PasswordRules } from "../components/Password";

interface Member {
  id: string; username: string; full_name: string; role: string; scope_level: string; scope_id: string | null;
  employee_id: string | null; active: boolean; locked: boolean; locked_until: string | null; must_change_password: boolean;
  has_password: boolean; failed_attempts: number; last_login_at: string | null; created_by: string | null; can_manage: boolean;
}
type Filter = "all" | "attention" | "inactive";

const ago = (iso: string | null) => {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};

function Status({ m }: { m: Member }) {
  if (!m.active) return <span className="tag neutral">Deactivated</span>;
  if (m.locked) return <span className="tag hard">Locked</span>;
  if (!m.has_password) return <span className="tag soft">No password yet</span>;
  if (m.must_change_password) return <span className="tag info">Awaiting first sign-in</span>;
  return <span className="tag ok">Active</span>;
}

export default function TeamPage() {
  const { user, toast, search } = useApp();
  const [members, setMembers] = useState<Member[]>([]);
  const [assignable, setAssignable] = useState<string[]>([]);
  const [pods, setPods] = useState<any[]>([]);
  const [brands, setBrands] = useState<any[]>([]);
  const [emps, setEmps] = useState<any[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [editing, setEditing] = useState<Partial<Member> | null>(null);
  const [secret, setSecret] = useState<{ username: string; password: string; reason: string } | null>(null);
  const [confirm, setConfirm] = useState<{ m: Member; action: string } | null>(null);

  const load = () => api("/api/team/users").then((r) => { setMembers(r.users); setAssignable(r.assignable_roles); })
    .catch((e) => toast(e.message, true));
  useEffect(() => {
    load();
    Promise.all([api("/api/pods"), api("/api/brands"), api("/api/employees")])
      .then(([p, b, e]) => { setPods(p); setBrands(b); setEmps(e); }).catch(() => {});
  }, []);

  const scopeName = (m: Member) => {
    if (m.scope_level === "POD") return pods.find((p) => p.id === m.scope_id)?.name ?? m.scope_id;
    if (m.scope_level === "BRAND") return brands.find((b) => b.id === m.scope_id)?.name ?? "brand";
    if (m.scope_level === "SELF") return emps.find((e) => e.id === m.employee_id)?.name ?? "own schedule";
    return "Whole company";
  };
  const attention = (m: Member) => m.active && (m.locked || !m.has_password || m.must_change_password);
  const q = search.trim().toLowerCase();
  const shown = members.filter((m) => (filter === "all" ? true : filter === "inactive" ? !m.active : attention(m))
    && (!q || m.username.includes(q) || m.full_name.toLowerCase().includes(q)));
  const counts = useMemo(() => ({
    active: members.filter((m) => m.active).length, attention: members.filter(attention).length,
    inactive: members.filter((m) => !m.active).length,
  }), [members]);

  const act = async (m: Member, action: string) => {
    try {
      const r = await api(`/api/team/users/${m.id}/${action}`, { method: "POST" });
      if (r.temporary_password) setSecret({ username: m.username, password: r.temporary_password, reason: "reset" });
      toast({ unlock: "Unlocked.", "revoke-sessions": "Signed out everywhere.", deactivate: "Deactivated; their sessions ended.",
              activate: "Reactivated.", "reset-password": "Password reset." }[action] || "Done.");
      load();
    } catch (e: any) { toast(e.message, true); }
    setConfirm(null);
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Team</h1><p>Who can sign in, with which role and scope. Every change here is audited, and permission changes take effect at once.</p></div>
        {assignable.length > 0 && <button className="btn primary" onClick={() => setEditing({ role: assignable[assignable.length - 1] })}><Plus size={16} />Add member</button>}
      </div>

      <div className="actions" style={{ justifyContent: "space-between" }}>
        <div className="seg" role="tablist" aria-label="Filter members">
          {([["all", `All ${members.length}`], ["attention", `Needs attention ${counts.attention}`], ["inactive", `Deactivated ${counts.inactive}`]] as [Filter, string][]).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
        <span className="subtle">{counts.active} active · roles you can grant: {assignable.map((r) => ROLE_LABEL[r]).join(", ") || "none (read-only)"}</span>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Member</th><th>Role</th><th>Scope</th><th>Status</th><th>Last sign-in</th><th aria-label="Actions" /></tr></thead>
          <tbody>
            {shown.map((m) => (
              <tr key={m.id} style={{ opacity: m.active ? 1 : .55 }}>
                <td><div className="emp-cell"><span className="avatar sm">{(m.full_name || m.username).split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase()}</span>
                  <div><b>{m.full_name || m.username}{m.id === user?.id ? " (you)" : ""}</b><small className="mono">{m.username}</small></div></div></td>
                <td><span className="tag neutral" title={ROLE_HELP[m.role]}>{ROLE_LABEL[m.role]}</span></td>
                <td>{scopeName(m)}</td>
                <td><Status m={m} />{m.failed_attempts > 0 && m.active && !m.locked && <small className="subtle" style={{ display: "block" }}>{m.failed_attempts} failed attempt(s)</small>}</td>
                <td className="subtle">{ago(m.last_login_at)}</td>
                <td>
                  {m.can_manage && (
                    <div className="row-actions">
                      <button className="icon-btn sm" title="Edit role or scope" aria-label={`Edit ${m.username}`} onClick={() => setEditing(m)}><Pencil size={15} /></button>
                      <button className="icon-btn sm" title="Issue a one-time password" aria-label={`Reset password for ${m.username}`} onClick={() => setConfirm({ m, action: "reset-password" })}><KeyRound size={15} /></button>
                      {m.locked && <button className="icon-btn sm" title="Unlock" aria-label={`Unlock ${m.username}`} onClick={() => act(m, "unlock")}><LockOpen size={15} /></button>}
                      <button className="icon-btn sm" title="Sign out everywhere" aria-label={`Sign out ${m.username} everywhere`} onClick={() => act(m, "revoke-sessions")}><LogOut size={15} /></button>
                      {m.active
                        ? <button className="icon-btn sm danger" title="Deactivate" aria-label={`Deactivate ${m.username}`} onClick={() => setConfirm({ m, action: "deactivate" })}><UserX size={15} /></button>
                        : <button className="icon-btn sm" title="Reactivate" aria-label={`Reactivate ${m.username}`} onClick={() => act(m, "activate")}><UserCheck size={15} /></button>}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {shown.length === 0 && <tr><td colSpan={6} className="empty">Nobody matches this filter.</td></tr>}
          </tbody>
        </table>
      </div>

      {editing && <MemberModal m={editing} assignable={assignable} pods={pods} brands={brands} emps={emps}
        onClose={() => setEditing(null)}
        onSaved={(username, pw) => { setEditing(null); load(); if (pw) setSecret({ username, password: pw, reason: "new" }); }} />}
      {secret && <SecretModal {...secret} onClose={() => setSecret(null)} />}
      {confirm && (
        <Modal title={confirm.action === "deactivate" ? `Deactivate ${confirm.m.full_name || confirm.m.username}?` : `Reset ${confirm.m.full_name || confirm.m.username}'s password?`} onClose={() => setConfirm(null)}>
          <p className="muted">{confirm.action === "deactivate"
            ? "They are signed out immediately and can't sign in until reactivated. Their roster history stays intact."
            : "Their current password stops working and every session ends. You'll get a one-time password to hand over privately; they must replace it at first sign-in."}</p>
          <div className="actions">
            <button className={`btn ${confirm.action === "deactivate" ? "danger" : "primary"}`} onClick={() => act(confirm.m, confirm.action)}>
              {confirm.action === "deactivate" ? <><UserX size={16} />Deactivate</> : <><KeyRound size={16} />Reset password</>}
            </button>
            <button className="btn ghost" onClick={() => setConfirm(null)}>Cancel</button>
          </div>
        </Modal>
      )}
    </>
  );
}

function MemberModal({ m, assignable, pods, brands, emps, onClose, onSaved }: {
  m: Partial<Member>; assignable: string[]; pods: any[]; brands: any[]; emps: any[];
  onClose: () => void; onSaved: (username: string, tempPassword: string | null) => void;
}) {
  const isNew = !m.id;
  const [fullName, setFullName] = useState(m.full_name || "");
  const [username, setUsername] = useState(m.username || "");
  const [touchedUser, setTouchedUser] = useState(false);
  const [role, setRole] = useState(m.role || assignable[0]);
  const [scopeId, setScopeId] = useState(m.scope_id || "");
  const [employeeId, setEmployeeId] = useState(m.employee_id || "");
  const [mode, setMode] = useState<"temp" | "set">("temp");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const roles = isNew ? assignable : Array.from(new Set([...(m.role ? [m.role] : []), ...assignable]));
  const level = { SUPER_ADMIN: "COMPANY", OPS_MANAGER: "COMPANY", AUDITOR: "COMPANY", POD_LEAD: "POD", BRAND_OWNER: "BRAND", EMPLOYEE: "SELF" }[role] || "COMPANY";

  const suggest = (name: string) => name.trim().toLowerCase().normalize("NFKD").replace(/[^a-z\s]/g, "").split(/\s+/).filter(Boolean).slice(0, 2).join(".");
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    const scope = level === "POD" || level === "BRAND" ? scopeId || null : null;
    const emp = level === "SELF" ? employeeId || null : null;
    try {
      if (isNew) {
        const r = await api("/api/team/users", { body: { username, full_name: fullName, role, scope_id: scope, employee_id: emp, password: mode === "set" ? password : null } });
        onSaved(username, r.temporary_password);
      } else {
        await api(`/api/team/users/${m.id}`, { method: "PATCH", body: { full_name: fullName, role, scope_id: scope, employee_id: emp } });
        onSaved(username, null);
      }
    } catch (err) { setError((err as ApiError).message); }
    finally { setBusy(false); }
  };

  return (
    <Modal title={isNew ? "Add a team member" : `Edit ${m.full_name || m.username}`} onClose={onClose}>
      <form className="pw-form" onSubmit={save} noValidate>
        {error && <div className="alert err" role="alert">{error}</div>}
        <div className="grid g2">
          <div className="field"><label htmlFor="m-name">Full name</label>
            <input id="m-name" className="input" value={fullName} maxLength={120} autoFocus
                   onChange={(e) => { setFullName(e.target.value); if (isNew && !touchedUser) setUsername(suggest(e.target.value)); }} /></div>
          <div className="field"><label htmlFor="m-user">Username</label>
            <input id="m-user" className="input mono" value={username} disabled={!isNew} maxLength={40} autoCapitalize="off" spellCheck={false}
                   onChange={(e) => { setTouchedUser(true); setUsername(e.target.value.toLowerCase()); }} />
            {isNew && <small className="subtle">Lowercase letters, numbers, dots, dashes.</small>}</div>
        </div>
        <div className="field"><label htmlFor="m-role">Role</label>
          <select id="m-role" className="input" value={role} onChange={(e) => { setRole(e.target.value); setScopeId(""); }}>
            {roles.map((r) => <option key={r} value={r} disabled={!assignable.includes(r)}>{ROLE_LABEL[r]}</option>)}
          </select>
          <small className="subtle">{ROLE_HELP[role]}</small></div>
        {level === "POD" && <div className="field"><label htmlFor="m-scope">Pod</label>
          <select id="m-scope" className="input" value={scopeId} onChange={(e) => setScopeId(e.target.value)}>
            <option value="">Choose a pod…</option>{pods.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>}
        {level === "BRAND" && <div className="field"><label htmlFor="m-scope">Brand</label>
          <select id="m-scope" className="input" value={scopeId} onChange={(e) => setScopeId(e.target.value)}>
            <option value="">Choose a brand…</option>{brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></div>}
        {level === "SELF" && <div className="field"><label htmlFor="m-emp">Employee record</label>
          <select id="m-emp" className="input" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">Choose the person…</option>{emps.filter((e) => e.active).map((e) => <option key={e.id} value={e.id}>{e.name} ({e.code})</option>)}</select>
          <small className="subtle">They will see their own schedule and the colleagues who cover their brands.</small></div>}
        {isNew && (
          <fieldset className="checks" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="subtle" style={{ marginBottom: 6 }}>First password</legend>
            <label className={`check ${mode === "temp" ? "on" : ""}`}><input type="radio" checked={mode === "temp"} onChange={() => setMode("temp")} />
              <div><b>Generate a one-time password</b><small className="subtle" style={{ display: "block" }}>Recommended. Shown once; they choose their own at first sign-in.</small></div></label>
            <label className={`check ${mode === "set" ? "on" : ""}`}><input type="radio" checked={mode === "set"} onChange={() => setMode("set")} />
              <div><b>Set one now</b><small className="subtle" style={{ display: "block" }}>They still replace it at first sign-in.</small></div></label>
          </fieldset>
        )}
        {isNew && mode === "set" && <>
          <PasswordField label="Password" value={password} onChange={setPassword} autoComplete="new-password" describedBy="m-rules" />
          <PasswordRules id="m-rules" password={password} username={username} fullName={fullName} />
        </>}
        <div className="actions">
          <button className="btn primary" disabled={busy}>{busy && <span className="spinner" />}{isNew ? "Create account" : "Save changes"}</button>
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
        </div>
        {!isNew && <p className="subtle"><ShieldAlert size={13} style={{ verticalAlign: -2 }} /> Changing role or scope signs them out so the new permissions apply immediately.</p>}
      </form>
    </Modal>
  );
}

function SecretModal({ username, password, reason, onClose }: { username: string; password: string; reason: string; onClose: () => void }) {
  const [shown, setShown] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => { try { await navigator.clipboard.writeText(password); setCopied(true); } catch { setShown(true); } };
  return (
    <Modal title={reason === "new" ? "Account created" : "One-time password issued"} onClose={onClose}>
      <p className="muted">Give this to <b>{username}</b> in person or over a private channel. It works once: they'll be asked to set their own password straight away. It won't be shown again.</p>
      <div className="secret">
        <code>{shown ? password : "•".repeat(password.length)}</code>
        <button className="btn sm ghost" onClick={() => setShown((s) => !s)}>{shown ? "Hide" : "Show"}</button>
        <button className="btn sm" onClick={copy}><Copy size={14} />{copied ? "Copied" : "Copy"}</button>
      </div>
      <button className="btn primary" onClick={onClose} style={{ alignSelf: "flex-start" }}>Done</button>
    </Modal>
  );
}
