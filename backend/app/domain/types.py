"""Pure domain types shared by the validator, solver and recommender.

Nothing here touches the database. A `Problem` is a frozen snapshot of everything
needed to build or check one month's roster; a `Plan` is a roster. Both serialise
to plain JSON so a solver worker can receive a problem and return a plan without
database access.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from enum import Enum
from functools import cached_property
from typing import Any


class Status(str, Enum):
    WORK = "WORK"
    WEEK_OFF = "WEEK_OFF"
    HOLIDAY = "HOLIDAY"
    LEAVE = "LEAVE"
    COMP_OFF = "COMP_OFF"


OFF_STATUSES = {Status.WEEK_OFF, Status.HOLIDAY, Status.LEAVE, Status.COMP_OFF}

# weekday bit 0 = Monday ... bit 6 = Sunday
ALL_WEEK = 0b1111111
MON_SAT = 0b0111111

CALENDAR_PRESETS: dict[str, tuple[int, bool]] = {
    # kind: (weekday_mask, works_public_holidays)
    "ALL_DAYS": (ALL_WEEK, True),      # 365-day operations
    "NO_PH": (ALL_WEEK, False),        # every day except public holidays
    "NO_SUN_PH": (MON_SAT, False),     # Sundays and public holidays off
}

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Employee:
    id: str
    code: str
    name: str
    pod_id: str
    capacity: int = 100
    weekly_offs: int = 1
    max_consecutive: int = 6
    holiday_calendar_id: str | None = None
    preferred_off_weekdays: tuple[int, ...] = ()
    is_lead: bool = False


@dataclass(frozen=True)
class ServiceLine:
    """A brand x process pair: the unit of coverage."""
    id: str
    brand_id: str
    brand_name: str
    process_code: str
    pod_id: str
    weekday_mask: int
    works_ph: bool
    min_heads: int
    weekday_min: dict[int, int] = field(default_factory=dict)
    shift_start: int = 9 * 60   # minutes from midnight
    shift_end: int = 18 * 60
    calendar_kind: str = "CUSTOM"

    @property
    def label(self) -> str:
        return f"{self.brand_name} · {self.process_code}"

    def __hash__(self) -> int:  # dict field makes the default hash fail
        return hash(self.id)


@dataclass(frozen=True)
class Assignment:
    employee_id: str
    line_id: str
    role: str = "PRIMARY"  # PRIMARY | BACKUP
    load_pct: int = 100


@dataclass
class Weights:
    gap: int = 10_000
    change: int = 500
    cover_change: int = 40
    backup: int = 80
    fairness: int = 40
    preference: int = 20
    ph_work: int = 15
    extra_off: int = 300
    adjacent_off: int = 5
    primary_reward: int = 1
    max_shift_span_minutes: int = 600
    time_limit_s: float = 30.0
    workers: int = 8
    seed: int = 7


@dataclass
class Cell:
    status: Status
    covers: dict[str, bool] = field(default_factory=dict)  # line_id -> as_backup
    source: str = "SOLVER"  # SOLVER | MANUAL
    locked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "covers": dict(self.covers),
                "source": self.source, "locked": self.locked}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Cell":
        return Cell(Status(d["status"]), dict(d.get("covers", {})),
                    d.get("source", "SOLVER"), bool(d.get("locked", False)))


@dataclass
class Plan:
    cells: dict[tuple[str, date], Cell] = field(default_factory=dict)

    def get(self, emp_id: str, d: date) -> Cell | None:
        return self.cells.get((emp_id, d))

    def copy(self) -> "Plan":
        return Plan({k: Cell(v.status, dict(v.covers), v.source, v.locked)
                     for k, v in self.cells.items()})

    def to_dict(self) -> dict[str, Any]:
        return {"cells": [{"employee_id": e, "date": d.isoformat(), **c.to_dict()}
                          for (e, d), c in self.cells.items()]}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Plan":
        return Plan({(c["employee_id"], date.fromisoformat(c["date"])): Cell.from_dict(c)
                     for c in d["cells"]})


@dataclass
class Problem:
    start: date
    end: date
    employees: list[Employee]
    lines: list[ServiceLine]
    assignments: list[Assignment]
    leaves: dict[tuple[str, date], Status] = field(default_factory=dict)
    holidays: dict[str, set[date]] = field(default_factory=dict)  # calendar id -> dates
    org_holiday_calendar: str = "IN-NATIONAL"
    overrides: dict[tuple[str, date], int] = field(default_factory=dict)
    prev_streak: dict[str, int] = field(default_factory=dict)
    locks: dict[tuple[str, date], Cell] = field(default_factory=dict)
    baseline: Plan | None = None
    repair_window: tuple[date, date] | None = None
    weights: Weights = field(default_factory=Weights)

    # ---- derived lookups -------------------------------------------------
    @cached_property
    def days(self) -> list[date]:
        n = (self.end - self.start).days + 1
        return [self.start + timedelta(days=i) for i in range(n)]

    @cached_property
    def emp_by_id(self) -> dict[str, Employee]:
        return {e.id: e for e in self.employees}

    @cached_property
    def line_by_id(self) -> dict[str, ServiceLine]:
        return {l.id: l for l in self.lines}

    @cached_property
    def assign_by_emp(self) -> dict[str, list[Assignment]]:
        out: dict[str, list[Assignment]] = {e.id: [] for e in self.employees}
        for a in self.assignments:
            if a.employee_id in out and a.line_id in self.line_by_id:
                out[a.employee_id].append(a)
        return out

    @cached_property
    def assign_by_line(self) -> dict[str, list[Assignment]]:
        out: dict[str, list[Assignment]] = {l.id: [] for l in self.lines}
        for a in self.assignments:
            if a.line_id in out and a.employee_id in self.emp_by_id:
                out[a.line_id].append(a)
        return out

    def assignment(self, emp_id: str, line_id: str) -> Assignment | None:
        for a in self.assign_by_emp.get(emp_id, []):
            if a.line_id == line_id:
                return a
        return None

    # ---- serialisation (problem -> solver worker) -------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "employees": [asdict(e) for e in self.employees],
            "lines": [{**asdict(l), "weekday_min": {str(k): v for k, v in l.weekday_min.items()}}
                      for l in self.lines],
            "assignments": [asdict(a) for a in self.assignments],
            "leaves": [[e, d.isoformat(), s.value] for (e, d), s in self.leaves.items()],
            "holidays": {k: sorted(x.isoformat() for x in v) for k, v in self.holidays.items()},
            "org_holiday_calendar": self.org_holiday_calendar,
            "overrides": [[l, d.isoformat(), n] for (l, d), n in self.overrides.items()],
            "prev_streak": self.prev_streak,
            "locks": [[e, d.isoformat(), c.to_dict()] for (e, d), c in self.locks.items()],
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "repair_window": [self.repair_window[0].isoformat(), self.repair_window[1].isoformat()]
            if self.repair_window else None,
            "weights": asdict(self.weights),
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Problem":
        return Problem(
            start=date.fromisoformat(d["start"]), end=date.fromisoformat(d["end"]),
            employees=[Employee(**{**e, "preferred_off_weekdays": tuple(e["preferred_off_weekdays"])})
                       for e in d["employees"]],
            lines=[ServiceLine(**{**l, "weekday_min": {int(k): v for k, v in l["weekday_min"].items()}})
                   for l in d["lines"]],
            assignments=[Assignment(**a) for a in d["assignments"]],
            leaves={(e, date.fromisoformat(x)): Status(s) for e, x, s in d["leaves"]},
            holidays={k: {date.fromisoformat(x) for x in v} for k, v in d["holidays"].items()},
            org_holiday_calendar=d["org_holiday_calendar"],
            overrides={(l, date.fromisoformat(x)): n for l, x, n in d["overrides"]},
            prev_streak=d.get("prev_streak", {}),
            locks={(e, date.fromisoformat(x)): Cell.from_dict(c) for e, x, c in d.get("locks", [])},
            baseline=Plan.from_dict(d["baseline"]) if d.get("baseline") else None,
            repair_window=(date.fromisoformat(d["repair_window"][0]),
                           date.fromisoformat(d["repair_window"][1])) if d.get("repair_window") else None,
            weights=Weights(**d.get("weights", {})),
        )
