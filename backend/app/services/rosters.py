"""Roster lifecycle: generate, repair, edit, validate, acknowledge, publish.

Rosters are versioned per month. Editing a published roster never mutates it:
the edit lands in a new DRAFT version, so every published version stays
reproducible and comparable.
"""
from __future__ import annotations

import threading
import time
import traceback
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as M
from ..config import get_settings
from ..db import SessionLocal
from ..domain.calendar import employee_holiday, required_heads
from ..domain.precheck import diff_plans, precheck
from ..domain.recommender import suggest
from ..domain.solver import SolveResult, solve
from ..domain.types import Cell, Plan, Problem, Status
from ..domain.validator import heads_on, risk_checks, summarize, validate
from .audit import audit, notify
from .snapshot import build_problem, month_bounds, roster_plan


class RosterError(Exception):
    pass


# ------------------------------------------------------------------ helpers
def latest(db: Session, month: date, statuses=("DRAFT", "PUBLISHED")) -> M.Roster | None:
    return db.scalar(select(M.Roster).where(M.Roster.month == month.replace(day=1),
                                            M.Roster.status.in_(statuses))
                     .order_by(M.Roster.version.desc()))


def published(db: Session, month: date) -> M.Roster | None:
    return latest(db, month, ("PUBLISHED",))


def current_rule_version(db: Session) -> int | None:
    return db.scalar(select(func.max(M.RuleSet.version)))


def save_plan(db: Session, month: date, plan: Plan, *, kind: str, actor: str, parent_id: str | None = None,
              note: str = "", stats: dict | None = None) -> M.Roster:
    version = (db.scalar(select(func.max(M.Roster.version)).where(M.Roster.month == month)) or 0) + 1
    r = M.Roster(month=month, version=version, status="DRAFT", parent_id=parent_id, kind=kind, note=note,
                 created_by=actor, rule_set_version=current_rule_version(db), solver_stats=stats or {})
    db.add(r)
    db.flush()
    db.bulk_save_objects([M.RosterDay(roster_id=r.id, employee_id=e, on_date=d, status=c.status.value,
                                      source=c.source, locked=c.locked, covers=c.covers)
                          for (e, d), c in plan.cells.items()])
    if parent_id:  # acknowledged conflicts stay acknowledged in derived versions
        for a in db.scalars(select(M.ConflictAck).where(M.ConflictAck.roster_id == parent_id)):
            db.add(M.ConflictAck(roster_id=r.id, conflict_key=a.conflict_key, reason=a.reason,
                                 acked_by=a.acked_by))
    # older drafts of the same month are superseded by the newest draft
    for old in db.scalars(select(M.Roster).where(M.Roster.month == month, M.Roster.status == "DRAFT",
                                                 M.Roster.id != r.id)):
        old.status = "DISCARDED"
    db.flush()
    return r


def _solve_via_queue(p: Problem) -> SolveResult:
    s = get_settings()
    if not s.redis_url:
        return solve(p)
    from redis import Redis
    from rq import Queue
    q = Queue("solve", connection=Redis.from_url(s.redis_url))
    job = q.enqueue("app.worker.solve_problem", p.to_dict(), job_timeout=int(p.weights.time_limit_s * 4) + 30)
    deadline = time.time() + p.weights.time_limit_s * 4 + 60
    while time.time() < deadline:
        st = job.get_status(refresh=True)
        if st == "finished":
            return SolveResult.from_dict(job.return_value())
        if st == "failed":
            raise RosterError("Solver worker failed")
        time.sleep(0.3)
    raise RosterError("Solver worker timed out")


# ---------------------------------------------------------------- jobs
def start_job(db: Session, kind: str, month: date, actor: str, params: dict, *, background: bool = True) -> M.Job:
    job = M.Job(kind=kind, month=month.replace(day=1), params=params, created_by=actor)
    db.add(job)
    db.commit()
    if background:
        threading.Thread(target=run_job, args=(job.id,), daemon=True).start()
    else:
        run_job(job.id)
        db.refresh(job)
    return job


