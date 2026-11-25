"""Fast structural checks that run before the solver.

If a slot needs more people than are even trained and available that day, no
solver can fix it. Reporting it up front gives the manager the real cause
("only Priya is trained on ACC and she is on leave") instead of a bare gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .calendar import fixed_status, required_heads
from .types import Plan, Problem


@dataclass
class ImpossibleSlot:
    line_id: str
    label: str
    date: date
    required: int
    available: int
    trained: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "date": self.date.isoformat()}


def precheck(p: Problem) -> list[ImpossibleSlot]:
    out = []
    for line in p.lines:
        trained = p.assign_by_line.get(line.id, [])
        for d in p.days:
            req = required_heads(p, line, d)
            if req <= 0:
                continue
            info = []
            avail = 0
            for a in trained:
                fs = fixed_status(p, p.emp_by_id[a.employee_id], d)
                info.append({"employee_id": a.employee_id, "name": p.emp_by_id[a.employee_id].name,
                             "role": a.role, "status": fs.value if fs else "AVAILABLE"})
                if fs is None:
                    avail += 1
            if avail < req:
                out.append(ImpossibleSlot(line.id, line.label, d, req, avail, info))
    return out


def diff_plans(old: Plan, new: Plan) -> list[dict[str, Any]]:
    changes = []
    for key, nc in new.cells.items():
        oc = old.cells.get(key)
        if oc is None or oc.status != nc.status or set(oc.covers) != set(nc.covers):
            changes.append({"employee_id": key[0], "date": key[1].isoformat(),
                            "before": oc.to_dict() if oc else None, "after": nc.to_dict()})
    return sorted(changes, key=lambda c: (c["date"], c["employee_id"]))
