import { useMemo, useState } from "react";
import { ArrowUpRight, CalendarCheck2, ShieldAlert, UserCheck, Users2 } from "lucide-react";
import { Link } from "react-router-dom";
import { STATUS_LABEL, WD, fmtDay, weekday } from "../api";
import { useApp } from "../ctx";
import { RosterActions } from "../components/RosterActions";

export default function Dashboard() {
  const { grid, gridLoading, openConflict, user } = useApp();
  const todayIso = new Date().toISOString().slice(0, 10);
  const [focus, setFocus] = useState<number | null>(null);

  const stats = useMemo(() => {
    if (!grid) return null;
    const n = grid.days.length;
    const perDay = Array.from({ length: n }, () => ({ req: 0, ok: 0 }));
    let slots = 0, covered = 0;
    for (const row of grid.coverage) {
      row.days.forEach((d, i) => {
        if (d.req > 0) {
          slots++; perDay[i].req++;
          if (d.heads.length >= d.req) { covered++; perDay[i].ok++; }
        }
      });
    }
    const hard = grid.conflicts.filter((c) => c.severity === "HARD");
    return {
      slots, covered, perDay,
      pct: slots ? Math.round((covered / slots) * 1000) / 10 : 100,
      openHard: hard.filter((c) => !c.acknowledged),
      acked: hard.filter((c) => c.acknowledged).length,
      backups: grid.conflicts.filter((c) => c.code === "C10").length,
      prefs: grid.conflicts.filter((c) => c.code === "C09").length,
    };
  }, [grid]);

  if (!grid || !stats) {
    return (
      <>
        <div className="page-head"><div><h1>Dashboard</h1><p>Plan, generate and validate the monthly roster.</p></div><RosterActions compact /></div>
        <div className="card empty">
          {gridLoading ? <span className="spinner" /> : <>
            <CalendarCheck2 size={36} color="var(--g-700)" />
            <h2>No roster for this month yet</h2>
            <p>{user?.role === "OPS_MANAGER" || user?.role === "SUPER_ADMIN" ? "Generate one: the solver reads every brand's operating calendar, leaves, holidays and weekly-off rules, then shows any gap it can't close." : "Nothing has been published for this month yet."}</p>
          </>}
        </div>
      </>
    );
  }

  const dayIdx = focus ?? Math.max(0, grid.days.indexOf(todayIso));
  const day = grid.days[dayIdx];
  const working = grid.employees.filter((e) => e.cells[dayIdx]?.status === "WORK");
  const off = grid.employees.filter((e) => e.cells[dayIdx] && e.cells[dayIdx]!.status !== "WORK");
  const r = grid.roster;
  const lines = Object.fromEntries(grid.coverage.map((c) => [c.line_id, c]));

  return (
    <>
      <div className="page-head">
        <div><h1>Dashboard</h1><p>{new Date(r.month).toLocaleDateString("en-GB", { month: "long", year: "numeric" })} roster · v{r.version} {r.status.toLowerCase()}{grid.scoped ? " · filtered to your scope" : ""}</p></div>
        <RosterActions compact />
      </div>

      <div className="grid g4">
        <div className="card kpi hero">
          <span className="lab">Coverage</span>
          <Link to="/roster" className="arrow" aria-label="Open roster"><ArrowUpRight size={16} /></Link>
          <span className="val">{stats.pct}%</span>
          <span className="foot">{stats.covered} of {stats.slots} required line-days staffed</span>
        </div>
        <div className="card kpi">
          <span className="lab">Open hard conflicts</span>
          <Link to="/conflicts" className="arrow" aria-label="Open conflicts"><ArrowUpRight size={16} /></Link>
          <span className="val" style={{ color: stats.openHard.length ? "var(--crit)" : undefined }}>{stats.openHard.length}</span>
          <span className="foot"><ShieldAlert size={13} />{stats.acked} acknowledged with a reason</span>
        </div>
        <div className="card kpi">
          <span className="lab">Working {fmtDay(day)}</span>
          <span className="val">{working.length}</span>
          <span className="foot"><UserCheck size={13} />{off.length} off, on leave or on holiday</span>
        </div>
        <div className="card kpi">
          <span className="lab">Backup cover</span>
          <span className="val">{stats.backups}</span>
          <span className="foot"><Users2 size={13} />line-days covered by a backup · {stats.prefs} preferences overridden</span>
        </div>
      </div>

      <div className="grid g-dash">
        <div className="card">
          <div className="card-head"><h2>Daily coverage</h2><span className="subtle">Click a day to see who's on</span></div>
          <div className="bars" role="list">
            {stats.perDay.map((d, i) => {
              const pct = d.req ? d.ok / d.req : 1;
              const cls = d.ok < d.req ? "gap" : grid.days[i] === todayIso ? "today" : pct === 1 && i === dayIdx ? "full" : "";
              return (
                <button key={i} className="bar-col" style={{ border: 0, background: "none", padding: 0 }} onClick={() => setFocus(i)} role="listitem"
                        aria-label={`${fmtDay(grid.days[i])}: ${d.ok} of ${d.req} lines staffed`}>
                  {i === dayIdx && <span className="tip">{d.ok}/{d.req}</span>}
                  <span className={`bar ${cls}`} style={{ height: `${Math.max(12, (d.req / Math.max(...stats.perDay.map((x) => x.req))) * 100)}%`, outline: i === dayIdx ? "2px solid var(--g-900)" : "none", outlineOffset: 2 }} />
                  <small>{WD[weekday(grid.days[i])][0]}</small>
                </button>
              );
            })}
          </div>
          <div className="legend">
            <span><i style={{ background: "var(--g-500)" }} />fully staffed (height = lines open that day)</span>
            <span><i style={{ background: "repeating-linear-gradient(135deg,#fff 0 3px,#9FB2A5 3px 5px)", border: "1px solid #9FB2A5" }} />at least one gap</span>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h2>Needs attention</h2><Link to="/conflicts" className="btn sm ghost">All</Link></div>
          {stats.openHard.length === 0 && <p className="muted">No open hard conflicts. {stats.acked ? `${stats.acked} known gap(s) acknowledged.` : ""}</p>}
          <div className="list">
            {stats.openHard.slice(0, 6).map((c) => (
              <button key={c.key} className="list-item" style={{ border: 0, background: "none", textAlign: "left" }} onClick={() => openConflict(c)}>
                <span className={`sev-dot ${c.severity}`} /><div className="grow"><b>{c.title}</b><small>{c.date ? fmtDay(c.date) : ""} · {c.detail}</small></div>
              </button>
            ))}
            {grid.risks.slice(0, 3).map((c) => (
              <div key={c.key} className="list-item"><span className="sev-dot SOFT" /><div className="grow"><b>{c.title}</b><small>{c.detail}</small></div></div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid g3">
        <div className="card">
          <div className="card-head"><h2>On {fmtDay(day)}</h2><span className="tag ok">{working.length} working</span></div>
          <div className="list" style={{ maxHeight: 300, overflow: "auto" }}>
            {working.map((e) => {
              const c = e.cells[dayIdx]!;
              return (
                <div key={e.id} className="list-item"><span className="avatar sm">{e.name.split(" ").map((s) => s[0]).join("")}</span>
                  <div className="grow"><b>{e.name}</b><small>{Object.keys(c.covers).map((l) => `${lines[l]?.brand ?? "?"} ${lines[l]?.process ?? ""}`).join(" · ") || "no line"}</small></div>
                  {Object.values(c.covers).some(Boolean) && <span className="tag info">backup</span>}
                </div>
              );
            })}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Off that day</h2><span className="tag neutral">{off.length}</span></div>
          <div className="list" style={{ maxHeight: 300, overflow: "auto" }}>
            {off.map((e) => (
              <div key={e.id} className="list-item"><span className="avatar sm" style={{ background: "var(--off)" }}>{e.name.split(" ").map((s) => s[0]).join("")}</span>
                <div className="grow"><b>{e.name}</b><small>{STATUS_LABEL[e.cells[dayIdx]!.status]}</small></div></div>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Solver run</h2><span className="tag neutral">{r.kind.toLowerCase()}</span></div>
          <dl className="kv">
            <dt>Result</dt><dd>{r.stats?.status ?? "manual edit"}</dd>
            <dt>Time</dt><dd className="num">{r.stats?.wall_ms != null ? `${(r.stats.wall_ms / 1000).toFixed(1)} s` : "—"}</dd>
            <dt>Decision variables</dt><dd className="num">{r.stats?.bools?.toLocaleString() ?? "—"}</dd>
            <dt>Optimality gap</dt><dd className="num">{r.stats?.optimality_gap_pct != null ? `${r.stats.optimality_gap_pct}%` : "—"}</dd>
            {r.stats?.changed_cells != null && <><dt>Cells changed</dt><dd className="num">{r.stats.changed_cells} (window {r.stats.window?.join(" → ")})</dd></>}
            <dt>Rule set</dt><dd>v{r.rule_set_version ?? "—"}</dd>
            <dt>Note</dt><dd>{r.note}</dd>
          </dl>
          {r.stats?.notes?.length > 0 && <p className="subtle">{r.stats.notes.join(" ")}</p>}
        </div>
      </div>
    </>
  );
}
