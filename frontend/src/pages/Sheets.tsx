import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api, canManage } from "../api";
import { useApp } from "../ctx";

export default function SheetsPage() {
  const { user, toast } = useApp();
  const [which, setWhich] = useState<"rules" | "dashboards">("rules");
  const [sheet, setSheet] = useState<any | null>(null);
  const [tab, setTab] = useState("");
  const [rows, setRows] = useState<string[][]>([]);
  const [dirty, setDirty] = useState(false);
  const manage = canManage(user);

  const load = () => api(`/api/sheets/${which}`).then((s) => {
    setSheet(s);
    const first = Object.keys(s.tabs)[0] || "";
    setTab((t) => (t && s.tabs[t] ? t : first));
  }).catch((e) => toast(e.message, true));
  useEffect(() => { setTab(""); load(); }, [which]);
  useEffect(() => { if (sheet && tab) { setRows(sheet.tabs[tab].map((r: string[]) => [...r])); setDirty(false); } }, [sheet, tab]);

  const editable = which === "rules" && manage;
  const width = Math.max(0, ...rows.map((r) => r.length));
  const set = (i: number, j: number, v: string) => { setRows((rs) => rs.map((r, a) => a === i ? Object.assign([...r], { [j]: v }) : r)); setDirty(true); };
  const save = async () => {
    try {
      const s = await api(`/api/sheets/rules/${tab}`, { method: "PUT", body: { rows: rows.filter((r) => r.some((c) => c?.trim())) } });
      setSheet(s); toast(`Sheet saved (revision ${s.revision}). Go to Brands & rules → Check Sheet for changes to review and import.`);
    } catch (e: any) { toast(e.message, true); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Google Sheets</h1><p>The ops team keeps working rules in a Sheet; published rosters are mirrored to a dashboard workbook. This demo uses a mock with the same API as Google Sheets.</p></div>
        <div className="seg"><button className={which === "rules" ? "on" : ""} onClick={() => setWhich("rules")}>Rules &amp; Coverage</button><button className={which === "dashboards" ? "on" : ""} onClick={() => setWhich("dashboards")}>Roster dashboards</button></div>
      </div>
      {sheet && (
        <>
          <div className="actions" style={{ justifyContent: "space-between" }}>
            <div className="seg">{Object.keys(sheet.tabs).map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}</div>
            <div className="actions"><span className="subtle">Revision {sheet.revision}</span>
              {editable && <button className="btn ghost sm" onClick={() => { setRows([...rows, Array(width).fill("")]); setDirty(true); }}><Plus size={14} />Row</button>}
              {editable && <button className="btn primary sm" disabled={!dirty} onClick={save}>Save to Sheet</button>}</div>
          </div>
          {Object.keys(sheet.tabs).length === 0 && <div className="card empty"><p>Nothing pushed yet. Publish a roster to fill the dashboard workbook.</p></div>}
          {rows.length > 0 && (
            <div className="table-wrap" style={{ maxHeight: "calc(100vh - 300px)" }}>
              <table className="data sheet">
                <thead><tr><th className="rn" />{Array.from({ length: width }).map((_, j) => <th key={j} style={{ textAlign: "center" }}>{String.fromCharCode(65 + (j % 26))}{j >= 26 ? Math.floor(j / 26) : ""}</th>)}</tr></thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i}>
                      <td className="rn">{i + 1}</td>
                      {Array.from({ length: width }).map((_, j) => (
                        <td key={j} style={i === 0 ? { background: "var(--panel)", fontWeight: 600 } : {}}>
                          {editable && i > 0 ? <input value={r[j] ?? ""} onChange={(e) => set(i, j, e.target.value)} aria-label={`Row ${i + 1} column ${j + 1}`} />
                                         : <div style={{ padding: "6px 8px", whiteSpace: "nowrap", fontSize: 12.5 }}>{r[j]}</div>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
