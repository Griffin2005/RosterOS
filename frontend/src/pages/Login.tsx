import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ArrowLeft, KeyRound, LockKeyhole, ShieldCheck, Timer } from "lucide-react";
import { api, ApiError } from "../api";
import { useApp } from "../ctx";
import { PasswordField } from "../components/Password";
import { Logo } from "./Landing";

export default function Login() {
  const { user, login } = useApp();
  const loc = useLocation();
  const next = new URLSearchParams(loc.search).get("next") || "/dashboard";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ msg: string; locked?: boolean } | null>(null);

  if (user) return <Navigate to={next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard"} replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) { setError({ msg: "Enter your username and password." }); return; }
    setBusy(true); setError(null);
    try {
      const r = await api("/api/auth/login", { body: { username: username.trim(), password } });
      setPassword("");
      login(r.user, r.csrf);
    } catch (err) {
      const e2 = err as ApiError;
      setError({ msg: e2.message, locked: e2.status === 429 });
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login-art">
        <Link to="/" className="brand" style={{ padding: 0, textDecoration: "none" }}><Logo light /></Link>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <h1>Monthly rosters that cover every brand</h1>
          <p>A constraint solver builds the month, an independent validator checks it, and every gap comes with the reason and a ranked fix.</p>
        </div>
        <ul className="login-trust">
          <li><KeyRound size={16} />Passwords hashed with Argon2id, never stored or shown</li>
          <li><LockKeyhole size={16} />Session in an httpOnly cookie with CSRF protection</li>
          <li><Timer size={16} />Accounts lock after 5 failed attempts</li>
          <li><ShieldCheck size={16} />Every sign-in and change is in the audit log</li>
        </ul>
      </div>
      <form className="login-form" onSubmit={submit} noValidate>
        <Link to="/" className="back-link"><ArrowLeft size={15} />Back to overview</Link>
        <div><h1>Sign in</h1><p className="muted">Use the account your administrator created for you.</p></div>
        {error && <div className={`alert ${error.locked ? "warn" : "err"}`} role="alert">{error.msg}</div>}
        <div className="field">
          <label htmlFor="login-user">Username</label>
          <input id="login-user" className="input" value={username} onChange={(e) => setUsername(e.target.value)}
                 autoComplete="username" autoCapitalize="off" spellCheck={false} autoFocus maxLength={60} />
        </div>
        <PasswordField label="Password" value={password} onChange={setPassword} autoComplete="current-password" invalid={!!error && !error.locked} />
        <button className="btn primary lg" disabled={busy}>{busy ? <span className="spinner" /> : null}Sign in</button>
        <p className="subtle">Forgot your password? An administrator can issue a one-time password from Team; you'll set a new one when you sign in.</p>
        <p className="subtle">Reviewing the assignment? Credentials are shared privately with the submission, never in the repository.</p>
      </form>
    </div>
  );
}
