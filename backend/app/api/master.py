"""Master data: pods, employees, brands, processes, service lines, assignments,
leaves, holidays, solver settings. Everything an operations manager changes
without touching code."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as M
from ..auth import MANAGE, WRITE_ROSTER, ADMIN, User, current_user, require
from ..db import get_db
from ..domain.calendar import fmt_minutes, parse_shift
from ..domain.types import CALENDAR_PRESETS
from ..services import rosters as R
from ..services.audit import audit, notify

router = APIRouter(prefix="/api")


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, f"That conflicts with an existing record ({e.orig}).")


def _get(db: Session, model, id_: str):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


# ------------------------------------------------------------------ pods
class PodIn(BaseModel):
    name: str
    lead_id: str | None = None


@router.get("/pods")
def list_pods(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": p.id, "name": p.name, "lead_id": p.lead_id} for p in db.scalars(select(M.Pod).order_by(M.Pod.name))]


@router.post("/pods")
def create_pod(body: PodIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    p = M.Pod(**body.model_dump())
    db.add(p)
    audit(db, user.username, "CREATED", "pod", None, None, body.model_dump())
    _commit(db)
    return {"id": p.id}


@router.put("/pods/{pid}")
def update_pod(pid: str, body: PodIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    p = _get(db, M.Pod, pid)
    before = {"name": p.name, "lead_id": p.lead_id}
    p.name, p.lead_id = body.name, body.lead_id
    audit(db, user.username, "UPDATED", "pod", pid, before, body.model_dump())
    _commit(db)
    return {"ok": True}


@router.delete("/pods/{pid}")
def delete_pod(pid: str, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    db.delete(_get(db, M.Pod, pid))
    audit(db, user.username, "DELETED", "pod", pid)
    _commit(db)
    return {"ok": True}


# ------------------------------------------------------------- employees
class EmployeeIn(BaseModel):
    code: str
    name: str
    pod_id: str | None = None
    capacity: int = Field(100, ge=10, le=200)
    weekly_offs: int = Field(1, ge=0, le=3)
    max_consecutive: int = Field(6, ge=1, le=13)
    holiday_calendar_id: str | None = None
    active: bool = True
    preferred_off: list[int] = []


def _emp_out(db: Session, e: M.Employee) -> dict:
    prefs = [int(p.value) for p in db.scalars(select(M.Preference).where(
        M.Preference.employee_id == e.id, M.Preference.kind == "OFF_DAY"))]
    return {"id": e.id, "code": e.code, "name": e.name, "pod_id": e.pod_id, "capacity": e.capacity,
            "weekly_offs": e.weekly_offs, "max_consecutive": e.max_consecutive,
            "holiday_calendar_id": e.holiday_calendar_id, "active": e.active, "preferred_off": sorted(prefs),
            "assignments": [{"id": a.id, "service_line_id": a.service_line_id, "role": a.role,
                             "load_pct": a.load_pct} for a in e.assignments]}


def _set_prefs(db: Session, emp_id: str, days: list[int]):
    db.query(M.Preference).filter(M.Preference.employee_id == emp_id, M.Preference.kind == "OFF_DAY").delete()
    for d in sorted(set(days)):
        if 0 <= d <= 6:
            db.add(M.Preference(employee_id=emp_id, kind="OFF_DAY", value=str(d)))


@router.get("/employees")
def list_employees(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_emp_out(db, e) for e in db.scalars(select(M.Employee).order_by(M.Employee.code))]


@router.post("/employees")
def create_employee(body: EmployeeIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    e = M.Employee(**body.model_dump(exclude={"preferred_off"}))
    db.add(e)
    db.flush()
    _set_prefs(db, e.id, body.preferred_off)
    audit(db, user.username, "CREATED", "employee", e.id, None, body.model_dump())
    _commit(db)
    return _emp_out(db, e)


@router.put("/employees/{eid}")
def update_employee(eid: str, body: EmployeeIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    e = _get(db, M.Employee, eid)
    before = _emp_out(db, e)
    for k, v in body.model_dump(exclude={"preferred_off"}).items():
        setattr(e, k, v)
    _set_prefs(db, eid, body.preferred_off)
    audit(db, user.username, "UPDATED", "employee", eid, before, body.model_dump())
    _commit(db)
    return _emp_out(db, e)


@router.delete("/employees/{eid}")
def delete_employee(eid: str, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    e = _get(db, M.Employee, eid)
    e.active = False  # soft delete keeps roster history intact
    audit(db, user.username, "DEACTIVATED", "employee", eid)
    _commit(db)
    return {"ok": True}


# ------------------------------------------------------- brands, processes
class BrandIn(BaseModel):
    name: str
    pod_id: str | None = None
    tier: str = "C"
    active: bool = True


@router.get("/brands")
def list_brands(db: Session = Depends(get_db), _: User = Depends(current_user)):
    out = []
    for b in db.scalars(select(M.Brand).order_by(M.Brand.name)):
        lines = db.scalars(select(M.ServiceLine).where(M.ServiceLine.brand_id == b.id, M.ServiceLine.active.is_(True))).all()
        people = {a.employee_id for l in lines for a in db.scalars(
            select(M.Assignment).where(M.Assignment.service_line_id == l.id, M.Assignment.role == "PRIMARY"))}
        out.append({"id": b.id, "name": b.name, "pod_id": b.pod_id, "tier": b.tier, "active": b.active,
                    "lines": len(lines), "primary_people": len(people)})
    return out


@router.post("/brands")
def create_brand(body: BrandIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    b = M.Brand(**body.model_dump())
    db.add(b)
    audit(db, user.username, "CREATED", "brand", None, None, body.model_dump())
    _commit(db)
    return {"id": b.id}


@router.put("/brands/{bid}")
def update_brand(bid: str, body: BrandIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    b = _get(db, M.Brand, bid)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    audit(db, user.username, "UPDATED", "brand", bid, None, body.model_dump())
    _commit(db)
    return {"ok": True}


class ProcessIn(BaseModel):
    code: str
    name: str


@router.get("/processes")
def list_processes(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": p.id, "code": p.code, "name": p.name} for p in db.scalars(select(M.Process).order_by(M.Process.code))]


@router.post("/processes")
def create_process(body: ProcessIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    p = M.Process(code=body.code.upper(), name=body.name)
    db.add(p)
    audit(db, user.username, "CREATED", "process", None, None, body.model_dump())
    _commit(db)
    return {"id": p.id}


# --------------------------------------------------------- service lines
class LineIn(BaseModel):
    brand_id: str
    process_id: str
    calendar_kind: str = "ALL_DAYS"
    weekday_mask: int | None = None
    min_heads: int = Field(1, ge=0, le=20)
    weekday_min: dict[str, int] = {}
    shift: str = "09:00-18:00"
    active: bool = True


def _line_out(sl: M.ServiceLine) -> dict:
    return {"id": sl.id, "brand_id": sl.brand_id, "brand": sl.brand.name, "process_id": sl.process_id,
            "process": sl.process.code, "calendar_kind": sl.calendar_kind, "weekday_mask": sl.weekday_mask,
            "works_ph": sl.works_ph, "min_heads": sl.min_heads, "weekday_min": sl.weekday_min,
            "shift": f"{fmt_minutes(sl.shift_start)}-{fmt_minutes(sl.shift_end)}", "active": sl.active,
            "rule_set_version": sl.rule_set_version}


@router.get("/service-lines")
def list_lines(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.scalars(select(M.ServiceLine).join(M.Brand).order_by(M.Brand.name)).all()
    return [_line_out(sl) for sl in rows]


def _apply_line(sl: M.ServiceLine, body: LineIn):
    if body.calendar_kind in CALENDAR_PRESETS:
        mask, ph = CALENDAR_PRESETS[body.calendar_kind]
    elif body.calendar_kind == "CUSTOM" and body.weekday_mask:
        mask, ph = body.weekday_mask, False
    else:
        raise HTTPException(422, "calendar_kind must be ALL_DAYS, NO_PH, NO_SUN_PH or CUSTOM with weekday_mask")
    try:
        s, e = parse_shift(body.shift)
    except ValueError:
        raise HTTPException(422, "Shift must look like 09:30-18:30")
    sl.brand_id, sl.process_id = body.brand_id, body.process_id
    sl.calendar_kind, sl.weekday_mask, sl.works_ph = body.calendar_kind, mask, ph
    sl.min_heads, sl.weekday_min, sl.shift_start, sl.shift_end = body.min_heads, body.weekday_min, s, e
    sl.active = body.active


@router.post("/service-lines")
def create_line(body: LineIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    from ..services.sheets_sync import write_back_rules
    sl = M.ServiceLine()
    _apply_line(sl, body)
    db.add(sl)
    audit(db, user.username, "CREATED", "service_line", None, None, body.model_dump())
    _commit(db)
    write_back_rules(db, user.username)
    return {"id": sl.id}


@router.put("/service-lines/{lid}")
def update_line(lid: str, body: LineIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    from ..services.sheets_sync import write_back_rules
    sl = _get(db, M.ServiceLine, lid)
    before = _line_out(sl)
    _apply_line(sl, body)
    audit(db, user.username, "UPDATED", "service_line", lid, before, body.model_dump())
    _commit(db)
    write_back_rules(db, user.username)
    return _line_out(sl)


# ---------------------------------------------------------- assignments
class AssignmentIn(BaseModel):
    employee_id: str
    service_line_id: str
    role: str = "PRIMARY"
    load_pct: int = Field(100, ge=5, le=100)


@router.get("/assignments")
def list_assignments(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": a.id, "employee_id": a.employee_id, "service_line_id": a.service_line_id, "role": a.role,
             "load_pct": a.load_pct} for a in db.scalars(select(M.Assignment))]


@router.post("/assignments")
def create_assignment(body: AssignmentIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    if body.role not in ("PRIMARY", "BACKUP"):
        raise HTTPException(422, "role must be PRIMARY or BACKUP")
    a = M.Assignment(**body.model_dump())
    db.add(a)
    audit(db, user.username, "CREATED", "assignment", None, None, body.model_dump())
    _commit(db)
    return {"id": a.id}


@router.put("/assignments/{aid}")
def update_assignment(aid: str, body: AssignmentIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    a = _get(db, M.Assignment, aid)
    before = {"role": a.role, "load_pct": a.load_pct}
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    audit(db, user.username, "UPDATED", "assignment", aid, before, body.model_dump())
    _commit(db)
    return {"ok": True}


@router.delete("/assignments/{aid}")
def delete_assignment(aid: str, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    a = _get(db, M.Assignment, aid)
    audit(db, user.username, "DELETED", "assignment", aid, {"employee_id": a.employee_id,
                                                              "service_line_id": a.service_line_id}, None)
    db.delete(a)
    _commit(db)
    return {"ok": True}


# ---------------------------------------------------------------- leaves
class LeaveIn(BaseModel):
    employee_id: str
    start_date: date
    end_date: date
    type: str = "PL"
    note: str = ""


def _leave_out(lv: M.Leave, names: dict[str, str]) -> dict:
    return {"id": lv.id, "employee_id": lv.employee_id, "employee": names.get(lv.employee_id),
            "start_date": lv.start_date.isoformat(), "end_date": lv.end_date.isoformat(), "type": lv.type,
            "status": lv.status, "note": lv.note}


@router.get("/leaves")
def list_leaves(db: Session = Depends(get_db), user: User = Depends(current_user)):
    names = {e.id: e.name for e in db.scalars(select(M.Employee))}
    q = select(M.Leave).order_by(M.Leave.start_date)
    if user.scope_level == "SELF":
        q = q.where(M.Leave.employee_id == user.employee_id)
    return [_leave_out(lv, names) for lv in db.scalars(q)]


@router.post("/leaves")
def request_leave(body: LeaveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role == "EMPLOYEE" and body.employee_id != user.employee_id:
        raise HTTPException(403, "You can only request leave for yourself.")
    if user.role in ("AUDITOR", "BRAND_OWNER"):
        raise HTTPException(403, "Your role can't request leave.")
    if body.end_date < body.start_date:
        raise HTTPException(422, "End date is before start date.")
    if body.type not in ("PL", "SL", "COMP_OFF"):
        raise HTTPException(422, "Leave type must be PL, SL or COMP_OFF.")
    lv = M.Leave(**body.model_dump(), status="PENDING")
    db.add(lv)
    audit(db, user.username, "LEAVE_REQUESTED", "leave", None, None, body.model_dump(mode="json"))
    _commit(db)
    return {"id": lv.id, "status": lv.status}


def leave_impact(db: Session, lv: M.Leave) -> dict:
    """Validate the current roster(s) for the leave's month(s) and report the hard
    conflicts that touch the leave dates: the 'what does this change break' view."""
    out = []
    month = lv.start_date.replace(day=1)
    seen = set()
    while month <= lv.end_date:
        r = R.latest(db, month)
        if r is not None and r.id not in seen:
            seen.add(r.id)
            ev = R.evaluate(db, r)
            for c in ev["conflicts"]:
                if c["severity"] != "HARD" or not c["date"]:
                    continue
                d = date.fromisoformat(c["date"])
                if lv.start_date <= d <= lv.end_date:
                    out.append({**c, "roster_id": r.id, "roster_version": r.version})
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {"conflicts": out, "rosters": list(seen)}


def _set_leave_status(db: Session, lid: str, status: str, user: User) -> M.Leave:
    lv = _get(db, M.Leave, lid)
    if user.role == "POD_LEAD":
        emp = db.get(M.Employee, lv.employee_id)
        if emp.pod_id != user.scope_id:
            raise HTTPException(403, "You can only act on leave for your own pod.")
    before = lv.status
    lv.status = status
    audit(db, user.username, f"LEAVE_{status}", "leave", lid, {"status": before}, {"status": status})
    notify(db, f"Leave {lv.start_date:%d %b}–{lv.end_date:%d %b} {status.lower()}.",
           audience=f"EMP:{lv.employee_id}", employee_id=lv.employee_id)
    _commit(db)
    return lv


@router.post("/leaves/{lid}/approve")
def approve_leave(lid: str, db: Session = Depends(get_db), user: User = Depends(require(WRITE_ROSTER))):
    lv = _set_leave_status(db, lid, "APPROVED", user)
    return {"status": lv.status, "impact": leave_impact(db, lv)}


@router.post("/leaves/{lid}/reject")
def reject_leave(lid: str, db: Session = Depends(get_db), user: User = Depends(require(WRITE_ROSTER))):
    return {"status": _set_leave_status(db, lid, "REJECTED", user).status}


@router.post("/leaves/{lid}/cancel")
def cancel_leave(lid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lv = _get(db, M.Leave, lid)
    if user.role == "EMPLOYEE" and lv.employee_id != user.employee_id:
        raise HTTPException(403, "You can only cancel your own leave.")
    lv = _set_leave_status(db, lid, "CANCELLED", user)
    return {"status": lv.status, "impact": leave_impact(db, lv)}


# --------------------------------------------------------------- holidays
class HolidayIn(BaseModel):
    calendar_id: str = "IN-NATIONAL"
    on_date: date
    name: str


@router.get("/holidays")
def list_holidays(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": h.id, "calendar_id": h.calendar_id, "date": h.on_date.isoformat(), "name": h.name}
            for h in db.scalars(select(M.Holiday).order_by(M.Holiday.on_date))]


@router.post("/holidays")
def add_holiday(body: HolidayIn, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    h = M.Holiday(**body.model_dump())
    db.add(h)
    audit(db, user.username, "CREATED", "holiday", None, None, body.model_dump(mode="json"))
    _commit(db)
    return {"id": h.id}


@router.delete("/holidays/{hid}")
def delete_holiday(hid: str, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    db.delete(_get(db, M.Holiday, hid))
    audit(db, user.username, "DELETED", "holiday", hid)
    _commit(db)
    return {"ok": True}


@router.post("/holidays/sync")
def sync_holidays(year: int = date.today().year, db: Session = Depends(get_db), user: User = Depends(require(MANAGE))):
    from ..services.sheets_sync import sync_holidays as _sync
    n = _sync(db, date(year, 1, 1), date(year + 1, 12, 31))
    return {"added": n}


# ------------------------------------------------------- solver settings
@router.get("/settings/solver")
def get_solver_settings(db: Session = Depends(get_db), _: User = Depends(current_user)):
    from ..services.snapshot import load_weights
    return load_weights(db).__dict__


@router.put("/settings/solver")
def put_solver_settings(body: dict[str, float], db: Session = Depends(get_db), user: User = Depends(require(ADMIN))):
    from ..domain.types import Weights
    allowed = set(Weights().__dict__)
    for k, v in body.items():
        if k not in allowed:
            raise HTTPException(422, f"Unknown setting {k}")
        row = db.get(M.SolverSetting, k) or M.SolverSetting(key=k)
        row.value = float(v)
        db.add(row)
    audit(db, user.username, "UPDATED", "solver_settings", None, None, body)
    _commit(db)
    return {"ok": True}
