import { useState } from "react";
import { fmtDay, type Conflict } from "../api";
import { useApp } from "../ctx";
import { RosterActions } from "../components/RosterActions";

const SEVS = ["HARD", "SOFT", "INFO"] as const;

export default function ConflictsPage() {
  const { grid, openConflict } = useApp();
  const [sev, setSev] = useState<(typeof SEVS)[number]>("HARD");
  if (!grid) return <div className="card empty"><p>No roster for this month yet.</p></div>;
  const list = grid.conflicts.filter((c) => c.severity === sev);
  const byCode = new Map<string, Conflict[]>();
  list.forEach((c) => byCode.set(`${c.code} · ${c.name.replace(/_/g, " ").toLowerCase()}`, [...(byCode.get(`${c.code} · ${c.name.replace(/_/g, " ").toLowerCase()}`) || []), c]));

  return (
    <>
      <div className="page-head">
        <div><h1>Conflicts</h1><p>Hard rules must be fixed or acknowledged before publishing. Preferences are soft and yield to coverage.</p></div>
        <RosterActions compact />
      </div>
      <div className="actions">
        <div className="seg">{SEVS.map((s) => <button key={s} className={sev === s ? "on" : ""} onClick={() => setSev(s)}>{s === "HARD" ? "Mandatory" : s === "SOFT" ? "Preferences" : "Info"} ({grid.conflicts.filter((c) => c.severity === s).length})</button>)}</div>
      </div>
      {grid.impossible.length > 0 && sev === "HARD" && (
        <div className="card" style={{ border: "1.5px solid var(--crit)" }}>
          <h3>Impossible before solving</h3>
          <p className="muted">The pre-check found slots where fewer people are trained and available than required. No roster can fill these; add a backup, move the leave, or acknowledge.</p>
          <div className="list">{grid.impossible.map((s: any, i: number) => (
            <div className="list-item" key={i}><span className="sev-dot HARD" /><div className="grow"><b>{s.label} · {fmtDay(s.date)}</b>
              <small>needs {s.required}, {s.available} available · {s.trained.map((t: any) => `${t.name} (${t.status.toLowerCase().replace("_", " ")})`).join(", ")}</small></div></div>
          ))}</div>
        </div>
      )}
      {list.length === 0 && <div className="card empty"><p>Nothing here.</p></div>}
      {Array.from(byCode.entries()).map(([code, items]) => (
        <div className="card" key={code}>
          <div className="card-head"><h3 style={{ textTransform: "capitalize" }}>{code}</h3><span className="subtle">{items.length}</span></div>
          <div className="list">
            {items.slice(0, 60).map((c) => (
              <button key={c.key} className="list-item" style={{ border: 0, background: "none", textAlign: "left" }} onClick={() => openConflict(c)}>
                <span className={`sev-dot ${c.severity}`} />
                <div className="grow"><b>{c.title}</b><small>{c.date ? fmtDay(c.date) + " · " : ""}{c.detail}</small></div>
                {c.acknowledged && <span className="tag ok">acknowledged</span>}
              </button>
            ))}
            {items.length > 60 && <p className="subtle">{items.length - 60} more not shown.</p>}
          </div>
        </div>
      ))}
    </>
  );
}
