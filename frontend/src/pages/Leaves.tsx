import { useEffect, useState } from "react";
import { api, canEditRoster, fmtDay } from "../api";
import { useApp } from "../ctx";
import { Modal } from "../components/Modal";

export default function LeavesPage() {
  const { user, toast, reload, openConflict, grid } = useApp();
  const [leaves, setLeaves] = useState<any[]>([]);
  const [emps, setEmps] = useState<any[]>([]);
  const [form, setForm] = useState({ employee_id: user?.employee_id || "", start_date: "", end_date: "", type: "PL", note: "" });
  const [impact, setImpact] = useState<any | null>(null);
  const load = () => api("/api/leaves").then(setLeaves).catch((e) => toast(e.message, true));
  useEffect(() => { load(); api("/api/employees").then(setEmps).catch(() => {}); }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/leaves", { body: { ...form, end_date: form.end_date || form.start_date } });
      toast("Leave requested."); load();
    } catch (err: any) { toast(err.message, true); }
  };
  const act = async (id: string, action: string) => {
    try {
      const r = await api(`/api/leaves/${id}/${action}`, { body: {} });
      await load(); await reload();
      if (r.impact) setImpact(r.impact);
      else toast(`Leave ${r.status.toLowerCase()}.`);
    } catch (err: any) { toast(err.message, true); }
  };
  const self = user?.role === "EMPLOYEE";

  return (
    <>
      <div className="page-head"><div><h1>Leaves &amp; comp-offs</h1><p>Approving a leave immediately re-validates the current roster and shows the gaps it opens.</p></div></div>
      <div className="grid g-dash">
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Employee</th><th>Dates</th><th>Type</th><th>Status</th><th /></tr></thead>
            <tbody>
              {leaves.map((l) => (
                <tr key={l.id}>
                  <td>{l.employee}</td>
                  <td className="num">{fmtDay(l.start_date)}{l.end_date !== l.start_date ? ` → ${fmtDay(l.end_date)}` : ""}</td>
                  <td>{({ COMP_OFF: "Comp-off", PL: "Planned", SL: "Sick", AWAY: "Unavailable" } as Record<string, string>)[l.type] ?? l.type}</td>
                  <td><span className={`tag ${l.status === "APPROVED" ? "ok" : l.status === "PENDING" ? "soft" : "neutral"}`}>{l.status.toLowerCase()}</span></td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {canEditRoster(user) && l.status === "PENDING" && <><button className="btn sm primary" onClick={() => act(l.id, "approve")}>Approve</button> <button className="btn sm ghost" onClick={() => act(l.id, "reject")}>Reject</button></>}
                    {l.status === "APPROVED" && (canEditRoster(user) || l.employee_id === user?.employee_id) && <button className="btn sm ghost" onClick={() => act(l.id, "cancel")}>Cancel</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!["AUDITOR", "BRAND_OWNER"].includes(user?.role || "") && (
          <form className="card" onSubmit={submit}>
            <h2>Request leave</h2>
            {!self && (
              <label className="field">Employee
                <select id="leave-emp" className="input" required value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })}>
                  <option value="">Choose…</option>{emps.filter((e) => e.active).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                </select>
              </label>
            )}
            <div className="grid g2">
              <label className="field">From<input id="leave-from" className="input" type="date" required value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></label>
              <label className="field">To<input id="leave-to" className="input" type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></label>
            </div>
            <label className="field">Type
              <select id="leave-type" className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value="PL">Planned leave</option><option value="SL">Sick leave</option><option value="COMP_OFF">Comp-off</option>
              </select>
            </label>
            <label className="field">Note<input id="leave-note" className="input" maxLength={200} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
              <small className="subtle">Visible to you, your pod lead and managers only. No medical details needed.</small></label>
            <button className="btn primary" style={{ alignSelf: "flex-start" }}>Submit request</button>
          </form>
        )}
      </div>
      {impact && (
        <Modal title={impact.conflicts.length ? "Approved: this opens gaps" : "Approved: no coverage impact"} onClose={() => setImpact(null)}>
          {impact.conflicts.length === 0 ? <p className="muted">The current roster still meets every requirement on those dates.</p> : (
            <>
              <p className="muted">The roster was re-validated with the new leave. Open a gap to see ranked backups, or run Auto-repair to fix them all with minimal changes.</p>
              <div className="list">{impact.conflicts.map((c: any) => (
                <button key={c.key} className="list-item" style={{ border: 0, background: "none", textAlign: "left" }}
                        onClick={() => { const live = grid?.conflicts.find((x) => x.key === c.key); setImpact(null); openConflict(live || c); }}>
                  <span className="sev-dot HARD" /><div className="grow"><b>{c.title}</b><small>{fmtDay(c.date)} · {c.detail}</small></div>
                </button>
              ))}</div>
            </>
          )}
        </Modal>
      )}
    </>
  );
}
