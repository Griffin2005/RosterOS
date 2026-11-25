import { useState } from "react";
import { Lock } from "lucide-react";
import { api, fmtDay, STATUS_LABEL, type EmployeeRow, type Status } from "../api";
import { useApp } from "../ctx";
import { Drawer } from "./Modal";

const STATUSES: Status[] = ["WORK", "WEEK_OFF", "HOLIDAY", "LEAVE", "COMP_OFF"];

export function CellEditor({ emp, dayIdx, onClose }: { emp: EmployeeRow; dayIdx: number; onClose: () => void }) {
  const { grid, reload, toast, setRosterId } = useApp();
  const cell = emp.cells[dayIdx]!;
  const day = grid!.days[dayIdx];
  const [status, setStatus] = useState<Status>(cell.status);
  const [covers, setCovers] = useState<Record<string, boolean>>({ ...cell.covers });
  const [locked, setLocked] = useState(cell.locked);
  const [busy, setBusy] = useState(false);
  const labels = Object.fromEntries(grid!.coverage.map((c) => [c.line_id, c]));
  const load = Object.keys(covers).reduce((s, l) => s + (emp.assignments.find((a) => a.line_id === l)?.load || 0), 0);
  const cellConflicts = grid!.conflicts.filter((c) => c.employee_id === emp.id && c.date === day);

  const toggle = (lineId: string, asBackup: boolean) => setCovers((c) => {
    const n = { ...c };
    if (lineId in n) delete n[lineId]; else n[lineId] = asBackup;
    return n;
  });

  const save = async () => {
    setBusy(true);
    try {
      const res = await api(`/api/rosters/${grid!.roster.id}/edits`, {
        body: { edits: [{ employee_id: emp.id, date: day, status, covers: status === "WORK" ? covers : {}, locked }] },
      });
      setRosterId(null);
      await reload();
      if (res.introduced.length) toast(`Saved, but it opened ${res.introduced.length} hard conflict(s): ${res.introduced[0].title}`, true);
      else toast(res.resolved ? `Saved. ${res.resolved} conflict(s) resolved.` : `Saved to draft v${res.roster.version}.`);
      onClose();
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer title={<><h2>{emp.name}</h2><p className="muted">{fmtDay(day)} · {grid!.roster.status === "PUBLISHED" ? "editing creates a new draft" : `draft v${grid!.roster.version}`}</p></>} onClose={onClose}>
      {cellConflicts.length > 0 && (
        <div className="list">{cellConflicts.map((c) => (
          <div key={c.key} className="list-item" style={{ background: "var(--crit-bg)" }}><span className={`sev-dot ${c.severity}`} /><div className="grow"><b>{c.title}</b><small>{c.detail}</small></div></div>
        ))}</div>
      )}
      <label className="field">Status
        <select id="cell-status" className="input" value={status} onChange={(e) => setStatus(e.target.value as Status)}>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
      </label>
      {status === "WORK" && (
        <div className="field">Lines carried this day <span className="subtle">Load {load}% of capacity</span>
          <div className="checks">
            {emp.assignments.map((a) => {
              const c = labels[a.line_id];
              const req = c?.days[dayIdx]?.req ?? 0;
              return (
                <label key={a.line_id} className={`check ${a.line_id in covers ? "on" : ""}`}>
                  <input type="checkbox" checked={a.line_id in covers} onChange={() => toggle(a.line_id, a.role === "BACKUP")} />
                  <div style={{ flex: 1 }}><b>{c ? `${c.brand} · ${c.process}` : a.line_id}</b>
                    <div className="subtle">{a.role.toLowerCase()} · {a.load}% load · {req ? `needs ${req} today` : "closed today"}</div></div>
                </label>
              );
            })}
          </div>
        </div>
      )}
      <label className={`check ${locked ? "on" : ""}`}>
        <input type="checkbox" checked={locked} onChange={(e) => setLocked(e.target.checked)} />
        <Lock size={15} /><div><b>Lock this cell</b><div className="subtle">The solver keeps it as set when it regenerates or repairs.</div></div>
      </label>
      <div className="actions"><button className="btn primary" onClick={save} disabled={busy}>{busy && <span className="spinner" />}Save and validate</button><button className="btn ghost" onClick={onClose}>Cancel</button></div>
    </Drawer>
  );
}
