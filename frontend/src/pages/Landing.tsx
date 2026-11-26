import { Link } from "react-router-dom";
import {
  ArrowRight, Bot, CalendarRange, CheckCircle2, FileSpreadsheet, GitBranch, KeyRound, LayoutGrid, LifeBuoy,
  LockKeyhole, Network, RefreshCcw, ScanSearch, ShieldCheck, Sparkles, Users,
} from "lucide-react";
import { useApp } from "../ctx";

const REPO = "https://github.com/Griffin2005/RosterOS";
const ARCH = "https://claude.ai/artifact/UnfEmv16yRrYjgDXsLBw2F";

export function Logo({ light = false }: { light?: boolean }) {
  return (
    <span className={`logo ${light ? "light" : ""}`}>
      <span className="brand-mark"><i /></span><b>RosterOS</b>
    </span>
  );
}

// A static, hand-arranged slice of a roster for the hero: one brand line with
// a gap on a leave day, and the backup the solver proposes.
const PEOPLE = [
  { n: "Meera", cells: "WWWWWOW LWWWWWO" },
  { n: "Arjun", cells: "WWOWWWW WWWOWWW" },
  { n: "Divya", cells: "OWWWWWW WWWWOWW" },
  { n: "Rohan (lead)", cells: "WWWWWOW OWWWWWW" },
];
const COVERAGE = "1111111 0111111";
const CODE: Record<string, string> = { W: "w", O: "o", L: "l", B: "b", " ": "sp" };

function HeroGrid() {
  return (
    <div className="lp-grid" aria-hidden="true">
      <div className="lp-grid-head">
        <b>Kesar Kitchen · CS</b><span className="tag hard">1 gap found</span>
      </div>
      {PEOPLE.map((p) => (
        <div className="lp-row" key={p.n}>
          <span className="lp-name">{p.n}</span>
          <div className="lp-cells">{[...p.cells].map((c, i) => <i key={i} className={CODE[c]} />)}</div>
        </div>
      ))}
      <div className="lp-row lp-cov">
        <span className="lp-name">Coverage</span>
        <div className="lp-cells">{[...COVERAGE].map((c, i) => <i key={i} className={c === " " ? "sp" : c === "0" ? "gap" : "ok"} />)}</div>
      </div>
      <div className="lp-fix">
        <Sparkles size={15} />
        <div><b>Suggested fix · Tue 8 Dec</b><span>Rohan covers as backup; his weekly off moves to Sun 13. 2 cells change.</span></div>
        <span className="tag ok">Recommended</span>
      </div>
    </div>
  );
}

const STEPS = [
  { icon: FileSpreadsheet, t: "Rules come from the Sheet", d: "Ops keeps operating calendars and minimum heads per brand and process in Google Sheets. Every import is validated, diffed and versioned." },
  { icon: Network, t: "The solver builds the month", d: "A CP-SAT model first proves the fewest possible uncovered slots, then optimises fair Sundays, preferences and backup use, without ever trading coverage away." },
  { icon: ScanSearch, t: "An independent validator checks it", d: "Separate code re-checks every rule and explains each conflict: who is trained, why each person can't cover, and what would fix it." },
  { icon: RefreshCcw, t: "Changes repair, not rebuild", d: "A leave approved after publishing re-solves only the affected window, keeps everything else frozen and shows the minimal diff for sign-off." },
];

const FEATURES = [
  { icon: LayoutGrid, t: "Five views of one month", d: "Company, pod, brand, process and employee, each filtered server-side to what the viewer may see." },
  { icon: CheckCircle2, t: "Hard rules vs preferences", d: "Coverage, leave, weekly offs, streaks and capacity are constraints; preferred days off yield to client coverage." },
  { icon: LifeBuoy, t: "Backup recommendations", d: "Ranked candidates with their cost: same pod, load headroom, streak risk and the weekly off that has to move." },
  { icon: Users, t: "Single- and multi-person brands", d: "80% of brands rest on one owner; the model knows who backs them up and flags brands with no trained backup." },
  { icon: FileSpreadsheet, t: "Excel with live formulas", d: "Exports are linked workbooks: edit a status on the Roster sheet and coverage, pods and KPIs recalculate across sheets." },
  { icon: Bot, t: "Assistant that explains", d: "Ask why a slot is empty or what a leave would break. It drafts changes for review and never publishes." },
  { icon: CalendarRange, t: "Holidays and comp-offs", d: "Regional holiday calendars, comp-off credits for holiday work, and per-brand rules for Sundays and public holidays." },
  { icon: GitBranch, t: "Versions and approvals", d: "Draft, publish, supersede. Hard conflicts must be fixed or acknowledged with a reason before anything goes live." },
];

