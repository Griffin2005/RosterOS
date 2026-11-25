import { useEffect, useState } from "react";
import { api, ROLE_LABEL } from "../api";
import { useApp } from "../ctx";

const DEMO_PASSWORD = "roster@123";

export default function Login() {
  const { login, toast } = useApp();
  const [users, setUsers] = useState<{ username: string; role: string; scope_level: string }[]>([]);
  const [username, setUsername] = useState("ops");
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api("/api/auth/demo-users").then((r) => setUsers(r.users)).catch(() => {}); }, []);

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    try {
      const r = await api("/api/auth/login", { body: { username, password } });
      login(r.token, r.user);
    } catch (err: any) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login-art">
        <div className="brand" style={{ padding: 0 }}><span className="brand-mark" style={{ borderColor: "#fff" }}><i style={{ background: "#fff" }} /></span><b style={{ color: "#fff" }}>RosterOS</b></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <h1>Monthly rosters that cover every brand</h1>
          <p>Plan, generate and validate rosters for 32 people across 22 brands. A constraint solver builds the month, an independent validator checks it, and every gap comes with the reason and a ranked fix.</p>
        </div>
        <p style={{ fontSize: 12.5 }}>Sample data: fictional brands and people. Working rules load from a simulated Google Sheet.</p>
      </div>
      <form className="login-form" onSubmit={submit}>
        <div><h1>Sign in</h1><p className="muted">Pick a demo role to see what each level can do. Password: <span className="mono">{DEMO_PASSWORD}</span></p></div>
        <div className="demo-users">
          {users.map((u) => (
            <button type="button" key={u.username} className={`demo-user ${username === u.username ? "on" : ""}`} onClick={() => setUsername(u.username)}>
              <b>{u.username}</b><span>{ROLE_LABEL[u.role]} · {u.scope_level.toLowerCase()}</span>
            </button>
          ))}
        </div>
        <label className="field">Username<input id="login-user" className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
        <label className="field">Password<input id="login-pass" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        <button className="btn primary" disabled={busy} style={{ alignSelf: "flex-start" }}>{busy ? <span className="spinner" /> : null}Sign in</button>
      </form>
    </div>
  );
}
