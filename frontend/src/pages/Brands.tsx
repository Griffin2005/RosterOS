import { Fragment, useEffect, useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { api, canManage, WD } from "../api";
import { useApp } from "../ctx";
import { Modal } from "../components/Modal";

const KINDS = ["ALL_DAYS", "NO_PH", "NO_SUN_PH", "CUSTOM"];
const KIND_LABEL: Record<string, string> = { ALL_DAYS: "365 days", NO_PH: "Daily, PH off", NO_SUN_PH: "Sun & PH off", CUSTOM: "Custom days" };
const WEIGHT_HELP: Record<string, string> = {
  gap: "Cost per missing head (always the largest)", change: "Repair: cost per changed day", backup: "Using a backup instead of a primary",
  fairness: "Spread of Sunday work across owners", preference: "Working a preferred off-day", ph_work: "Working a public holiday",
  extra_off: "Giving more offs than needed", time_limit_s: "Solver time limit (seconds)",
};

export default function BrandsPage() {
  const { user, toast, reload, search } = useApp();
  const manage = canManage(user);
  const [brands, setBrands] = useState<any[]>([]);
  const [lines, setLines] = useState<any[]>([]);
  const [pods, setPods] = useState<any[]>([]);
  const [procs, setProcs] = useState<any[]>([]);
  const [versions, setVersions] = useState<any[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<any | null>(null);
  const [lineEdit, setLineEdit] = useState<any | null>(null);
  const [newBrand, setNewBrand] = useState<any | null>(null);
  const [newProc, setNewProc] = useState<any | null>(null);

  const load = () => Promise.all([api("/api/brands"), api("/api/service-lines"), api("/api/pods"), api("/api/processes"), api("/api/rules/versions"), api("/api/settings/solver")])
    .then(([b, l, p, pr, v, w]) => { setBrands(b); setLines(l); setPods(p); setProcs(pr); setVersions(v); setWeights(w); }).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);
  useEffect(() => { if (location.hash === "#solver") document.getElementById("solver")?.scrollIntoView(); }, [weights]);

  const podName = Object.fromEntries(pods.map((p) => [p.id, p.name]));
  const q = search.toLowerCase();

  const doPreview = async () => { try { setPreview(await api("/api/rules/preview")); } catch (e: any) { toast(e.message, true); } };
  const doImport = async () => {
    try { const r = await api("/api/rules/import", { body: {} }); toast(`Rule set v${r.version} imported from the Sheet.`); setPreview(null); load(); reload(); }
    catch (e: any) { toast(e.message, true); }
  };
  const saveLine = async () => {
    try {
      const wmin: Record<string, number> = {};
      String(lineEdit.weekday_min_text || "").split(";").map((s: string) => s.trim()).filter(Boolean).forEach((p: string) => {
        const [d, n] = p.split(":"); const i = WD.findIndex((w) => w.toLowerCase() === d.trim().slice(0, 3).toLowerCase()); if (i >= 0) wmin[String(i)] = +n;
      });
      const body = { brand_id: lineEdit.brand_id, process_id: lineEdit.process_id, calendar_kind: lineEdit.calendar_kind, weekday_mask: lineEdit.weekday_mask,
                     min_heads: +lineEdit.min_heads, weekday_min: wmin, shift: lineEdit.shift, active: lineEdit.active };
      if (lineEdit.id) await api(`/api/service-lines/${lineEdit.id}`, { method: "PUT", body });
      else await api("/api/service-lines", { body });
      toast("Saved and written back to the Google Sheet. The roster is re-validated against it."); setLineEdit(null); load(); reload();
    } catch (e: any) { toast(e.message, true); }
  };
  const saveWeights = async () => {
    try { await api("/api/settings/solver", { method: "PUT", body: weights }); toast("Solver settings saved. They apply to the next generate or repair."); }
    catch (e: any) { toast(e.message, true); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Brands &amp; working rules</h1><p>Each brand runs one or more service lines (brand × process). Operating calendars and minimum heads come from the Google Sheet and are versioned on import.</p></div>
        {manage && <div className="actions">
          <button className="btn" onClick={doPreview}><RefreshCw size={16} />Check Sheet for changes</button>
          <button className="btn ghost" onClick={() => setNewProc({ code: "", name: "" })}><Plus size={16} />Process</button>
          <button className="btn primary" onClick={() => setNewBrand({ name: "", pod_id: pods[0]?.id, tier: "C" })}><Plus size={16} />Brand</button>
        </div>}
      </div>

      <div className="grid g4">
        <div className="card kpi hero"><span className="lab">Brands</span><span className="val">{brands.length}</span><span className="foot">{brands.filter((b) => b.primary_people === 1).length} run by one dedicated person ({brands.length ? Math.round(brands.filter((b) => b.primary_people === 1).length / brands.length * 100) : 0}%)</span></div>
        <div className="card kpi"><span className="lab">Service lines</span><span className="val">{lines.filter((l) => l.active).length}</span><span className="foot">{lines.filter((l) => l.calendar_kind === "ALL_DAYS" && l.active).length} run 365 days</span></div>
        <div className="card kpi"><span className="lab">Processes</span><span className="val">{procs.length}</span><span className="foot">{procs.map((p) => p.code).join(" · ")}</span></div>
        <div className="card kpi"><span className="lab">Rule set</span><span className="val">v{versions[0]?.version ?? "—"}</span><span className="foot">Sheet revision {versions[0]?.sheet_revision ?? "—"} · {versions[0] ? new Date(versions[0].imported_at).toLocaleString() : ""}</span></div>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Brand</th><th>Pod</th><th>Process</th><th>Calendar</th><th>Min heads</th><th>Day overrides</th><th>Shift</th><th>Rule set</th><th /></tr></thead>
          <tbody>
            {lines.filter((l) => !q || l.brand.toLowerCase().includes(q) || l.process.toLowerCase().includes(q)).map((l) => {
              const b = brands.find((x) => x.id === l.brand_id);
              return (
                <tr key={l.id} style={{ opacity: l.active ? 1 : .45 }}>
                  <td><b>{l.brand}</b> {b && <span className="subtle">· {b.primary_people === 1 ? "single" : `${b.primary_people} people`}</span>}</td>
                  <td>{podName[b?.pod_id] || "—"}</td>
                  <td><span className="tag neutral">{l.process}</span></td>
                  <td><span className={`tag ${l.calendar_kind === "ALL_DAYS" ? "ok" : "info"}`}>{KIND_LABEL[l.calendar_kind]}</span></td>
                  <td className="num">{l.min_heads}</td>
                  <td className="mono">{Object.entries(l.weekday_min || {}).map(([d, n]) => `${WD[+d]}:${n}`).join(" ") || "—"}</td>
                  <td className="mono">{l.shift}</td>
                  <td className="num">v{l.rule_set_version ?? "—"}</td>
                  <td>{manage && <button className="btn sm ghost" onClick={() => setLineEdit({ ...l, weekday_min_text: Object.entries(l.weekday_min || {}).map(([d, n]) => `${WD[+d]}:${n}`).join(";") })}>Edit</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {manage && <button className="btn ghost" style={{ alignSelf: "flex-start" }} onClick={() => setLineEdit({ brand_id: brands[0]?.id, process_id: procs[0]?.id, calendar_kind: "ALL_DAYS", min_heads: 1, weekday_min_text: "", shift: "09:00-18:00", active: true })}><Plus size={16} />Add service line</button>}

      <div className="grid g2">
        <div className="card">
          <h2>Rule set history</h2>
          <div className="list">{versions.map((v) => (
            <div key={v.version} className="list-item"><span className="tag ok">v{v.version}</span><div className="grow"><b>Sheet revision {v.sheet_revision}</b>
              <small>{new Date(v.imported_at).toLocaleString()} by {v.imported_by} · {v.summary?.added ?? 0} added, {v.summary?.changed ?? 0} changed, {v.summary?.removed ?? 0} removed, {v.summary?.errors ?? 0} row errors</small></div></div>
          ))}</div>
        </div>
        <div className="card" id="solver">
          <div className="card-head"><h2>Solver settings</h2>{user?.role === "SUPER_ADMIN" && <button className="btn sm primary" onClick={saveWeights}>Save</button>}</div>
          <p className="subtle">Weights decide priorities when not everything fits. A coverage gap always costs more than any set of preference violations.</p>
          <dl className="kv" style={{ gridTemplateColumns: "1fr 110px" }}>
            {Object.keys(WEIGHT_HELP).map((k) => (
              <Fragment key={k}><dt>{WEIGHT_HELP[k]}</dt><dd><input className="input" style={{ width: 100, padding: "5px 8px" }} type="number" value={weights[k] ?? ""} disabled={user?.role !== "SUPER_ADMIN"}
                onChange={(e) => setWeights({ ...weights, [k]: +e.target.value })} aria-label={WEIGHT_HELP[k]} /></dd></Fragment>
            ))}
          </dl>
        </div>
      </div>

      {preview && (
        <Modal title={preview.up_to_date ? "The Sheet matches the current rule set" : `Sheet revision ${preview.revision}: review changes`} onClose={() => setPreview(null)}>
          {preview.errors.length > 0 && (<div className="card" style={{ boxShadow: "none", border: "1.5px solid var(--warn)" }}><h3>Rows that will be skipped</h3>
            <div className="list">{preview.errors.map((e: any, i: number) => <div key={i} className="list-item"><span className="tag soft mono">{e.cell}</span><div className="grow">{e.message}</div></div>)}</div></div>)}
          {preview.added.length > 0 && <div><h3>New lines</h3><ul>{preview.added.map((a: any) => <li key={a.line}>{a.line} · {KIND_LABEL[a.after.calendar] || a.after.calendar} · {a.after.min_heads} head(s){a.new_process ? " · new process" : ""}</li>)}</ul></div>}
          {preview.changed.length > 0 && <div><h3>Changed</h3><ul>{preview.changed.map((c: any) => (
            <li key={c.line}><b>{c.line}</b>: {Object.keys(c.after).filter((k) => JSON.stringify(c.after[k]) !== JSON.stringify(c.before[k])).map((k) => `${k} ${JSON.stringify(c.before[k])} → ${JSON.stringify(c.after[k])}`).join(", ")}</li>
          ))}</ul></div>}
          {preview.removed.length > 0 && <div><h3>Removed (deactivated)</h3><ul>{preview.removed.map((r: string) => <li key={r}>{r}</li>)}</ul></div>}
          <p className="subtle">{preview.unchanged} line(s) unchanged · {preview.overrides.length} date override(s)</p>
          <div className="actions"><button className="btn primary" onClick={doImport} disabled={preview.up_to_date}>Import as rule set v{(preview.current_version ?? 0) + 1}</button><button className="btn ghost" onClick={() => setPreview(null)}>Close</button></div>
        </Modal>
      )}
      {lineEdit && (
        <Modal title={lineEdit.id ? `${lineEdit.brand} · ${lineEdit.process}` : "New service line"} onClose={() => setLineEdit(null)}>
          {!lineEdit.id && <div className="grid g2">
            <label className="field">Brand<select id="ln-brand" className="input" value={lineEdit.brand_id} onChange={(e) => setLineEdit({ ...lineEdit, brand_id: e.target.value })}>{brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
            <label className="field">Process<select id="ln-proc" className="input" value={lineEdit.process_id} onChange={(e) => setLineEdit({ ...lineEdit, process_id: e.target.value })}>{procs.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}</select></label>
          </div>}
          <label className="field">Operating calendar<select id="ln-cal" className="input" value={lineEdit.calendar_kind} onChange={(e) => setLineEdit({ ...lineEdit, calendar_kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></label>
          {lineEdit.calendar_kind === "CUSTOM" && <div className="chips">{WD.map((d, i) => {
            const on = ((lineEdit.weekday_mask || 0) >> i) & 1;
            return <button key={d} type="button" className="chip" style={on ? { background: "var(--g-800)", color: "#fff" } : {}} onClick={() => setLineEdit({ ...lineEdit, weekday_mask: (lineEdit.weekday_mask || 0) ^ (1 << i) })}>{d}</button>;
          })}</div>}
          <div className="grid g2">
            <label className="field">Minimum heads<input id="ln-heads" className="input" type="number" min={0} value={lineEdit.min_heads} onChange={(e) => setLineEdit({ ...lineEdit, min_heads: e.target.value })} /></label>
            <label className="field">Shift<input id="ln-shift" className="input" value={lineEdit.shift} onChange={(e) => setLineEdit({ ...lineEdit, shift: e.target.value })} placeholder="09:30-18:30" /></label>
          </div>
          <label className="field">Per-weekday minimums<input id="ln-wmin" className="input" value={lineEdit.weekday_min_text} onChange={(e) => setLineEdit({ ...lineEdit, weekday_min_text: e.target.value })} placeholder="Sat:2;Sun:2" /></label>
          <p className="subtle">Saving writes the change back to the Google Sheet and imports it as a new rule set, so the Sheet stays the single source of truth.</p>
          <div className="actions"><button className="btn primary" onClick={saveLine}>Save</button><button className="btn ghost" onClick={() => setLineEdit(null)}>Cancel</button></div>
        </Modal>
      )}
      {newBrand && (
        <Modal title="Add brand" onClose={() => setNewBrand(null)}>
          <label className="field">Name<input id="br-name" className="input" value={newBrand.name} onChange={(e) => setNewBrand({ ...newBrand, name: e.target.value })} /></label>
          <label className="field">Pod<select id="br-pod" className="input" value={newBrand.pod_id} onChange={(e) => setNewBrand({ ...newBrand, pod_id: e.target.value })}>{pods.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <p className="subtle">Next: add its service lines here or as rows in the Sheet, then assign people on the People page.</p>
          <div className="actions"><button className="btn primary" disabled={!newBrand.name.trim()} onClick={async () => { try { await api("/api/brands", { body: newBrand }); toast("Brand added."); setNewBrand(null); load(); } catch (e: any) { toast(e.message, true); } }}>Add brand</button></div>
        </Modal>
      )}
      {newProc && (
        <Modal title="Add process" onClose={() => setNewProc(null)}>
          <div className="grid g2">
            <label className="field">Code<input id="pr-code" className="input" value={newProc.code} onChange={(e) => setNewProc({ ...newProc, code: e.target.value })} placeholder="CHAT" /></label>
            <label className="field">Name<input id="pr-name" className="input" value={newProc.name} onChange={(e) => setNewProc({ ...newProc, name: e.target.value })} placeholder="Live chat" /></label>
          </div>
          <div className="actions"><button className="btn primary" disabled={!newProc.code.trim()} onClick={async () => { try { await api("/api/processes", { body: newProc }); toast("Process added."); setNewProc(null); load(); } catch (e: any) { toast(e.message, true); } }}>Add process</button></div>
        </Modal>
      )}
    </>
  );
}
