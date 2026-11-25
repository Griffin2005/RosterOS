"""Operating calendars, demand expansion and per-employee availability.

This is where a brand's operating calendar and an individual's working schedule
are kept apart: `line_operates` / `required_heads` describe the brand side,
`fixed_status` / `employee_holiday` describe the person side.
"""
from __future__ import annotations

from datetime import date

from .types import Problem, ServiceLine, Status, Employee


def is_org_holiday(p: Problem, d: date) -> bool:
    return d in p.holidays.get(p.org_holiday_calendar, set())


def line_operates(p: Problem, line: ServiceLine, d: date) -> bool:
    ov = p.overrides.get((line.id, d))
    if ov is not None:
        return ov > 0
    if not (line.weekday_mask >> d.weekday()) & 1:
        return False
    if is_org_holiday(p, d) and not line.works_ph:
        return False
    return True


def required_heads(p: Problem, line: ServiceLine, d: date) -> int:
    ov = p.overrides.get((line.id, d))
    if ov is not None:
        return max(ov, 0)
    if not line_operates(p, line, d):
        return 0
    return line.weekday_min.get(d.weekday(), line.min_heads)


def employee_holiday(p: Problem, e: Employee, d: date) -> bool:
    cal = e.holiday_calendar_id or p.org_holiday_calendar
    return d in p.holidays.get(cal, set()) or d in p.holidays.get(p.org_holiday_calendar, set())


def eligible_lines_on(p: Problem, emp_id: str, d: date) -> list[str]:
    """Lines the employee is trained on (primary or backup) that operate on d."""
    return [a.line_id for a in p.assign_by_emp.get(emp_id, [])
            if line_operates(p, p.line_by_id[a.line_id], d)]


def fixed_status(p: Problem, e: Employee, d: date) -> Status | None:
    """A status the roster cannot change: approved leave, comp-off, or a public
    holiday on which none of the employee's lines operate."""
    lv = p.leaves.get((e.id, d))
    if lv is not None:
        return lv
    if employee_holiday(p, e, d) and not eligible_lines_on(p, e.id, d):
        return Status.HOLIDAY
    return None


def weeks(p: Problem) -> list[list[date]]:
    """Days of the problem grouped into Monday-Sunday weeks (partial at the edges)."""
    out: list[list[date]] = []
    for d in p.days:
        if not out or d.weekday() == 0:
            out.append([])
        out[-1].append(d)
    return out


def required_offs(e: Employee, week_len: int) -> int:
    """Weekly offs owed inside the month for one Mon-Sun week.

    A week split across two months may take its off on the other side of the
    boundary (e.g. Mon 28 - Thu 31 Dec, off on Sun 3 Jan), so only the offs that
    cannot fit outside the month are owed here. The 6-day streak limit (H7),
    which carries over between months, still bounds the split weeks."""
    if week_len >= 7:
        return e.weekly_offs
    return max(0, e.weekly_offs - (7 - week_len))


def shifts_compatible(a: ServiceLine, b: ServiceLine, max_span: int) -> bool:
    """Two lines can be carried by one person on one day if their shift windows
    fit inside a single working span. Overlapping windows are fine: one person
    handles CS, ACC and NDR concurrently for a single-resource brand."""
    span = max(a.shift_end, b.shift_end) - min(a.shift_start, b.shift_start)
    return span <= max_span


def fmt_minutes(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_shift(text: str) -> tuple[int, int]:
    a, b = text.replace("–", "-").split("-")
    h1, m1 = a.strip().split(":")
    h2, m2 = b.strip().split(":")
    return int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
