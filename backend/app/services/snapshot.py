"""Database -> domain Problem / Plan conversion."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from ..config import get_settings
from ..domain.types import (Assignment, Cell, Employee, Plan, Problem, ServiceLine, Status, Weights)


def month_bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    return start, start.replace(day=monthrange(start.year, start.month)[1])


def load_weights(db: Session) -> Weights:
    s = get_settings()
    w = Weights(time_limit_s=s.solver_time_limit_s, workers=s.solver_workers)
    for row in db.scalars(select(M.SolverSetting)):
        if hasattr(w, row.key):
            cur = getattr(w, row.key)
            setattr(w, row.key, type(cur)(row.value))
    return w


def build_problem(db: Session, month: date, *, baseline: Plan | None = None,
                  repair_window: tuple[date, date] | None = None,
                  locks_from: Plan | None = None) -> Problem:
    start, end = month_bounds(month)
    lead_ids = {pid for pid in db.scalars(select(M.Pod.lead_id)) if pid}
    prefs: dict[str, list[int]] = {}
    for pr in db.scalars(select(M.Preference).where(M.Preference.kind == "OFF_DAY")):
        prefs.setdefault(pr.employee_id, []).append(int(pr.value))

    emps = [Employee(id=e.id, code=e.code, name=e.name, pod_id=e.pod_id or "", capacity=e.capacity,
                     weekly_offs=e.weekly_offs, max_consecutive=e.max_consecutive,
                     holiday_calendar_id=e.holiday_calendar_id,
                     preferred_off_weekdays=tuple(sorted(prefs.get(e.id, []))), is_lead=e.id in lead_ids)
            for e in db.scalars(select(M.Employee).where(M.Employee.active.is_(True)).order_by(M.Employee.code))]
    emp_ids = {e.id for e in emps}

    lines = []
    for sl in db.scalars(select(M.ServiceLine).join(M.Brand).where(
            M.ServiceLine.active.is_(True), M.Brand.active.is_(True))):
        lines.append(ServiceLine(
            id=sl.id, brand_id=sl.brand_id, brand_name=sl.brand.name, process_code=sl.process.code,
            pod_id=sl.brand.pod_id or "", weekday_mask=sl.weekday_mask, works_ph=sl.works_ph,
            min_heads=sl.min_heads, weekday_min={int(k): v for k, v in (sl.weekday_min or {}).items()},
            shift_start=sl.shift_start, shift_end=sl.shift_end, calendar_kind=sl.calendar_kind))
    line_ids = {l.id for l in lines}

    assigns = []
    for a in db.scalars(select(M.Assignment)):
        if a.employee_id not in emp_ids or a.service_line_id not in line_ids:
            continue
        if a.valid_from and a.valid_from > end or a.valid_to and a.valid_to < start:
            continue
        assigns.append(Assignment(a.employee_id, a.service_line_id, a.role, a.load_pct))

    leaves: dict[tuple[str, date], Status] = {}
    for lv in db.scalars(select(M.Leave).where(M.Leave.status == "APPROVED",
                                               M.Leave.start_date <= end, M.Leave.end_date >= start)):
        d = max(lv.start_date, start)
        while d <= min(lv.end_date, end):
            leaves[(lv.employee_id, d)] = Status.COMP_OFF if lv.type == "COMP_OFF" else Status.LEAVE
            d += timedelta(days=1)

    holidays: dict[str, set[date]] = {}
    for h in db.scalars(select(M.Holiday).where(M.Holiday.on_date >= start, M.Holiday.on_date <= end)):
        holidays.setdefault(h.calendar_id, set()).add(h.on_date)

    overrides = {(o.service_line_id, o.on_date): o.min_heads for o in db.scalars(
        select(M.CoverageOverride).where(M.CoverageOverride.on_date >= start, M.CoverageOverride.on_date <= end))}

    locks = {k: c for k, c in locks_from.cells.items() if c.locked} if locks_from else {}

    return Problem(start=start, end=end, employees=emps, lines=lines, assignments=assigns, leaves=leaves,
                   holidays=holidays, overrides=overrides, prev_streak=previous_streaks(db, start),
                   locks=locks, baseline=baseline, repair_window=repair_window, weights=load_weights(db))


def previous_streaks(db: Session, start: date) -> dict[str, int]:
    prev_month = (start - timedelta(days=1)).replace(day=1)
    r = db.scalar(select(M.Roster).where(M.Roster.month == prev_month, M.Roster.status == "PUBLISHED"))
    if r is None:
        return {}
    by_emp: dict[str, list[M.RosterDay]] = {}
    for d in r.days:
        by_emp.setdefault(d.employee_id, []).append(d)
    out = {}
    for emp, days in by_emp.items():
        n = 0
        for d in sorted(days, key=lambda x: x.on_date, reverse=True):
            if d.status != "WORK":
                break
            n += 1
        out[emp] = n
    return out


def roster_plan(r: M.Roster) -> Plan:
    return Plan({(d.employee_id, d.on_date): Cell(Status(d.status), dict(d.covers or {}), d.source, d.locked)
                 for d in r.days})
