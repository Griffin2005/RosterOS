import { useEffect, useId, useState } from "react";
import { Check, Eye, EyeOff, X } from "lucide-react";
import { api, checkPassword, strength, type Rule } from "../api";

/** Password input with a show/hide toggle and a Caps Lock warning. */
export function PasswordField({ label, value, onChange, autoComplete, autoFocus, invalid, describedBy }: {
  label: string; value: string; onChange: (v: string) => void; autoComplete: string;
  autoFocus?: boolean; invalid?: boolean; describedBy?: string;
}) {
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const id = useId();
  const onKey = (e: React.KeyboardEvent) => setCaps(e.getModifierState?.("CapsLock") ?? false);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className={`pw-wrap ${invalid ? "invalid" : ""}`}>
        <input id={id} className="input" type={show ? "text" : "password"} value={value} autoComplete={autoComplete}
               autoFocus={autoFocus} spellCheck={false} autoCapitalize="off" maxLength={128}
               aria-invalid={invalid || undefined} aria-describedby={describedBy}
               onChange={(e) => onChange(e.target.value)} onKeyDown={onKey} onKeyUp={onKey} onBlur={() => setCaps(false)} />
        <button type="button" className="pw-toggle" onClick={() => setShow((s) => !s)}
                aria-label={show ? "Hide password" : "Show password"} aria-pressed={show} title={show ? "Hide password" : "Show password"}>
          {show ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
      {caps && <span className="caps" role="status">Caps Lock is on</span>}
    </div>
  );
}

let policyCache: { min_length: number; rules: Rule[] } | null = null;
export function usePolicy() {
  const [p, setP] = useState(policyCache);
  useEffect(() => {
    if (!policyCache) api("/api/auth/password-policy").then((r) => { policyCache = r; setP(r); }).catch(() => {});
  }, []);
  return p;
}

const STRENGTH = ["", "Weak", "Fair", "Good", "Strong"];

/** Live checklist against the server's policy, plus a strength meter. */
export function PasswordRules({ password, username, fullName, id }: {
  password: string; username?: string; fullName?: string; id?: string;
}) {
  const policy = usePolicy();
  const [serverFailed, setServerFailed] = useState<string[] | undefined>();
  useEffect(() => {            // the server's verdict (incl. its common-password list), debounced
    setServerFailed(undefined);
    if (!password) return;
    const t = setTimeout(() => {
      api("/api/auth/password-check", { body: { password, username: username || "", full_name: fullName || "" } })
        .then((r) => setServerFailed(r.failed)).catch(() => {});
    }, 350);
    return () => clearTimeout(t);
  }, [password, username, fullName]);
  if (!policy) return null;
  const failed = checkPassword(password, policy.min_length, username, fullName);
  serverFailed?.forEach((f) => failed.add(f));
  const s = password ? strength(password) : 0;
  return (
    <div className="pw-rules" id={id}>
      <div className="meter" aria-label={`Strength: ${STRENGTH[s] || "none"}`}>
        {[1, 2, 3, 4].map((i) => <i key={i} className={i <= s ? `on s${s}` : ""} />)}
        <span>{password ? STRENGTH[s] : "Strength"}</span>
      </div>
      <ul>
        {policy.rules.filter((r) => r.id !== "max" || password.length > 128).map((r) => {
          const ok = password.length > 0 && !failed.has(r.id) && !(r.id === "common" && !serverFailed);
          const pending = r.id === "common" && !serverFailed;
          return (
            <li key={r.id} className={ok ? "ok" : password && !pending ? "bad" : ""}>
              {ok ? <Check size={13} /> : password && !pending ? <X size={13} /> : <span className="dot" />}
              {r.label}{pending && password ? " (checking…)" : ""}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