def run_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(M.Job, job_id)
        job.status = "RUNNING"
        db.commit()
        if job.kind == "GENERATE":
            r = _generate(db, job.month, job.created_by or "system", job.params)
        else:
            r = _repair(db, job.params["roster_id"], job.created_by or "system", job.params)
        job.status, job.result_roster_id = "DONE", r.id
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # surface any failure on the job record
        db.rollback()
        job = db.get(M.Job, job_id)
        job.status, job.error = "FAILED", f"{exc}\n{traceback.format_exc(limit=3)}"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _generate(db: Session, month: date, actor: str, params: dict) -> M.Roster:
    base = latest(db, month)
    locks_from = roster_plan(base) if (base and params.get("keep_locks", True)) else None
    p = build_problem(db, month, locks_from=locks_from)
    impossible = precheck(p)
    res = _solve_via_queue(p)
    stats = {"mode": "FULL", "status": res.status, "objective": res.objective, "wall_ms": res.wall_ms,
             "gaps": len(res.gaps), "impossible_slots": len(impossible), "notes": res.notes, **res.stats}
    r = save_plan(db, month, res.plan, kind="FULL", actor=actor, parent_id=base.id if base else None,
                  note=params.get("note", "Generated by solver"), stats=stats)
    summary = summarize(validate(p, res.plan))
    r.solver_stats = {**stats, "conflicts": summary}
    audit(db, actor, "ROSTER_GENERATED", "roster", r.id, None,
          {"month": month.isoformat(), "version": r.version, **summary})
    db.commit()
    return r


def repair_window_for(p: Problem, plan: Plan, pad: int = 7, skip: set[str] = frozenset()) -> tuple[date, date] | None:
    dates = [c.date for c in validate(p, plan) if c.severity == "HARD" and c.date and c.key not in skip]
    if not dates:
        return None
    return max(p.start, min(dates) - timedelta(days=pad)), min(p.end, max(dates) + timedelta(days=pad))


def _repair(db: Session, roster_id: str, actor: str, params: dict) -> M.Roster:
    src = db.get(M.Roster, roster_id)
    base = roster_plan(src)
    p0 = build_problem(db, src.month)
    acked = {a.conflict_key for a in db.scalars(select(M.ConflictAck).where(M.ConflictAck.roster_id == src.id))}
    window = repair_window_for(p0, base, params.get("pad", 7), acked)
    if window is None:
        raise RosterError("Nothing to repair: every hard conflict is already acknowledged or resolved.")
    p = build_problem(db, src.month, baseline=base, repair_window=window, locks_from=base)
    res = _solve_via_queue(p)
    changes = diff_plans(base, res.plan)
    before, after = summarize(validate(p, base)), summarize(validate(p, res.plan))
    stats = {"mode": "REPAIR", "status": res.status, "objective": res.objective, "wall_ms": res.wall_ms,
             "window": [window[0].isoformat(), window[1].isoformat()], "changed_cells": len(changes),
             "conflicts_before": before, "conflicts": after, "notes": res.notes, **res.stats}
    r = save_plan(db, src.month, res.plan, kind="REPAIR", actor=actor, parent_id=src.id,
                  note=f"Repair of v{src.version}: {len(changes)} cell(s) changed", stats=stats)
    audit(db, actor, "ROSTER_REPAIRED", "roster", r.id, {"from_version": src.version}, stats)
    db.commit()
    return r


# ----------------------------------------------------------- validation
def evaluate(db: Session, r: M.Roster) -> dict:
    plan = roster_plan(r)
    p = build_problem(db, r.month)
    conflicts = validate(p, plan)
    acks = {a.conflict_key: {"reason": a.reason, "by": a.acked_by}
            for a in db.scalars(select(M.ConflictAck).where(M.ConflictAck.roster_id == r.id))}
    stale = r.rule_set_version is not None and r.rule_set_version != current_rule_version(db)
    out = [c.to_dict() | {"acknowledged": acks.get(c.key)} for c in conflicts]
    if stale:
        out.append({"code": "C12", "name": "STALE_ROSTER", "severity": "SOFT", "key": "C12",
                    "title": "Rules changed since this roster was built",
                    "detail": f"Built under rule set v{r.rule_set_version}; current is v{current_rule_version(db)}. "
                              "Conflicts above are already checked against the current rules.",
                    "date": None, "line_id": None, "employee_id": None, "brand_id": None,
                    "explanation": {}, "acknowledged": None})
    risks = [c.to_dict() for c in risk_checks(p)]
    return {"problem": p, "plan": plan, "conflicts": out, "summary": summarize(conflicts), "risks": risks,
            "impossible": [s.to_dict() for s in precheck(p)]}


