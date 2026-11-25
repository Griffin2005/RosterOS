import { Fragment, useMemo, useState } from "react";
import { canEditRoster, fmtDay, STATUS_LABEL, STATUS_SHORT, WD, weekday, type CoverageRow, type EmployeeRow, type Grid } from "../api";
import { useApp } from "../ctx";
import { RosterActions } from "../components/RosterActions";
import { CellEditor } from "../components/CellEditor";

type View = "company" | "pod" | "brand" | "process" | "employee";

export default function RosterPage() {
  const { grid, gridLoading, user, search } = useApp();
  const [view, setView] = useState<View>(user?.scope_level === "SELF" ? "employee" : "company");
  const [podId, setPodId] = useState<string>("");
  const [brandId, setBrandId] = useState<string>("");
  const [proc, setProc] = useState<string>("");
  const [empId, setEmpId] = useState<string>(user?.employee_id || "");
  const [editing, setEditing] = useState<{ emp: EmployeeRow; idx: number } | null>(null);

  if (!grid) return (<><Head /><div className="card empty">{gridLoading ? <span className="spinner" /> : <p>No roster for this month yet.</p>}</div></>);

  const pods = grid.pods.filter((p) => grid.employees.some((e) => e.pod_id === p.id));
  const brands = Array.from(new Map(grid.coverage.map((c) => [c.brand_id, c.brand])).entries()).sort((a, b) => a[1].localeCompare(b[1]));
  const procs = Array.from(new Set(grid.coverage.map((c) => c.process))).sort();
  const pod = podId || pods[0]?.id;
  const brand = brandId || brands[0]?.[0];
  const pr = proc || procs[0];
  const emp = grid.employees.find((e) => e.id === (empId || grid.employees[0]?.id));
  const q = search.trim().toLowerCase();
  const matchE = (e: EmployeeRow) => !q || e.name.toLowerCase().includes(q) || e.code.toLowerCase().includes(q)
    || e.assignments.some((a) => grid.coverage.find((c) => c.line_id === a.line_id)?.brand.toLowerCase().includes(q));
  const onCell = canEditRoster(user) ? (e: EmployeeRow, idx: number) => setEditing({ emp: e, idx }) : undefined;

  return (
    <>
      <Head />
      <div className="actions" style={{ justifyContent: "space-between" }}>
        <div className="seg" role="tablist">
          {(["company", "pod", "brand", "process", "employee"] as View[]).map((v) => (
            <button key={v} role="tab" aria-selected={view === v} className={view === v ? "on" : ""} onClick={() => setView(v)}>{v[0].toUpperCase() + v.slice(1)}</button>
          ))}
        </div>
        <div className="actions">
          {view === "pod" && <select className="input" value={pod} onChange={(e) => setPodId(e.target.value)} aria-label="Pod">{pods.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
          {view === "brand" && <select className="input" value={brand} onChange={(e) => setBrandId(e.target.value)} aria-label="Brand">{brands.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select>}
          {view === "process" && <select className="input" value={pr} onChange={(e) => setProc(e.target.value)} aria-label="Process">{procs.map((p) => <option key={p} value={p}>{p}</option>)}</select>}
          {view === "employee" && <select className="input" value={emp?.id} onChange={(e) => setEmpId(e.target.value)} aria-label="Employee">{grid.employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>}
        </div>
      </div>
      <Legend />

      {view === "company" && <EmployeeGrid grid={grid} groups={pods.map((p) => ({ title: `${p.name} · lead ${grid.employees.find((e) => e.id === p.lead_id)?.name ?? "—"}`, emps: grid.employees.filter((e) => e.pod_id === p.id && matchE(e)) }))} onCell={onCell} />}
      {view === "pod" && (() => {
        const p = grid.pods.find((x) => x.id === pod)!;
        const lead = grid.employees.find((e) => e.id === p?.lead_id);
        return <EmployeeGrid grid={grid}
          groups={[{ title: `Coverage · ${p?.name}`, lines: grid.coverage.filter((c) => c.pod_id === pod) },
                   { title: `People · lead ${lead?.name ?? "—"}`, emps: grid.employees.filter((e) => e.pod_id === pod && matchE(e)) }]} onCell={onCell} />;
      })()}
      {view === "brand" && (() => {
        const ls = grid.coverage.filter((c) => c.brand_id === brand);
        const ids = new Set(ls.flatMap((c) => c.assignees.map((a) => a.employee_id)));
        const primaries = new Set(ls.flatMap((c) => c.assignees.filter((a) => a.role === "PRIMARY").map((a) => a.employee_id)));
        return (<>
          <p className="muted">{primaries.size === 1 ? "Single-resource brand: one person carries every line; backups step in on their offs." : `${primaries.size} people share this brand's lines.`}</p>
          <EmployeeGrid grid={grid} groups={[{ title: "Daily coverage (scheduled / required)", lines: ls },
            { title: "Primary staff", emps: grid.employees.filter((e) => primaries.has(e.id)) },
            { title: "Trained backups", emps: grid.employees.filter((e) => ids.has(e.id) && !primaries.has(e.id)) }]} onCell={onCell} />
        </>);
      })()}
      {view === "process" && (() => {
        const ls = grid.coverage.filter((c) => c.process === pr && (!q || c.brand.toLowerCase().includes(q)));
        const ids = new Set(ls.flatMap((c) => c.assignees.filter((a) => a.role === "PRIMARY").map((a) => a.employee_id)));
        return <EmployeeGrid grid={grid} groups={[{ title: `${pr} lines across brands`, lines: ls }, { title: `People staffed on ${pr}`, emps: grid.employees.filter((e) => ids.has(e.id)) }]} onCell={onCell} />;
      })()}
      {view === "employee" && emp && <EmployeeCalendar grid={grid} emp={emp} onCell={onCell} />}

      {editing && <CellEditor emp={editing.emp} dayIdx={editing.idx} onClose={() => setEditing(null)} />}
    </>
  );
}

function Head() {
  return (
    <div className="page-head">
      <div><h1>Roster</h1><p>Company, pod, brand, process and employee views of the same month. Click a cell to edit it; every edit is validated.</p></div>
      <RosterActions />
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      <span><i style={{ background: "var(--g-100)" }} />Working</span>
      <span><i style={{ background: "var(--g-500)" }} />Covering as backup</span>
      <span><i style={{ background: "var(--off)" }} />Weekly off</span>
      <span><i style={{ background: "var(--info-bg)" }} />Holiday</span>
      <span><i style={{ background: "var(--crit-bg)" }} />Leave</span>
      <span><i style={{ background: "var(--warn-bg)" }} />Comp-off</span>
      <span><i style={{ boxShadow: "inset 0 0 0 2px var(--crit)" }} />Hard conflict</span>
      <span><i style={{ outline: "1.5px dashed var(--g-700)", outlineOffset: -3 }} />Manual edit</span>
    </div>
  );
}

interface Group { title: string; emps?: EmployeeRow[]; lines?: CoverageRow[] }

function DayHeads({ grid }: { grid: Grid }) {
  const hol = new Set(grid.holidays);
  return (<>{grid.days.map((d) => {
    const wd = weekday(d);
    return <th key={d} className={hol.has(d) ? "ph" : wd >= 5 ? "we" : ""} title={hol.has(d) ? "Public holiday" : ""}>{WD[wd].slice(0, 2)}<span className="d">{d.slice(8)}</span></th>;
  })}</>);
}

function EmployeeGrid({ grid, groups, onCell }: { grid: Grid; groups: Group[]; onCell?: (e: EmployeeRow, i: number) => void }) {
  const { openConflict } = useApp();
  const hardKey = useMemo(() => {
    const m = new Map<string, any>();
    for (const c of grid.conflicts) if (c.severity === "HARD" && !c.acknowledged && c.employee_id && c.date) m.set(`${c.employee_id}|${c.date}`, c);
    return m;
  }, [grid]);
  const lineConf = useMemo(() => {
    const m = new Map<string, any>();
    for (const c of grid.conflicts) if (c.severity === "HARD" && c.line_id && c.date) m.set(`${c.line_id}|${c.date}`, c);
    return m;
  }, [grid]);
  const labels = Object.fromEntries(grid.coverage.map((c) => [c.line_id, `${c.brand} · ${c.process}`]));
  const names = Object.fromEntries(grid.employees.map((e) => [e.id, e.name]));

  return (
    <div className="grid-wrap">
      <table className="roster">
        <thead><tr><th className="sticky">{groups.some((g) => g.emps) ? "Employee" : "Line"}</th><DayHeads grid={grid} /></tr></thead>
        <tbody>
          {groups.map((g) => (
            <GroupRows key={g.title} g={g} grid={grid} onCell={onCell} hardKey={hardKey} lineConf={lineConf} labels={labels} names={names} openConflict={openConflict} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ g, grid, onCell, hardKey, lineConf, labels, names, openConflict }: any) {
  if ((g.emps && g.emps.length === 0) || (g.lines && g.lines.length === 0)) return null;
  return (
    <>
      <tr className="group"><td colSpan={grid.days.length + 1}>{g.title}</td></tr>
      {g.lines?.map((l: CoverageRow) => (
        <tr key={l.line_id}>
          <td className="sticky"><div className="emp-cell"><div><b>{l.brand} · {l.process}</b><small>{l.calendar.replace(/_/g, " ").toLowerCase()} · {l.assignees.filter((a) => a.role === "PRIMARY").length} primary, {l.assignees.filter((a) => a.role === "BACKUP").length} backup</small></div></div></td>
          {l.days.map((d, i) => {
            const conf = lineConf.get(`${l.line_id}|${grid.days[i]}`);
            const cls = d.req === 0 ? "closed" : d.heads.length === 0 ? "none" : d.heads.length < d.req ? "short" : d.heads.length > d.req ? "over" : "ok";
            const tip = d.req === 0 ? "Closed" : `${d.heads.length}/${d.req}: ${d.heads.map((h) => names[h] ?? h).join(", ") || "nobody"}${conf?.acknowledged ? " (acknowledged)" : ""}`;
            return <td key={i}><button className={`cov ${cls}`} style={{ border: 0, cursor: conf ? "pointer" : "default" }} title={tip} aria-label={tip} onClick={() => conf && openConflict(conf)}>{d.req === 0 ? "·" : `${d.heads.length}/${d.req}`}</button></td>;
          })}
        </tr>
      ))}
      {g.emps?.map((e: EmployeeRow) => (
        <tr key={e.id}>
          <td className="sticky"><div className="emp-cell"><span className="avatar sm">{e.name.split(" ").map((s) => s[0]).join("")}</span>
            <div style={{ minWidth: 0 }}><b>{e.name}{e.is_lead ? " · lead" : ""}</b><small>{e.code} · {Array.from(new Set(e.assignments.filter((a) => a.role === "PRIMARY").map((a) => labels[a.line_id]?.split(" · ")[0]))).join(", ") || "backup pool"}</small></div></div></td>
          {e.cells.map((c, i) => {
            if (!c) return <td key={i} />;
            const conf = hardKey.get(`${e.id}|${grid.days[i]}`);
            const backup = Object.values(c.covers).some(Boolean);
            const lines = Object.keys(c.covers).map((l) => labels[l] ?? l);
            const tip = `${e.name}, ${fmtDay(grid.days[i])}: ${STATUS_LABEL[c.status]}${lines.length ? ` · ${lines.join(", ")}` : ""}${c.locked ? " · locked" : ""}${conf ? ` · ${conf.title}` : ""}`;
            return (
              <td key={i}>
                <button className={`cell ${c.status} ${backup ? "backup" : ""} ${conf ? "conflict" : ""} ${c.locked ? "locked" : ""} ${c.source === "MANUAL" ? "manual" : ""}`}
                        title={tip} aria-label={tip} onClick={() => (conf && !onCell ? openConflict(conf) : onCell?.(e, i))} disabled={!onCell && !conf}>
                  {c.status === "WORK" ? (lines.length > 1 ? lines.length : backup ? "B" : "W") : STATUS_SHORT[c.status]}
                </button>
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}

function EmployeeCalendar({ grid, emp, onCell }: { grid: Grid; emp: EmployeeRow; onCell?: (e: EmployeeRow, i: number) => void }) {
  const labels = Object.fromEntries(grid.coverage.map((c) => [c.line_id, `${c.brand} · ${c.process}`]));
  const counts: Record<string, number> = {};
  emp.cells.forEach((c) => c && (counts[c.status] = (counts[c.status] || 0) + 1));
  const lead = weekday(grid.days[0]);
  const hard = grid.conflicts.filter((c) => c.employee_id === emp.id && c.severity !== "INFO");
  return (
    <div className="grid g-dash">
      <div className="card">
        <div className="card-head"><h2>{emp.name}</h2><span className="subtle">{emp.code}{emp.preferred_off.length ? ` · prefers ${emp.preferred_off.map((d) => WD[d]).join(", ")} off` : ""}</span></div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 8 }}>
          {WD.map((d) => <div key={d} className="subtle" style={{ textAlign: "center" }}>{d}</div>)}
          {Array.from({ length: lead }).map((_, i) => <div key={`x${i}`} />)}
          {emp.cells.map((c, i) => c && (
            <button key={i} onClick={() => onCell?.(emp, i)} disabled={!onCell}
                    className={`cell ${c.status} ${Object.values(c.covers).some(Boolean) ? "backup" : ""}`}
                    style={{ width: "100%", height: 74, margin: 0, display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "space-between", padding: 8, fontFamily: "var(--f-body)", textAlign: "left" }}>
              <b style={{ fontFamily: "var(--f-head)", fontSize: 14 }}>{grid.days[i].slice(8)}</b>
              <span style={{ fontSize: 10.5, lineHeight: 1.25 }}>{c.status === "WORK" ? Object.keys(c.covers).map((l) => labels[l]?.split(" · ")[1]).join(" · ") : STATUS_LABEL[c.status]}</span>
            </button>
          ))}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="card">
          <h3>This month</h3>
          <dl className="kv">{Object.entries(STATUS_LABEL).map(([k, v]) => <Fragment key={k}><dt>{v}</dt><dd className="num">{counts[k] || 0} day(s)</dd></Fragment>)}</dl>
        </div>
        <div className="card">
          <h3>Responsibilities</h3>
          <div className="list">{emp.assignments.map((a) => <div key={a.line_id} className="list-item"><div className="grow"><b>{labels[a.line_id]}</b><small>{a.role.toLowerCase()} · {a.load}% load</small></div></div>)}</div>
        </div>
        {hard.length > 0 && <div className="card"><h3>Flags</h3><div className="list">{hard.slice(0, 8).map((c) => <div key={c.key} className="list-item"><span className={`sev-dot ${c.severity}`} /><div className="grow"><b>{c.title}</b><small>{c.date}</small></div></div>)}</div></div>}
      </div>
    </div>
  );
}
