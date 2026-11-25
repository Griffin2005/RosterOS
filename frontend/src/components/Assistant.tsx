import { useEffect, useRef, useState } from "react";
import { Bot, Send, X } from "lucide-react";
import { api } from "../api";
import { useApp } from "../ctx";

interface Msg { role: "user" | "assistant"; content: string; tools?: string[] }

const STARTERS = [
  "What are the open hard conflicts and how do I fix them?",
  "Who covers Kesar Kitchen on Sundays this month?",
  "What breaks if Meera Iyer is on leave 14–15 Dec?",
  "Why is Bloom Basket ACC uncovered on the 22nd?",
];

export function Assistant() {
  const { grid, toast, reload } = useApp();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => { body.current?.scrollTo(0, body.current.scrollHeight); }, [msgs, busy]);

  const send = async (q: string) => {
    if (!q.trim() || !grid) return;
    const next: Msg[] = [...msgs, { role: "user", content: q.trim() }];
    setMsgs(next); setText(""); setBusy(true);
    try {
      const r = await api("/api/assistant/chat", {
        body: { roster_id: grid.roster.id, messages: next.map(({ role, content }) => ({ role, content })) },
      });
      setMsgs([...next, { role: "assistant", content: r.reply, tools: r.tool_calls.map((t: any) => t.tool) }]);
      if (r.tool_calls.some((t: any) => t.tool === "draft_change_request" && t.ok)) await reload();
    } catch (e: any) {
      toast(e.message, true);
      setMsgs(next);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return <button className="fab" onClick={() => setOpen(true)}><Bot size={18} />Ask the roster assistant</button>;
  return (
    <div className="chat" role="dialog" aria-label="Roster assistant">
      <div className="chat-head"><Bot size={20} /><div><h3>Roster assistant</h3><small style={{ color: "#B9DCC6" }}>Explains and proposes. Never publishes.</small></div>
        <button className="close" onClick={() => setOpen(false)} aria-label="Close assistant"><X size={16} /></button></div>
      <div className="chat-body" ref={body}>
        {msgs.length === 0 && (
          <>
            <div className="msg assistant">Ask about coverage, conflicts or what-if changes for {grid ? `the ${new Date(grid.roster.month).toLocaleDateString("en-GB", { month: "long", year: "numeric" })} roster` : "a roster"}. I look facts up with the same tools the app uses, and anything I change is saved as an unpublished draft.</div>
            <div className="chips">{STARTERS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}</div>
          </>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>{m.content}
            {m.tools && m.tools.length > 0 && <div className="tools">Looked up: {Array.from(new Set(m.tools)).join(", ").replace(/_/g, " ")}</div>}
          </div>
        ))}
        {busy && <div className="msg assistant"><span className="spinner" style={{ display: "inline-block", color: "var(--g-700)" }} /></div>}
      </div>
      <form className="chat-foot" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input id="assistant-input" className="input" style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} placeholder={grid ? "Ask about this roster" : "Generate a roster first"} disabled={!grid || busy} />
        <button className="btn primary" disabled={!grid || busy || !text.trim()} aria-label="Send"><Send size={16} /></button>
      </form>
    </div>
  );
}
