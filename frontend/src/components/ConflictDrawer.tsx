import { useEffect, useState } from "react";
import { CheckCircle2, Wand2 } from "lucide-react";
import { api, canEditRoster, canManage, fmtDay, waitJob, type Suggestion } from "../api";
import { useApp } from "../ctx";
import { Drawer } from "./Modal";

export function ConflictDrawer() {
  const { conflict: c, openConflict, grid, user, reload, toast, setRosterId } = useApp();
  const [sugg, setSugg] = useState<Suggestion[] | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const brandLines = c && grid ? grid.coverage.filter((x) => x.brand_id === c.brand_id).map((x) => x.line_id) : [];

  useEffect(() => {
    setSugg(null); setReason("");
    if (!c || !grid || !canEditRoster(user) || !["C01", "C02", "C08"].includes(c.code) || !c.date) return;
    const lines = c.code === "C08" ? grid.coverage.filter((x) => x.days[grid.days.indexOf(c.date!)]?.req > x.days[grid.days.indexOf(c.date!)]?.heads.length).map((x) => x.line_id) : brandLines;
    api(`/api/rosters/${grid.roster.id}/suggest`, { body: { date: c.date, line_ids: lines } })
      .then((r) => setSugg(r.suggestions)).catch((e) => toast(e.message, true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c?.key, grid?.roster.id]);

  if (!c || !grid) return null;
  const close = () => openConflict(null);
  const names = Object.fromEntries(grid.employees.map((e) => [e.id, e.name]));

  const apply = async (s: Suggestion) => {
    setBusy(s.employee_id);
    try {
      const res = await api(`/api/rosters/${grid.roster.id}/edits`, { body: { edits: s.actions } });
      setRosterId(null); await reload();
      toast(res.introduced.length ? `Applied, but ${res.introduced.length} new conflict(s) appeared.` : `Applied: ${s.name} covers. Saved to draft v${res.roster.version}.`, !!res.introduced.length);
      close();
    } catch (e: any) { toast(e.message, true); } finally { setBusy(null); }
  };
  const ack = async () => {
    setBusy("ack");
    try { await api(`/api/rosters/${grid.roster.id}/ack`, { body: { key: c.key, reason } }); await reload(); toast("Acknowledged with your reason."); close(); }
    catch (e: any) { toast(e.message, true); } finally { setBusy(null); }
  };
  const repair = async () => {
    setBusy("repair");
    try {
      const { job_id } = await api(`/api/rosters/${grid.roster.id}/repair`, { body: {} });
      const j = await waitJob(job_id);
      if (j.status !== "DONE") throw new Error(j.error || "Repair failed");
      setRosterId(null); await reload(); toast("Repair draft ready: only cells near the conflicts changed."); close();
    } catch (e: any) { toast(e.message, true); } finally { setBusy(null); }
  };

  const ex = c.explanation || {};
  return (
    <Drawer onClose={close} title={<><span className={`tag ${c.severity.toLowerCase()}`}>{c.code} · {c.name.replace(/_/g, " ").toLowerCase()}</span><h2 style={{ marginTop: 8 }}>{c.title}</h2><p className="muted">{c.date ? fmtDay(c.date) : "Whole month"}</p></>}>
      <p>{c.detail}</p>
      {c.acknowledged && <div className="tag ok" style={{ padding: 10, whiteSpace: "normal" }}><CheckCircle2 size={14} /> Acknowledged by {c.acknowledged.by}: {c.acknowledged.reason}</div>}
      {ex.assignees && (
        <div className="card" style={{ boxShadow: "none", border: "1px solid var(--line)" }}>
          <h3>Who is trained on this line</h3>
          <div className="list">{ex.assignees.map((a: any) => (
            <div className="list-item" key={a.employee_id}><span className="avatar sm">{a.name.split(" ").map((s: string) => s[0]).join("")}</span>
              <div className="grow"><b>{a.name}</b><small>{a.role.toLowerCase()} · {a.reason}</small></div></div>
          ))}</div>
        </div>
      )}
      {ex.load && <dl className="kv"><dt>Load</dt><dd>{ex.load}% of {ex.capacity}%</dd><dt>Lines</dt><dd>{ex.lines?.join(", ")}</dd></dl>}
      {ex.brands && <p className="muted">Brands affected: {ex.brands.join(", ")}</p>}
      {c.employee_id && !ex.assignees && <p className="subtle">Employee: {names[c.employee_id] || c.employee_id}</p>}

      {sugg && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3>Possible fixes, best first</h3>
          {sugg.length === 0 && <p className="muted">The line is covered now.</p>}
          {sugg.map((s) => (
            <div key={s.employee_id} className={`sugg ${s.verdict}`}>
              <div className="card-head">
                <div><b>{s.name}</b> <span className={`tag ${s.verdict === "RECOMMENDED" ? "ok" : s.verdict === "PARTIAL" ? "soft" : "neutral"}`}>{s.verdict.toLowerCase()}</span>{s.same_pod && <span className="subtle"> · same pod</span>}</div>
                {s.verdict !== "REJECTED" && canEditRoster(user) && <button className="btn sm primary" disabled={!!busy} onClick={() => apply(s)}>{busy === s.employee_id && <span className="spinner" />}Apply</button>}
              </div>
              {s.covers.length > 0 && <span className="subtle">Covers {s.covers.join(", ")} · cost {s.cost}</span>}
              <ul>{s.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </div>
          ))}
        </div>
      )}
      {canManage(user) && c.severity === "HARD" && (
        <div className="actions"><button className="btn" onClick={repair} disabled={!!busy}>{busy === "repair" ? <span className="spinner" /> : <Wand2 size={16} />}Auto-repair roster</button></div>
      )}
      {canManage(user) && c.severity === "HARD" && !c.acknowledged && (
        <div className="field">Can't fix it? Acknowledge with a reason so it can be published.
          <textarea id="ack-reason" className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Client agreed to pause ACC calls for the day" />
          <button className="btn ghost" style={{ alignSelf: "flex-start" }} disabled={!reason.trim() || !!busy} onClick={ack}>Acknowledge</button>
        </div>
      )}
    </Drawer>
  );
}
