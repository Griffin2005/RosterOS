"""Seed the sample dataset. Rules and coverage go through the real import path
(mock Google Sheet -> validate -> rule set v1), holidays through the Calendar
client, and the December roster through the solver.

Run:  python -m app.seed [--reset]
"""
from __future__ import annotations

import sys
from datetime import date

from sqlalchemy import select

from . import models as M
from . import sample_data as S
from .config import get_settings
from .db import Base, SessionLocal, engine, init_db
from .services import rosters as R
from .services.sheets_sync import apply_import, sync_holidays

DEMO_MONTH = date(2026, 12, 1)


def seed(publish_demo: bool = True) -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.scalar(select(M.UserAccount)) is not None:
            print("Database already seeded.")
            added = _ensure_demo_accounts(db)
            if added:
                print(f"Added {added} missing demo account(s).")
            _refresh_dashboard_mirror(db)
            return
        procs = {code: M.Process(code=code, name=name) for code, name in S.PROCESSES}
        db.add_all(procs.values())
        pods = {pid: M.Pod(id=pid, name=name) for pid, name, _ in S.PODS}
        db.add_all(pods.values())
        db.flush()
        emps = {}
        for code, name, pod, cal, prefs in S.EMPLOYEES:
            e = M.Employee(code=code, name=name, pod_id=pod, holiday_calendar_id=cal)
            db.add(e)
            db.flush()
            emps[code] = e
            for d in prefs:
                db.add(M.Preference(employee_id=e.id, kind="OFF_DAY", value=str(d)))
        for pid, _, lead in S.PODS:
            pods[pid].lead_id = emps[lead].id
        brands = {}
        for name, pod, tier in S.BRANDS:
            b = M.Brand(name=name, pod_id=pod, tier=tier)
            db.add(b)
            brands[name] = b
        db.commit()

        sync_holidays(db, date(2026, 1, 1), date(2027, 12, 31))
        result = apply_import(db, "seed")
        print(f"Rules imported from sheet: rule set v{result['version']}, "
              f"{len(result['added'])} lines, {len(result['errors'])} errors")

        lines = {(sl.brand.name, sl.process.code): sl for sl in db.scalars(select(M.ServiceLine))}
        for code, brand, proc, role, load in S.ASSIGNMENTS:
            db.add(M.Assignment(employee_id=emps[code].id, service_line_id=lines[(brand, proc)].id,
                                role=role, load_pct=load))
        db.flush()
        if S.LEAD_BACKUP_ALL_POD_LINES:
            lead_of = {pid: emps[lead].id for pid, _, lead in S.PODS}
            for (brand, proc), sl in lines.items():
                primary = [load for c, b, p, role, load in S.ASSIGNMENTS if b == brand and p == proc and role == "PRIMARY"]
                db.add(M.Assignment(employee_id=lead_of[brands[brand].pod_id], service_line_id=sl.id,
                                    role="BACKUP", load_pct=max(primary or [50])))
        for code, a, b, typ, status in S.LEAVES:
            db.add(M.Leave(employee_id=emps[code].id, start_date=date.fromisoformat(a),
                           end_date=date.fromisoformat(b), type=typ, status=status))
        db.commit()
        _ensure_demo_accounts(db)
        print(f"Seeded {len(emps)} employees, {len(brands)} brands, {len(lines)} service lines.")

        if publish_demo:
            job = R.start_job(db, "GENERATE", DEMO_MONTH, "seed", {"note": "Initial December roster"},
                              background=False)
            if job.status != "DONE":
                print("Demo roster generation failed:", job.error)
                return
            r = db.get(M.Roster, job.result_roster_id)
            ev = R.evaluate(db, r)
            for c in ev["conflicts"]:
                if c["severity"] == "HARD":
                    R.acknowledge(db, r.id, c["key"],
                                  "Priya and Ananya both on approved leave; client agreed to pause cart "
                                  "recovery calls for one day.", "seed")
            out = R.publish(db, r.id, "seed")
            print(f"December roster v{r.version} published ({r.solver_stats.get('wall_ms')} ms, "
                  f"{r.solver_stats.get('status')}); sheets push: {out['sheets'].get('ok')}")
    finally:
        db.close()


def _ensure_demo_accounts(db) -> int:
    """Create any demo account that does not exist yet, e.g. in a database
    seeded before that account was added. Existing accounts (including ones
    an admin changed or deactivated) are never touched. New accounts have no
    password: app/bootstrap.py sets it from deployment secrets at start-up,
    never at image build time."""
    have = set(db.scalars(select(M.UserAccount.username)))
    added = 0
    for username, full_name, role, level, scope in S.DEMO_USERS:
        if username in have:
            continue
        scope_id, emp_id = None, None
        if level == "POD":
            scope_id = scope
        elif level == "BRAND":
            brand = db.scalar(select(M.Brand).where(M.Brand.name == scope))
            if brand is None:
                continue
            scope_id = brand.id
        elif level == "SELF":
            emp = db.scalar(select(M.Employee).where(M.Employee.code == scope))
            if emp is None:
                continue
            emp_id = emp.id
        if role == "POD_LEAD":
            pod = db.get(M.Pod, scope)
            if pod is None:
                continue
            emp_id = pod.lead_id
        db.add(M.UserAccount(username=username, full_name=full_name, password_hash=None, role=role,
                             scope_level=level, scope_id=scope_id, employee_id=emp_id, created_by="seed"))
        added += 1
    db.commit()
    return added


def _refresh_dashboard_mirror(db) -> None:
    """The embedded Sheets mock keeps its workbooks in memory, so a database
    seeded earlier (e.g. baked into the image at build time) boots with an
    empty dashboard workbook. Re-push the latest published roster into it."""
    if get_settings().sheets_mode != "embedded":
        return
    r = db.scalars(select(M.Roster).where(M.Roster.status == "PUBLISHED")
                   .order_by(M.Roster.month.desc())).first()
    if r is None:
        return
    try:
        from .services.sheets_sync import push_dashboards
        ev = R.evaluate(db, r)
        push_dashboards(db, ev["problem"], ev["plan"], r)
        db.commit()
    except Exception as exc:  # the app works without the mirror
        db.rollback()
        print("Dashboard mirror refresh failed:", exc)


def reset() -> None:
    from . import models  # noqa: F401
    Base.metadata.drop_all(engine)
    from .integrations import google_mock
    google_mock.reset()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    seed()