def grid(db: Session, r: M.Roster) -> dict:
    ev = evaluate(db, r)
    p: Problem = ev["problem"]
    plan: Plan = ev["plan"]
    pods = {x.id: {"id": x.id, "name": x.name, "lead_id": x.lead_id} for x in db.scalars(select(M.Pod))}
    cov = []
    for l in p.lines:
        days = []
        for d in p.days:
            req = required_heads(p, l, d)
            heads = heads_on(p, plan, l.id, d) if req else []
            days.append({"req": req, "heads": heads})
        cov.append({"line_id": l.id, "label": l.label, "brand_id": l.brand_id, "brand": l.brand_name,
                    "process": l.process_code, "pod_id": l.pod_id, "calendar": l.calendar_kind,
                    "days": days,
                    "assignees": [{"employee_id": a.employee_id, "role": a.role, "load": a.load_pct}
                                  for a in p.assign_by_line[l.id]]})
    emps = []
    for e in p.employees:
        cells = []
        for d in p.days:
            c = plan.get(e.id, d)
            cells.append(None if c is None else {**c.to_dict(), "holiday": employee_holiday(p, e, d)})
        emps.append({"id": e.id, "code": e.code, "name": e.name, "pod_id": e.pod_id, "is_lead": e.is_lead,
                     "preferred_off": list(e.preferred_off_weekdays), "cells": cells,
                     "assignments": [{"line_id": a.line_id, "role": a.role, "load": a.load_pct}
                                     for a in p.assign_by_emp[e.id]]})
    holidays = sorted({d.isoformat() for ds in p.holidays.values() for d in ds})
    return {"roster": roster_meta(r), "days": [d.isoformat() for d in p.days], "pods": list(pods.values()),
            "employees": emps, "coverage": cov, "conflicts": ev["conflicts"], "summary": ev["summary"],
            "risks": ev["risks"], "impossible": ev["impossible"], "holidays": holidays}


def roster_meta(r: M.Roster) -> dict:
    return {"id": r.id, "month": r.month.isoformat(), "version": r.version, "status": r.status, "kind": r.kind,
            "note": r.note, "parent_id": r.parent_id, "rule_set_version": r.rule_set_version,
            "created_by": r.created_by, "created_at": r.created_at.isoformat() if r.created_at else None,
            "published_at": r.published_at.isoformat() if r.published_at else None, "stats": r.solver_stats}


# -------------------------------------------------------------- editing
def _editable(db: Session, r: M.Roster, actor: str) -> M.Roster:
    if r.status == "DRAFT":
        return r
    if r.status != "PUBLISHED":
        raise RosterError(f"Version {r.version} is {r.status.lower()} and can't be edited.")
    newer = latest(db, r.month, ("DRAFT",))
    if newer is not None and newer.version > r.version:
        return newer
    return save_plan(db, r.month, roster_plan(r), kind="EDIT", actor=actor, parent_id=r.id,
                     note=f"Edits on top of published v{r.version}")


