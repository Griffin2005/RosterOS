import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api, canManage, WD } from "../api";
import { useApp } from "../ctx";
import { Modal } from "../components/Modal";

export default function PeoplePage() {
  const { user, toast, search, reload } = useApp();
  const [emps, setEmps] = useState<any[]>([]);
  const [pods, setPods] = useState<any[]>([]);
  const [lines, setLines] = useState<any[]>([]);
  const [edit, setEdit] = useState<any | null>(null);
  const manage = canManage(user);
  const load = () => Promise.all([api("/api/employees"), api("/api/pods"), api("/api/service-lines")])
    .then(([e, p, l]) => { setEmps(e); setPods(p); setLines(l); }).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);

  const podName = Object.fromEntries(pods.map((p) => [p.id, p.name]));
  const lineName = Object.fromEntries(lines.map((l) => [l.id, `${l.brand} · ${l.process}`]));
  const q = search.toLowerCase();
  const shown = emps.filter((e) => !q || e.name.toLowerCase().includes(q) || e.code.toLowerCase().includes(q));

  const save = async () => {
    try {
      const body = { code: edit.code, name: edit.name, pod_id: edit.pod_id || null, capacity: +edit.capacity, weekly_offs: +edit.weekly_offs,
                     max_consecutive: +edit.max_consecutive, holiday_calendar_id: edit.holiday_calendar_id || null, active: edit.active, preferred_off: edit.preferred_off };
      if (edit.id) await api(`/api/employees/${edit.id}`, { method: "PUT", body });
      else await api("/api/employees", { body });
      toast("Saved. Regenerate or repair the roster to apply."); setEdit(null); load(); reload();
    } catch (e: any) { toast(e.message, true); }
  };
  const addAssign = async (line: string, role: string, load_pct: number) => {
    try { await api("/api/assignments", { body: { employee_id: edit.id, service_line_id: line, role, load_pct } }); await load(); setEdit((x: any) => ({ ...x, assignments: [...x.assignments, { id: "new", service_line_id: line, role, load_pct }] })); reload(); }
    catch (e: any) { toast(e.message, true); }
  };
  const delAssign = async (id: string) => {
    try { await api(`/api/assignments/${id}`, { method: "DELETE" }); setEdit((x: any) => ({ ...x, assignments: x.assignments.filter((a: any) => a.id !== id) })); load(); reload(); }
    catch (e: any) { toast(e.message, true); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>People</h1><p>{emps.filter((e) => e.active).length} active employees in {pods.length} pods. Assignments, capacity and weekly-off rules are all data, not code.</p></div>
        {manage && <button className="btn primary" onClick={() => setEdit({ code: "", name: "", pod_id: pods[0]?.id, capacity: 100, weekly_offs: 1, max_consecutive: 6, holiday_calendar_id: "", active: true, preferred_off: [], assignments: [] })}><Plus size={16} />Add employee</button>}
      </div>
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Code</th><th>Name</th><th>Pod</th><th>Responsibilities</th><th>Offs / week</th><th>Max streak</th><th>Prefers off</th><th /></tr></thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.id} style={{ opacity: e.active ? 1 : .5 }}>
                <td className="mono">{e.code}</td>
                <td><b>{e.name}</b>{pods.some((p) => p.lead_id === e.id) && <span className="tag ok" style={{ marginLeft: 6 }}>lead</span>}</td>
                <td>{podName[e.pod_id] || "—"}</td>
                <td className="subtle" style={{ maxWidth: 360 }}>
                  {e.assignments.filter((a: any) => a.role === "PRIMARY").map((a: any) => `${lineName[a.service_line_id]} ${a.load_pct}%`).join(", ") || "—"}
                  {e.assignments.some((a: any) => a.role === "BACKUP") && <> · backup on {e.assignments.filter((a: any) => a.role === "BACKUP").length}</>}
                </td>
                <td className="num">{e.weekly_offs}</td><td className="num">{e.max_consecutive}</td>
                <td>{e.preferred_off.map((d: number) => WD[d]).join(", ") || "—"}</td>
                <td>{manage && <button className="btn sm ghost" onClick={() => setEdit({ ...e, holiday_calendar_id: e.holiday_calendar_id || "" })}>Edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {edit && (
        <Modal title={edit.id ? `Edit ${edit.name}` : "Add employee"} onClose={() => setEdit(null)}>
          <div className="grid g2">
            <label className="field">Code<input id="emp-code" className="input" value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value })} /></label>
            <label className="field">Name<input id="emp-name" className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
            <label className="field">Pod<select id="emp-pod" className="input" value={edit.pod_id || ""} onChange={(e) => setEdit({ ...edit, pod_id: e.target.value })}>{pods.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <label className="field">Holiday calendar<select id="emp-cal" className="input" value={edit.holiday_calendar_id} onChange={(e) => setEdit({ ...edit, holiday_calendar_id: e.target.value })}><option value="">National only</option><option value="IN-WB">West Bengal</option><option value="IN-MH">Maharashtra</option></select></label>
            <label className="field">Daily capacity %<input id="emp-cap" className="input" type="number" value={edit.capacity} onChange={(e) => setEdit({ ...edit, capacity: e.target.value })} /></label>
            <label className="field">Weekly offs<input id="emp-offs" className="input" type="number" min={0} max={3} value={edit.weekly_offs} onChange={(e) => setEdit({ ...edit, weekly_offs: e.target.value })} /></label>
            <label className="field">Max consecutive days<input id="emp-streak" className="input" type="number" min={1} max={13} value={edit.max_consecutive} onChange={(e) => setEdit({ ...edit, max_consecutive: e.target.value })} /></label>
            <label className="field">Active<select id="emp-active" className="input" value={edit.active ? "1" : "0"} onChange={(e) => setEdit({ ...edit, active: e.target.value === "1" })}><option value="1">Active</option><option value="0">Inactive</option></select></label>
          </div>
          <div className="field">Preferred off days (soft)
            <div className="chips">{WD.map((d, i) => (
              <button key={d} type="button" className="chip" style={edit.preferred_off.includes(i) ? { background: "var(--g-800)", color: "#fff", borderColor: "var(--g-800)" } : {}}
                      onClick={() => setEdit({ ...edit, preferred_off: edit.preferred_off.includes(i) ? edit.preferred_off.filter((x: number) => x !== i) : [...edit.preferred_off, i] })}>{d}</button>
            ))}</div>
          </div>
          {edit.id && (
            <div className="field">Assignments
              <div className="list">{edit.assignments.map((a: any) => (
                <div key={a.id + a.service_line_id} className="list-item"><div className="grow"><b>{lineName[a.service_line_id]}</b><small>{a.role.toLowerCase()} · {a.load_pct}% load</small></div>
                  {a.id !== "new" && <button className="close" onClick={() => delAssign(a.id)} aria-label="Remove assignment"><Trash2 size={14} /></button>}</div>
              ))}</div>
              <AddAssignment lines={lines.filter((l) => !edit.assignments.some((a: any) => a.service_line_id === l.id))} onAdd={addAssign} />
            </div>
          )}
          <div className="actions"><button className="btn primary" onClick={save}>Save</button><button className="btn ghost" onClick={() => setEdit(null)}>Cancel</button></div>
        </Modal>
      )}
    </>
  );
}

function AddAssignment({ lines, onAdd }: { lines: any[]; onAdd: (l: string, role: string, load: number) => void }) {
  const [line, setLine] = useState("");
  const [role, setRole] = useState("BACKUP");
  const [load, setLoad] = useState(50);
  return (
    <div className="actions">
      <select id="asg-line" className="input" value={line} onChange={(e) => setLine(e.target.value)} style={{ flex: 1 }}><option value="">Add a line…</option>{lines.map((l) => <option key={l.id} value={l.id}>{l.brand} · {l.process}</option>)}</select>
      <select id="asg-role" className="input" value={role} onChange={(e) => setRole(e.target.value)}><option>PRIMARY</option><option>BACKUP</option></select>
      <input id="asg-load" className="input" type="number" style={{ width: 80 }} value={load} onChange={(e) => setLoad(+e.target.value)} aria-label="Load %" />
      <button className="btn sm" disabled={!line} onClick={() => { onAdd(line, role, load); setLine(""); }}>Add</button>
    </div>
  );
}
