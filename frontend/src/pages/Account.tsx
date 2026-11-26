import { useState } from "react";
import { KeyRound, LogOut, ShieldCheck } from "lucide-react";
import { api, ApiError, ROLE_HELP, ROLE_LABEL } from "../api";
import { useApp } from "../ctx";
import { PasswordField, PasswordRules, usePolicy } from "../components/Password";
import { Logo } from "./Landing";

export function ChangePasswordForm({ forced = false, onDone }: { forced?: boolean; onDone?: () => void }) {
  const { user, login, toast } = useApp();
  const policy = usePolicy();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mismatch = confirm.length > 0 && confirm !== next;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!current || !next) { setError("Fill in every field."); return; }
    if (next !== confirm) { setError("The new passwords don't match."); return; }
    setBusy(true);
    try {
      const r = await api("/api/auth/change-password", { body: { current_password: current, new_password: next } });
      login(r.user, r.csrf);
      setCurrent(""); setNext(""); setConfirm("");
      toast("Password changed. Other sessions were signed out.");
      onDone?.();
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="pw-form" onSubmit={submit} noValidate>
      {error && <div className="alert err" role="alert">{error}</div>}
      <PasswordField label={forced ? "Temporary password" : "Current password"} value={current} onChange={setCurrent}
                     autoComplete="current-password" autoFocus={forced} />
      <PasswordField label="New password" value={next} onChange={setNext} autoComplete="new-password" describedBy="pw-rules" />
      <PasswordRules id="pw-rules" password={next} username={user?.username} fullName={user?.full_name} />
      <PasswordField label="Confirm new password" value={confirm} onChange={setConfirm} autoComplete="new-password" invalid={mismatch} />
      {mismatch && <span className="caps">The passwords don't match yet.</span>}
      <button className="btn primary" disabled={busy || !policy} style={{ alignSelf: "flex-start" }}>
        {busy ? <span className="spinner" /> : <KeyRound size={16} />}{forced ? "Set password and continue" : "Change password"}
      </button>
    </form>
  );
}

/** Shown instead of the app until a temporary password has been replaced. */
export function ForcedPasswordChange() {
  const { user, logout } = useApp();
  return (
    <div className="center-screen">
      <div className="card narrow">
        <Logo />
        <div><h1 style={{ fontSize: 24 }}>Set your own password</h1>
          <p className="muted">Welcome, {user?.full_name || user?.username}. You signed in with a one-time password from an administrator. Choose a new one to continue; nobody else will know it.</p></div>
        <ChangePasswordForm forced />
        <button className="btn ghost sm" onClick={logout} style={{ alignSelf: "flex-start" }}><LogOut size={14} />Sign out</button>
      </div>
    </div>
  );
}

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—");

export default function AccountPage() {
  const { user, toast, logout } = useApp();
  if (!user) return null;
  const signOutEverywhere = async () => {
    try { await api("/api/auth/logout-all", { method: "POST" }); toast("Signed out on every device."); }
    catch (e: any) { toast(e.message, true); }
    await logout();
  };
  return (
    <>
      <div className="page-head"><div><h1>Your account</h1><p>Profile, password and sessions.</p></div></div>
      <div className="grid g-dash">
        <div className="card">
          <div className="card-head"><h2>Change password</h2><span className="tag ok"><ShieldCheck size={12} />Argon2id</span></div>
          <p className="muted">Changing your password signs you out everywhere else.</p>
          <ChangePasswordForm />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <h3>Profile</h3>
            <dl className="kv">
              <dt>Name</dt><dd>{user.full_name || "—"}</dd>
              <dt>Username</dt><dd className="mono">{user.username}</dd>
              <dt>Role</dt><dd>{ROLE_LABEL[user.role]}</dd>
              <dt>Can</dt><dd className="subtle">{ROLE_HELP[user.role]}</dd>
              <dt>Scope</dt><dd>{user.scope_level.toLowerCase()}{user.scope_id ? ` · ${user.scope_id}` : ""}</dd>
              <dt>Last sign-in</dt><dd>{fmt(user.last_login_at)}</dd>
              <dt>Password set</dt><dd>{fmt(user.password_changed_at)}</dd>
            </dl>
          </div>
          <div className="card">
            <h3>Sessions</h3>
            <p className="muted">Sessions last 8 hours. Lost a laptop or used a shared computer? End every session at once.</p>
            <button className="btn danger" onClick={signOutEverywhere} style={{ alignSelf: "flex-start" }}><LogOut size={16} />Sign out everywhere</button>
          </div>
        </div>
      </div>
    </>
  );
}
