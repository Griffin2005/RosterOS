"""Backup recommendations for coverage gaps.

Given open lines on one day (often all lines of a single-resource brand), rank
every trained person by how they could cover, what it costs, and which rule
would break. Each recommendation carries concrete cell changes that the API can
apply as a validated manual edit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .calendar import fixed_status, required_heads, shifts_compatible, weeks, employee_holiday
from .types import Cell, Plan, Problem, Status, WEEKDAY_NAMES
from .validator import effective_working, heads_on

ORDER = {"RECOMMENDED": 0, "PARTIAL": 1, "REJECTED": 2}


@dataclass
class Suggestion:
    employee_id: str
    name: str
    verdict: str
    covers: list[str]
    cost: int
    reasons: list[str]
    actions: list[dict[str, Any]] = field(default_factory=list)
    same_pod: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _run_length(p: Problem, plan: Plan, emp_id: str, d: date, extra_off: date | None = None) -> int:
    """Consecutive working days that would include d if d became a working day."""
    def works(x: date) -> bool:
        if x == d:
            return True
        if x == extra_off:
            return False
        return effective_working(p, plan, emp_id, x)

    idx = p.days.index(d)
    n = 1
    i = idx - 1
    while i >= 0 and works(p.days[i]):
        n += 1
        i -= 1
    if i < 0:
        n += p.prev_streak.get(emp_id, 0)
    i = idx + 1
    while i < len(p.days) and works(p.days[i]):
        n += 1
        i += 1
    return n


def suggest(p: Problem, plan: Plan, d: date, line_ids: list[str]) -> list[Suggestion]:
    w = p.weights
    open_lines = [l for l in line_ids if len(heads_on(p, plan, l, d)) < required_heads(p, p.line_by_id[l], d)]
    if not open_lines:
        return []
    pods = {p.line_by_id[l].pod_id for l in open_lines}
    candidates: dict[str, list[str]] = {}
    for l in open_lines:
        for a in p.assign_by_line.get(l, []):
            candidates.setdefault(a.employee_id, []).append(l)

    out: list[Suggestion] = []
    for emp_id, trained in candidates.items():
        e = p.emp_by_id[emp_id]
        cell = plan.get(emp_id, d) or Cell(Status.WEEK_OFF)
        reasons: list[str] = []
        fs = fixed_status(p, e, d)
        if fs in (Status.LEAVE, Status.COMP_OFF):
            out.append(Suggestion(emp_id, e.name, "REJECTED", [], 0,
                                  [f"On approved {fs.value.lower().replace('_', '-')}"]))
            continue

        working = effective_working(p, plan, emp_id, d)
        used = sum(p.assignment(emp_id, l).load_pct for l in cell.covers if p.assignment(emp_id, l)) if working else 0
        current = list(cell.covers) if working else []
        cost = 0
        actions: list[dict[str, Any]] = []

        if not working:
            run = _run_length(p, plan, emp_id, d)
            if run > e.max_consecutive:
                out.append(Suggestion(emp_id, e.name, "REJECTED", [], 0,
                                      [f"{d:%d %b} would be day {run} in a row (limit {e.max_consecutive})"],
                                      same_pod=e.pod_id in pods))
                continue
            if cell.status == Status.WEEK_OFF:
                swap = _find_swap_day(p, plan, emp_id, d)
                if swap is None:
                    wk = next(x for x in weeks(p) if d in x)
                    offs = sum(1 for x in wk if (c := plan.get(emp_id, x)) and c.status == Status.WEEK_OFF)
                    if offs <= 1:
                        out.append(Suggestion(emp_id, e.name, "REJECTED", [], 0,
                                              ["No other day that week can take their weekly off without opening a new gap"],
                                              same_pod=e.pod_id in pods))
                        continue
                else:
                    actions.append({"employee_id": emp_id, "date": swap.isoformat(), "status": "WEEK_OFF", "covers": {}})
                    reasons.append(f"Weekly off moves to {swap:%a %d %b}")
                    cost += w.change
            elif cell.status == Status.HOLIDAY:
                reasons.append("Works the public holiday and earns a comp-off")
                cost += w.ph_work
            if d.weekday() in e.preferred_off_weekdays:
                reasons.append(f"Overrides preferred {WEEKDAY_NAMES[d.weekday()]} off")
                cost += w.preference
            cost += w.change

        # greedily add trained lines that fit capacity and shift windows
        added: list[str] = []
        blocked: list[str] = []
        for l in trained:
            a = p.assignment(emp_id, l)
            line = p.line_by_id[l]
            if used + a.load_pct > e.capacity:
                blocked.append(f"{line.label} needs {a.load_pct}%, only {e.capacity - used}% free")
                continue
            clash = next((x for x in current + added
                          if not shifts_compatible(p.line_by_id[x], line, w.max_shift_span_minutes)), None)
            if clash:
                blocked.append(f"{line.label} clashes with {p.line_by_id[clash].label} shift")
                continue
            used += a.load_pct
            added.append(l)
            if a.role == "BACKUP":
                cost += w.backup

        if not added:
            out.append(Suggestion(emp_id, e.name, "REJECTED", [], 0,
                                  (reasons + blocked) or ["No capacity"], same_pod=e.pod_id in pods))
            continue
        covers = {**({x: cell.covers[x] for x in current}),
                  **{x: p.assignment(emp_id, x).role == "BACKUP" for x in added}}
        actions.insert(0, {"employee_id": emp_id, "date": d.isoformat(), "status": "WORK", "covers": covers})
        missing = [l for l in open_lines if l not in added]
        verdict = "RECOMMENDED" if not missing else "PARTIAL"
        if working:
            reasons.insert(0, f"Already working; adds {', '.join(p.line_by_id[x].process_code for x in added)} "
                              f"(load {used}%)")
        if missing:
            reasons.append("Cannot take " + ", ".join(p.line_by_id[x].label for x in missing)
                           + (": " + "; ".join(blocked) if blocked else ""))
        out.append(Suggestion(emp_id, e.name, verdict, [p.line_by_id[x].label for x in added], cost,
                              reasons, actions, same_pod=e.pod_id in pods))

    out.sort(key=lambda s: (ORDER[s.verdict], -len(s.covers), s.cost, not s.same_pod))
    return out


def _find_swap_day(p: Problem, plan: Plan, emp_id: str, d: date) -> date | None:
    """A working day in the same week that can become the weekly off without
    leaving any of the lines covered that day short."""
    wk = next(x for x in weeks(p) if d in x)
    e = p.emp_by_id[emp_id]
    best: tuple[int, date] | None = None
    for x in wk:
        if x == d:
            continue
        c = plan.get(emp_id, x)
        if c is None or c.status != Status.WORK or c.locked or employee_holiday(p, e, x):
            continue
        ok = all(len(heads_on(p, plan, l, x)) - 1 >= required_heads(p, p.line_by_id[l], x) for l in c.covers)
        if not ok:
            continue
        score = (0 if x.weekday() in e.preferred_off_weekdays else 1) * 10 + abs((x - d).days)
        if best is None or score < best[0]:
            best = (score, x)
    return best[1] if best else None
