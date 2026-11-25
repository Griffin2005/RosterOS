import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  AlertTriangle, Bell, CalendarDays, ChevronLeft, ChevronRight, ClipboardList, FileSpreadsheet, LayoutDashboard,
  LogOut, Plane, Search, Settings2, Store, Users,
} from "lucide-react";
import { api, ROLE_LABEL } from "./api";
import { AppProvider, useApp } from "./ctx";
import { Assistant } from "./components/Assistant";
import { ConflictDrawer } from "./components/ConflictDrawer";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import RosterPage from "./pages/Roster";
import ConflictsPage from "./pages/Conflicts";
import PeoplePage from "./pages/People";
import BrandsPage from "./pages/Brands";
import LeavesPage from "./pages/Leaves";
import SheetsPage from "./pages/Sheets";
import AuditPage from "./pages/Audit";

export default function App() {
  return (
    <AppProvider>
      <Root />
    </AppProvider>
  );
}

function Root() {
  const { user, toasts } = useApp();
  return (
    <>
      {user ? <Shell /> : <Login />}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.err ? "err" : ""}`}>{t.msg}</div>)}
      </div>
    </>
  );
}

export function MonthPicker() {
  const { month, setMonth } = useApp();
  const [y, m] = month.split("-").map(Number);
  const shift = (n: number) => {
    const d = new Date(y, m - 1 + n, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  };
  return (
    <div className="month">
      <button onClick={() => shift(-1)} aria-label="Previous month"><ChevronLeft size={16} /></button>
      <b>{new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</b>
      <button onClick={() => shift(1)} aria-label="Next month"><ChevronRight size={16} /></button>
    </div>
  );
}

function Shell() {
  const { user, logout, grid, search, setSearch } = useApp();
  const [notes, setNotes] = useState<any[]>([]);
  const [showNotes, setShowNotes] = useState(false);
  const openHard = grid ? grid.conflicts.filter((c) => c.severity === "HARD" && !c.acknowledged).length : 0;
  const manage = user && ["SUPER_ADMIN", "OPS_MANAGER", "AUDITOR"].includes(user.role);

  useEffect(() => { api("/api/notifications").then(setNotes).catch(() => {}); }, [grid?.roster.id]);
  const initials = (user?.username || "?").replace(/[^a-z]/gi, " ").trim().split(/\s+/).map((s) => s[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><i /></span><b>RosterOS</b></div>
        <div className="nav-label">Menu</div>
        <nav className="nav">
          <NavLink to="/" end><LayoutDashboard size={18} />Dashboard</NavLink>
          <NavLink to="/roster"><CalendarDays size={18} />Roster</NavLink>
          <NavLink to="/conflicts"><AlertTriangle size={18} />Conflicts{openHard > 0 && <span className="badge crit">{openHard}</span>}</NavLink>
          <NavLink to="/leaves"><Plane size={18} />Leaves</NavLink>
          <NavLink to="/people"><Users size={18} />People</NavLink>
          <NavLink to="/brands"><Store size={18} />Brands &amp; rules</NavLink>
        </nav>
        <div className="nav-label">General</div>
        <nav className="nav">
          <NavLink to="/sheets"><FileSpreadsheet size={18} />Google Sheets</NavLink>
          {manage && <NavLink to="/audit"><ClipboardList size={18} />Audit log</NavLink>}
          <NavLink to="/brands#solver"><Settings2 size={18} />Solver settings</NavLink>
          <button onClick={logout}><LogOut size={18} />Sign out</button>
        </nav>
        <div className="side-card">
          <b>Rules live in Google Sheets</b>
          <p>Ops edits coverage in the Sheet; RosterOS validates and versions every change.</p>
          <NavLink to="/sheets" className="btn sm" style={{ alignSelf: "flex-start", background: "#fff", border: 0 }}>Open sheet</NavLink>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <label className="search"><Search size={16} /><input placeholder="Search people or brands" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search people or brands" /></label>
          <div className="spacer" />
          <MonthPicker />
          <div style={{ position: "relative" }}>
            <button className="icon-btn" aria-label="Notifications" onClick={() => setShowNotes((s) => !s)}><Bell size={18} />{notes.length > 0 && <span className="dot" />}</button>
            {showNotes && (
              <div className="card" style={{ position: "absolute", right: 0, top: 48, width: 340, zIndex: 30, maxHeight: 380, overflow: "auto" }}>
                <h3>Notifications</h3>
                {notes.length === 0 && <p className="muted">Nothing new.</p>}
                {notes.map((n) => <div key={n.id} className="list-item"><div className="grow"><b>{n.message}</b><small>{new Date(n.at).toLocaleString()}</small></div></div>)}
              </div>
            )}
          </div>
          <div className="user-chip">
            <span className="avatar">{initials}</span>
            <div><b>{user?.username}</b><span>{ROLE_LABEL[user?.role || ""]} · {user?.scope_level.toLowerCase()}</span></div>
          </div>
        </header>
        <section className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/roster" element={<RosterPage />} />
            <Route path="/conflicts" element={<ConflictsPage />} />
            <Route path="/leaves" element={<LeavesPage />} />
            <Route path="/people" element={<PeoplePage />} />
            <Route path="/brands" element={<BrandsPage />} />
            <Route path="/sheets" element={<SheetsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </section>
      </main>
      <ConflictDrawer />
      {user && ["SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD", "AUDITOR"].includes(user.role) && <Assistant />}
    </div>
  );
}