def apply_edits(db: Session, roster_id: str, edits: list[dict], actor: str) -> tuple[M.Roster, dict]:
    src = db.get(M.Roster, roster_id)
    if src is None:
        raise RosterError("Roster not found")
    p = build_problem(db, src.month)
    before_plan = roster_plan(src)
    before = {c.key for c in validate(p, before_plan) if c.severity == "HARD"}
    r = _editable(db, src, actor)
    rows = {(d.employee_id, d.on_date): d for d in r.days}
    for ed in edits:
        d = date.fromisoformat(ed["date"])
        row = rows.get((ed["employee_id"], d))
        if row is None:
            raise RosterError(f"No cell for {ed['employee_id']} on {d}")
        old = {"status": row.status, "covers": row.covers, "locked": row.locked}
        status = Status(ed.get("status", row.status))
        covers = ed.get("covers", row.covers if status == Status.WORK else {})
        if status != Status.WORK:
            covers = {}
        row.status, row.covers, row.source = status.value, dict(covers), "MANUAL"
        if "locked" in ed:
            row.locked = bool(ed["locked"])
        audit(db, actor, "CELL_EDITED", "roster_day", row.id, old,
              {"status": row.status, "covers": row.covers, "locked": row.locked, "date": d.isoformat()})
    db.flush()
    db.refresh(r)
    after_conf = validate(p, roster_plan(r))
    introduced = [c.to_dict() for c in after_conf if c.severity == "HARD" and c.key not in before]
    resolved = len(before - {c.key for c in after_conf if c.severity == "HARD"})
    db.commit()
    return r, {"introduced": introduced, "resolved": resolved, "summary": summarize(after_conf)}


def suggestions(db: Session, roster_id: str, d: date, line_ids: list[str]) -> list[dict]:
    r = db.get(M.Roster, roster_id)
    p = build_problem(db, r.month)
    return [s.to_dict() for s in suggest(p, roster_plan(r), d, line_ids)]


def acknowledge(db: Session, roster_id: str, key: str, reason: str, actor: str) -> None:
    if not reason.strip():
        raise RosterError("A reason is required to acknowledge a hard conflict.")
    db.add(M.ConflictAck(roster_id=roster_id, conflict_key=key, reason=reason.strip(), acked_by=actor))
    audit(db, actor, "CONFLICT_ACKNOWLEDGED", "roster", roster_id, None, {"key": key, "reason": reason})
    db.commit()


def publish(db: Session, roster_id: str, actor: str) -> dict:
    r = db.get(M.Roster, roster_id)
    if r is None or r.status != "DRAFT":
        raise RosterError("Only a draft can be published.")
    ev = evaluate(db, r)
    blocking = [c for c in ev["conflicts"] if c["severity"] == "HARD" and not c["acknowledged"]]
    if blocking:
        raise RosterError(f"{len(blocking)} hard conflict(s) are open. Resolve them or acknowledge each with a reason.")
    prev = published(db, r.month)
    changed_people: set[str] = set()
    if prev is not None:
        changed_people = {c["employee_id"] for c in diff_plans(roster_plan(prev), ev["plan"])}
        prev.status = "SUPERSEDED"
    r.status, r.published_at = "PUBLISHED", datetime.now(timezone.utc)
    p: Problem = ev["problem"]
    for (eid, d), c in ev["plan"].cells.items():   # comp-off credits for working a public holiday
        if c.status == Status.WORK and employee_holiday(p, p.emp_by_id[eid], d):
            exists = db.scalar(select(M.CompOffCredit).where(M.CompOffCredit.employee_id == eid,
                                                             M.CompOffCredit.earned_on == d))
            if exists is None:
                db.add(M.CompOffCredit(employee_id=eid, earned_on=d, expires_on=d + timedelta(days=30),
                                       roster_id=r.id))
    audit(db, actor, "ROSTER_PUBLISHED", "roster", r.id, {"previous": prev.version if prev else None},
          {"version": r.version, "changed_people": len(changed_people)})
    month_txt = r.month.strftime("%B %Y")
    if prev is None:
        notify(db, f"{month_txt} roster v{r.version} published.", roster_id=r.id)
    for eid in changed_people:
        notify(db, f"Your {month_txt} schedule changed in v{r.version}.", audience=f"EMP:{eid}",
               roster_id=r.id, employee_id=eid)
    db.commit()
    sheet = {"ok": False}
    try:
        from .sheets_sync import push_dashboards
        sheet = {"ok": True, **push_dashboards(db, p, ev["plan"], r)}
    except Exception as exc:  # the roster is published even if the mirror push fails
        sheet = {"ok": False, "error": str(exc)}
    return {"roster": roster_meta(r), "notified": len(changed_people), "sheets": sheet}
