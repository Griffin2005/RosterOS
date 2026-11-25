"""Independent, deterministic rule engine.

It never trusts the solver: every roster (solver output, manual edit, repaired
plan) is re-checked here, and the result is the conflict list shown to the
operations manager. Each conflict carries a structured explanation that both the
UI and the AI assistant read.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

from .calendar import (employee_holiday, fixed_status, line_operates, required_heads,
                       required_offs, shifts_compatible, weeks)
from .types import Plan, Problem, Status, WEEKDAY_NAMES

HARD, SOFT, INFO = "HARD", "SOFT", "INFO"

CODES = {
    "C01": ("NO_COVERAGE", HARD),
    "C02": ("UNDERSTAFFED", HARD),
    "C03": ("OVER_ALLOCATED", HARD),
    "C04": ("SHIFT_CLASH", HARD),
    "C05": ("LEAVE_CONFLICT", HARD),
    "C06": ("NO_WEEKLY_OFF", HARD),
    "C07": ("STREAK", HARD),
    "C08": ("CASCADE_GAP", HARD),
    "C09": ("PREFERENCE", SOFT),
    "C10": ("BACKUP_USED", INFO),
    "C13": ("NOT_ASSIGNED", HARD),
    "C14": ("NO_BACKUP", SOFT),
}


@dataclass
class Conflict:
    code: str
    severity: str
    title: str
    detail: str
    date: date | None = None
    line_id: str | None = None
    employee_id: str | None = None
    brand_id: str | None = None
    explanation: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return CODES[self.code][0]

    @property
    def key(self) -> str:
        return f"{self.code}:{self.date or ''}:{self.line_id or ''}:{self.employee_id or ''}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat() if self.date else None
        d["name"] = self.name
        d["key"] = self.key
        return d


def _mk(code: str, title: str, detail: str, **kw: Any) -> Conflict:
    return Conflict(code=code, severity=CODES[code][1], title=title, detail=detail, **kw)


def effective_working(p: Problem, plan: Plan, emp_id: str, d: date) -> bool:
    """Scheduled to work AND actually available (leave approved after publishing
    makes a WORK cell useless for coverage)."""
    c = plan.get(emp_id, d)
    if c is None or c.status != Status.WORK:
        return False
    fs = fixed_status(p, p.emp_by_id[emp_id], d)
    return fs not in (Status.LEAVE, Status.COMP_OFF, Status.HOLIDAY)


def heads_on(p: Problem, plan: Plan, line_id: str, d: date) -> list[str]:
    return [a.employee_id for a in p.assign_by_line.get(line_id, [])
            if effective_working(p, plan, a.employee_id, d)
            and line_id in plan.cells[(a.employee_id, d)].covers]


def why_unavailable(p: Problem, plan: Plan, emp_id: str, line_id: str, d: date) -> str:
    e = p.emp_by_id[emp_id]
    fs = fixed_status(p, e, d)
    if fs == Status.LEAVE:
        return "on approved leave"
    if fs == Status.COMP_OFF:
        return "on approved comp-off"
    if fs == Status.HOLIDAY:
        return "public holiday"
    c = plan.get(emp_id, d)
    if c is None:
        return "not in roster"
    if c.status == Status.WEEK_OFF:
        return "weekly off"
    if c.status == Status.HOLIDAY:
        return "public holiday off"
    if c.status != Status.WORK:
        return c.status.value.lower()
    used = sum((p.assignment(emp_id, l).load_pct if p.assignment(emp_id, l) else 0) for l in c.covers)
    others = [p.line_by_id[l].label for l in c.covers if l in p.line_by_id]
    return f"working, {used}% load on {', '.join(others) or 'nothing'}"


def validate(p: Problem, plan: Plan) -> list[Conflict]:
    out: list[Conflict] = []
    w = p.weights

    # ---- per-cell checks -------------------------------------------------
    for e in p.employees:
        for d in p.days:
            c = plan.get(e.id, d)
            if c is None:
                continue
            fs = fixed_status(p, e, d)
            if c.status == Status.WORK and fs in (Status.LEAVE, Status.COMP_OFF):
                out.append(_mk("C05", f"{e.name} scheduled on {fs.value.lower().replace('_', '-')}",
                               f"{e.name} is rostered to work on {d:%a %d %b} but has an approved "
                               f"{fs.value.lower().replace('_', '-')}.",
                               date=d, employee_id=e.id,
                               explanation={"approved": fs.value}))
            if c.status != Status.WORK:
                continue
            load = 0
            for lid, as_backup in c.covers.items():
                a = p.assignment(e.id, lid)
                line = p.line_by_id.get(lid)
                if a is None or line is None:
                    out.append(_mk("C13", f"{e.name} covering an untrained line",
                                   f"{e.name} is not assigned to {line.label if line else lid}.",
                                   date=d, employee_id=e.id, line_id=lid))
                    continue
                load += a.load_pct
                if a.role == "BACKUP":
                    out.append(_mk("C10", f"Backup covers {line.label}",
                                   f"{e.name} covers {line.label} as a backup.",
                                   date=d, employee_id=e.id, line_id=lid, brand_id=line.brand_id))
            if load > e.capacity:
                out.append(_mk("C03", f"{e.name} over-allocated ({load}%)",
                               f"Covered lines add up to {load}% load against a capacity of {e.capacity}%.",
                               date=d, employee_id=e.id,
                               explanation={"load": load, "capacity": e.capacity,
                                            "lines": [p.line_by_id[l].label for l in c.covers if l in p.line_by_id]}))
            ids = [l for l in c.covers if l in p.line_by_id]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = p.line_by_id[ids[i]], p.line_by_id[ids[j]]
                    if not shifts_compatible(a, b, w.max_shift_span_minutes):
                        out.append(_mk("C04", f"{e.name}: shift clash",
                                       f"{a.label} and {b.label} can't be combined in one working span.",
                                       date=d, employee_id=e.id,
                                       explanation={"lines": [a.label, b.label]}))
            if d.weekday() in e.preferred_off_weekdays and fs is None and not employee_holiday(p, e, d):
                out.append(_mk("C09", f"{e.name} works a preferred off-day",
                               f"{e.name} prefers {WEEKDAY_NAMES[d.weekday()]} off; overridden for coverage.",
                               date=d, employee_id=e.id))

    # ---- weekly offs and streaks ----------------------------------------
    for e in p.employees:
        for wk in weeks(p):
            countable = [d for d in wk if fixed_status(p, e, d) is None and not employee_holiday(p, e, d)]
            need = min(required_offs(e, len(wk)), len(countable))
            got = sum(1 for d in countable
                      if (c := plan.get(e.id, d)) is not None and c.status == Status.WEEK_OFF)
            if got < need:
                out.append(_mk("C06", f"{e.name}: missing weekly off",
                               f"Week of {wk[0]:%d %b}: {got} of {need} required weekly off(s).",
                               date=wk[0], employee_id=e.id,
                               explanation={"week_start": wk[0].isoformat(), "required": need, "scheduled": got}))
        streak = p.prev_streak.get(e.id, 0)
        reported = False
        for d in p.days:
            if effective_working(p, plan, e.id, d):
                streak += 1
                if streak > e.max_consecutive and not reported:
                    out.append(_mk("C07", f"{e.name}: {streak} days in a row",
                                   f"Exceeds the limit of {e.max_consecutive} consecutive working days on {d:%a %d %b}.",
                                   date=d, employee_id=e.id,
                                   explanation={"streak": streak, "limit": e.max_consecutive}))
                    reported = True
            else:
                streak = 0
                reported = False

    # ---- coverage --------------------------------------------------------
    gap_causes: dict[tuple[date, str], set[str]] = defaultdict(set)  # (day, emp) -> brands
    for line in p.lines:
        assignees = p.assign_by_line.get(line.id, [])
        for d in p.days:
            req = required_heads(p, line, d)
            if req <= 0:
                continue
            heads = heads_on(p, plan, line.id, d)
            if len(heads) >= req:
                continue
            people = [{"employee_id": a.employee_id, "name": p.emp_by_id[a.employee_id].name,
                       "role": a.role, "reason": why_unavailable(p, plan, a.employee_id, line.id, d)}
                      for a in assignees]
            for a in assignees:
                if a.role == "PRIMARY" and not effective_working(p, plan, a.employee_id, d):
                    gap_causes[(d, a.employee_id)].add(line.brand_id)
            code = "C01" if not heads else "C02"
            title = (f"{line.label} uncovered" if code == "C01"
                     else f"{line.label} short {req - len(heads)}")
            detail = (f"Needs {req} on {d:%a %d %b}; {len(heads)} scheduled." if assignees
                      else f"Needs {req} on {d:%a %d %b} but nobody is assigned to this line.")
            out.append(_mk(code, title, detail, date=d, line_id=line.id, brand_id=line.brand_id,
                           explanation={"required": req, "scheduled": len(heads), "assignees": people}))

    for (d, emp_id), brands in gap_causes.items():
        if len(brands) >= 2:
            e = p.emp_by_id[emp_id]
            names = sorted({l.brand_name for l in p.lines if l.brand_id in brands})
            out.append(_mk("C08", f"{e.name} away opens gaps in {len(brands)} brands",
                           f"{', '.join(names)} are all short on {d:%a %d %b}.",
                           date=d, employee_id=emp_id, explanation={"brands": names}))
    return out


def risk_checks(p: Problem) -> list[Conflict]:
    """Structural risks independent of any roster: a line that must be staffed
    7 days a week but has only one trained person."""
    out = []
    for line in p.lines:
        if not p.days:
            break
        open_days = sum(1 for d in p.days if required_heads(p, line, d) > 0)
        trained = p.assign_by_line.get(line.id, [])
        if open_days >= len(p.days) * 0.95 and len(trained) <= 1:
            out.append(_mk("C14", f"{line.label} has no backup",
                           "Runs every day with a single trained person; every weekly off or leave is a gap.",
                           line_id=line.id, brand_id=line.brand_id))
    return out


def summarize(conflicts: list[Conflict]) -> dict[str, int]:
    s = {HARD: 0, SOFT: 0, INFO: 0}
    for c in conflicts:
        s[c.severity] += 1
    return s
