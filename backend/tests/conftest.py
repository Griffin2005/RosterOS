import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import sample_data as S  # noqa: E402
from app.domain.rules_parser import parse_overrides, parse_service_lines  # noqa: E402
from app.domain.types import Assignment, Employee, Problem, ServiceLine, Status, Weights  # noqa: E402


def build_sample_problem(year: int = 2026, month: int = 12, **kw) -> Problem:
    """The sample dataset as a Problem, without any database."""
    start = date(year, month, 1)
    end = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    rules, errs = parse_service_lines(S.RULE_SHEET_HEADER, S.RULE_SHEET_ROWS)
    assert not errs
    brand_pod = {b: pod for b, pod, _ in S.BRANDS}
    lines = [ServiceLine(id=f"{r.brand}|{r.process}", brand_id=r.brand, brand_name=r.brand,
                         process_code=r.process, pod_id=brand_pod[r.brand], weekday_mask=r.weekday_mask,
                         works_ph=r.works_ph, min_heads=r.min_heads, weekday_min=r.weekday_min,
                         shift_start=r.shift_start, shift_end=r.shift_end, calendar_kind=r.calendar_kind)
             for r in rules]
    leads = {lead for _, _, lead in S.PODS}
    emps = [Employee(id=c, code=c, name=n, pod_id=pod, holiday_calendar_id=cal,
                     preferred_off_weekdays=tuple(pref), is_lead=c in leads)
            for c, n, pod, cal, pref in S.EMPLOYEES]
    assigns = [Assignment(e, f"{b}|{pr}", role, load) for e, b, pr, role, load in S.ASSIGNMENTS]
    lead_of = {pod: lead for pod, _, lead in S.PODS}
    for l in lines:
        primary_loads = [a.load_pct for a in assigns if a.line_id == l.id and a.role == "PRIMARY"]
        assigns.append(Assignment(lead_of[l.pod_id], l.id, "BACKUP", max(primary_loads or [50])))
    ovs, _ = parse_overrides(S.OVERRIDE_SHEET_HEADER, S.OVERRIDE_SHEET_ROWS)
    overrides = {(f"{o.brand}|{o.process}", o.on_date): o.min_heads for o in ovs}
    leaves = {}
    for code, a, b, typ, status in S.LEAVES:
        if status != "APPROVED":
            continue
        d = date.fromisoformat(a)
        while d <= date.fromisoformat(b):
            leaves[(code, d)] = Status.COMP_OFF if typ == "COMP_OFF" else Status.LEAVE
            d += timedelta(days=1)
    holidays = {cal: {date.fromisoformat(d) for d, _ in items} for cal, items in S.HOLIDAYS.items()}
    w = kw.pop("weights", Weights(time_limit_s=20))
    return Problem(start=start, end=end, employees=emps, lines=lines, assignments=assigns,
                   leaves=leaves, holidays=holidays, overrides=overrides, weights=w, **kw)


@pytest.fixture(scope="session")
def december():
    return build_sample_problem()
