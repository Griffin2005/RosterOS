import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../ctx";

export default function AuditPage() {
  const { toast } = useApp();
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { api("/api/audit?limit=300").then(setRows).catch((e) => toast(e.message, true)); }, []);
  return (
    <>
      <div className="page-head"><div><h1>Audit log</h1><p>Every change to rules, assignments, leaves and roster cells, with who made it and what it was before.</p></div></div>
      <div className="table-wrap" style={{ maxHeight: "calc(100vh - 220px)" }}>
        <table className="data">
          <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Entity</th><th>Change</th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td className="num" style={{ whiteSpace: "nowrap" }}>{new Date(a.at).toLocaleString()}</td>
                <td>{a.actor}</td>
                <td><span className="tag neutral">{a.action.replace(/_/g, " ").toLowerCase()}</span></td>
                <td className="mono">{a.entity}</td>
                <td className="mono" style={{ maxWidth: 520, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={JSON.stringify(a.after)}>
                  {a.before ? `${JSON.stringify(a.before)} → ` : ""}{a.after ? JSON.stringify(a.after) : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
