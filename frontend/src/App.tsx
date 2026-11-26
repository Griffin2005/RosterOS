import { lazy, Suspense, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle, Bell, CalendarDays, ChevronLeft, ChevronRight, ClipboardList, FileSpreadsheet, LayoutDashboard,
  LogOut, Plane, Search, Settings2, ShieldCheck, Store, UserCircle2, Users, UsersRound,
} from "lucide-react";
import { api, canSeeSecurity, canSeeTeam, ROLE_LABEL } from "./api";
import { AppProvider, useApp } from "./ctx";
import Landing, { Logo } from "./pages/Landing";
import Login from "./pages/Login";
import AccountPage, { ForcedPasswordChange } from "./pages/Account";   // needed before the app shell loads

// Route-level code splitting: the landing and sign-in pages load without the
// roster grid, the editors or the assistant.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const RosterPage = lazy(() => import("./pages/Roster"));
const ConflictsPage = lazy(() => import("./pages/Conflicts"));
const PeoplePage = lazy(() => import("./pages/People"));
const BrandsPage = lazy(() => import("./pages/Brands"));
const LeavesPage = lazy(() => import("./pages/Leaves"));
const SheetsPage = lazy(() => import("./pages/Sheets"));
const AuditPage = lazy(() => import("./pages/Audit"));
const TeamPage = lazy(() => import("./pages/Team"));
const SecurityPage = lazy(() => import("./pages/Security"));
const Assistant = lazy(() => import("./components/Assistant").then((m) => ({ default: m.Assistant })));
const ConflictDrawer = lazy(() => import("./components/ConflictDrawer").then((m) => ({ default: m.ConflictDrawer })));

export default function App() {
  return (
    <AppProvider>
      <Root />
    </AppProvider>
  );
}

function Root() {
  const { toasts } = useApp();
  return (
    <>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/*" element={<Protected />} />
      </Routes>
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.err ? "err" : ""}`}>{t.msg}</div>)}
      </div>
    </>
  );
}

function Splash() {
  return <div className="center-screen"><span className="spinner" aria-label="Loading" /></div>;
}

function Protected() {
  const { user, authChecked } = useApp();
  const loc = useLocation();
  if (!authChecked) return <Splash />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (user.must_change_password) return <ForcedPasswordChange />;
  return <Shell />;
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
  const navigate = useNavigate();
  const [notes, setNotes] = useState<any[]>([]);
  const [showNotes, setShowNotes] = useState(false);
  const openHard = grid ? grid.conflicts.filter((c) => c.severity === "HARD" && !c.acknowledged).length : 0;
  const audit = user && ["SUPER_ADMIN", "OPS_MANAGER", "AUDITOR"].includes(user.role);

  useEffect(() => { api("/api/notifications").then(setNotes).catch(() => {}); }, [grid?.roster.id]);
  const name = user?.full_name || user?.username || "?";
  const initials = name.replace(/[^a-z ]/gi, " ").trim().split(/\s+/).map((s) => s[0]).join("").slice(0, 2).toUpperCase();
  const signOut = async () => { await logout(); navigate("/"); };

  return (
    <div className="app">
      <aside className="sidebar">
        <Link to="/" className="brand" style={{ textDecoration: "none" }} aria-label="RosterOS overview"><Logo /></Link>
        <div className="nav-label">Plan</div>
        <nav className="nav">
          <NavLink to="/dashboard"><LayoutDashboard size={18} />Dashboard</NavLink>
          <NavLink to="/roster"><CalendarDays size={18} />Roster</NavLink>
          <NavLink to="/conflicts"><AlertTriangle size={18} />Conflicts{openHard > 0 && <span className="badge crit">{openHard}</span>}</NavLink>
          <NavLink to="/leaves"><Plane size={18} />Leaves</NavLink>
          <NavLink to="/people"><Users size={18} />People</NavLink>
          <NavLink to="/brands"><Store size={18} />Brands &amp; rules</NavLink>
          <NavLink to="/sheets"><FileSpreadsheet size={18} />Google Sheets</NavLink>
        </nav>
        <div className="nav-label">Admin</div>
        <nav className="nav">
          {canSeeTeam(user) && <NavLink to="/team"><UsersRound size={18} />Team</NavLink>}
          {canSeeSecurity(user) && <NavLink to="/security"><ShieldCheck size={18} />Security</NavLink>}
          {audit && <NavLink to="/audit"><ClipboardList size={18} />Audit log</NavLink>}
          <NavLink to="/brands#solver" end><Settings2 size={18} />Solver settings</NavLink>
          <NavLink to="/account"><UserCircle2 size={18} />Your account</NavLink>
          <button onClick={signOut}><LogOut size={18} />Sign out</button>
        </nav>
        <div className="side-card">
          <b>Rules live in Google Sheets</b>
          <p>Ops edits coverage in the Sheet; RosterOS validates and versions every change.</p>
          <NavLink to="/sheets" className="btn sm" style={{ alignSelf: "flex-start", background: "#fff", border: 0 }}>Open sheet</NavLink>
        </div>
      </aside>
      <main className="main" id="main">
        <header className="topbar">
          <label className="search"><Search size={16} /><input placeholder="Search people or brands" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search people or brands" /></label>
          <div className="spacer" />
          <MonthPicker />
          <div style={{ position: "relative" }}>
            <button className="icon-btn" aria-label="Notifications" aria-expanded={showNotes} onClick={() => setShowNotes((s) => !s)}><Bell size={18} />{notes.length > 0 && <span className="dot" />}</button>
            {showNotes && (
              <div className="card popover">
                <h3>Notifications</h3>
                {notes.length === 0 && <p className="muted">Nothing new.</p>}
                {notes.map((n) => <div key={n.id} className="list-item"><div className="grow"><b>{n.message}</b><small>{new Date(n.at).toLocaleString()}</small></div></div>)}
              </div>
            )}
          </div>
          <Link to="/account" className="user-chip" title="Your account">
            <span className="avatar">{initials}</span>
            <div><b>{name}</b><span>{ROLE_LABEL[user?.role || ""]} · {user?.scope_level.toLowerCase()}</span></div>
          </Link>
        </header>
        <section className="content">
          <Suspense fallback={<div className="card empty"><span className="spinner" /></div>}>
            <Routes>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/roster" element={<RosterPage />} />
              <Route path="/conflicts" element={<ConflictsPage />} />
              <Route path="/leaves" element={<LeavesPage />} />
              <Route path="/people" element={<PeoplePage />} />
              <Route path="/brands" element={<BrandsPage />} />
              <Route path="/sheets" element={<SheetsPage />} />
              <Route path="/audit" element={audit ? <AuditPage /> : <Navigate to="/dashboard" />} />
              <Route path="/team" element={canSeeTeam(user) ? <TeamPage /> : <Navigate to="/dashboard" />} />
              <Route path="/security" element={canSeeSecurity(user) ? <SecurityPage /> : <Navigate to="/dashboard" />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </Suspense>
        </section>
      </main>
      <Suspense fallback={null}>
        <ConflictDrawer />
        {user && ["SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD", "AUDITOR"].includes(user.role) && <Assistant />}
      </Suspense>
    </div>
  );
}