const SECURITY = [
  { icon: KeyRound, t: "Argon2id password hashing", d: "OWASP-recommended parameters; passwords are never stored, logged or shown, and old hashes upgrade on sign-in." },
  { icon: LockKeyhole, t: "Hardened sessions", d: "httpOnly SameSite=Strict cookie, CSRF token bound to the session, instant revocation on password or role change." },
  { icon: ShieldCheck, t: "Brute-force protection", d: "12+ character policy with live feedback, lockout after 5 failures, per-network rate limits, identical errors for unknown users." },
  { icon: Users, t: "Least privilege", d: "Six roles, five scope levels. Nobody can grant a role at or above their own; the last admin can't be removed." },
  { icon: ScanSearch, t: "Privacy by design", d: "No contact data stored, the AI sees employee codes instead of names, leave reasons stay with the people who need them." },
  { icon: GitBranch, t: "Everything audited", d: "Sign-ins, lockouts, team changes, exports and every roster edit land in an append-only audit log." },
];

export default function Landing() {
  const { user } = useApp();
  const cta = user ? { to: "/dashboard", label: "Open the app" } : { to: "/login", label: "Sign in" };
  return (
    <div className="lp">
      <header className="lp-nav">
        <Link to="/" className="lp-logo-link" aria-label="RosterOS home"><Logo /></Link>
        <nav aria-label="Sections">
          <a href="#how">How it works</a><a href="#features">Features</a><a href="#security">Security</a><a href="#stack">Architecture</a>
        </nav>
        <Link to={cta.to} className="btn primary">{cta.label}<ArrowRight size={16} /></Link>
      </header>

      <section className="lp-hero">
        <div className="lp-hero-copy">
          <span className="lp-eyebrow">Smart roster management for multi-brand CX teams</span>
          <h1>Every brand covered, every day of the month.</h1>
          <p>RosterOS plans monthly rosters across brands, processes and pods. An optimisation solver proves the best possible coverage, flags what can't be met and why, and repairs the roster when someone's availability changes.</p>
          <div className="actions">
            <Link to={cta.to} className="btn primary lg">{cta.label}<ArrowRight size={16} /></Link>
            <a href="#how" className="btn lg">See how it works</a>
          </div>
        </div>
        <HeroGrid />
      </section>

      <section className="lp-stats" aria-label="Sample data at a glance">
        {[["32", "people"], ["22", "brands"], ["46", "brand × process lines"], ["4", "pods with leads"], ["1,272", "staffed line-days a month"], ["~1 s", "to prove minimum gaps"]].map(([v, l]) => (
          <div key={l}><b>{v}</b><span>{l}</span></div>
        ))}
      </section>

      <section id="how" className="lp-section">
        <div className="lp-section-head"><span className="lp-eyebrow">How it works</span><h2>Solve the scheduling problem, then keep it solved</h2></div>
        <ol className="lp-steps">
          {STEPS.map((s, i) => (
            <li key={s.t}><span className="lp-step-n">{i + 1}</span><s.icon size={22} /><h3>{s.t}</h3><p>{s.d}</p></li>
          ))}
        </ol>
      </section>

      <section id="features" className="lp-section">
        <div className="lp-section-head"><span className="lp-eyebrow">Features</span><h2>Built around the operations manager's month</h2></div>
        <div className="lp-cards">
          {FEATURES.map((f) => <div key={f.t} className="lp-card"><f.icon size={20} /><h3>{f.t}</h3><p>{f.d}</p></div>)}
        </div>
      </section>

      <section id="security" className="lp-section lp-dark">
        <div className="lp-section-head"><span className="lp-eyebrow">Security & privacy</span><h2>Roster data is personal data. It's treated that way.</h2></div>
        <div className="lp-cards">
          {SECURITY.map((f) => <div key={f.t} className="lp-card"><f.icon size={20} /><h3>{f.t}</h3><p>{f.d}</p></div>)}
        </div>
      </section>

      <section id="stack" className="lp-section">
        <div className="lp-section-head"><span className="lp-eyebrow">Architecture</span><h2>Plain, inspectable parts</h2></div>
        <div className="lp-stack">
          {[["Solver", "Google OR-Tools CP-SAT, lexicographic and decomposed by pod"], ["API", "FastAPI, SQLAlchemy, Argon2id, JWT cookie sessions"],
            ["Data", "PostgreSQL with streaming replica and WAL archive"], ["Workers", "Redis queue; solver workers hold no database credentials"],
            ["Integrations", "Google Sheets, Drive and Calendar APIs (simulated)"], ["Web", "React, TypeScript, code-split routes"]].map(([k, v]) => (
            <div key={k}><b>{k}</b><span>{v}</span></div>
          ))}
        </div>
        <div className="actions" style={{ justifyContent: "center" }}>
          <a className="btn" href={ARCH} target="_blank" rel="noopener noreferrer">Architecture document</a>
          <a className="btn" href={REPO} target="_blank" rel="noopener noreferrer">Source on GitHub</a>
        </div>
      </section>

      <section className="lp-cta">
        <h2>See December's roster, its one unavoidable gap, and how it was handled.</h2>
        <Link to={cta.to} className="btn lg">{cta.label}<ArrowRight size={16} /></Link>
      </section>

      <footer className="lp-foot">
        <Logo /><span>All brands, people and data in this demo are fictional.</span>
      </footer>
    </div>
  );
}
