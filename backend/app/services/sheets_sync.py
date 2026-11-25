"""Google Sheets / Calendar synchronisation.

Inbound: rules + coverage (pull, validate, diff, version).
Outbound: published roster -> dashboard workbook tabs (push, idempotent).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as M
from ..config import get_settings
from ..domain.calendar import fmt_minutes, required_heads
from ..domain.rules_parser import RowError, parse_overrides, parse_service_lines
from ..domain.types import WEEKDAY_NAMES, Plan, Problem, Status
from ..domain.validator import heads_on
from ..integrations.google import google
from .audit import audit

STATUS_CODE = {"WORK": "W", "WEEK_OFF": "WO", "HOLIDAY": "PH", "LEAVE": "L", "COMP_OFF": "CO"}


def _fetch_rules():
    s = get_settings()
    g = google()
    lines_rows = g.get_values(s.rules_spreadsheet_id, "ServiceLines!A1:Z1000")
    ov_rows = g.get_values(s.rules_spreadsheet_id, "CoverageOverrides!A1:Z1000")
    revision = g.file_version(s.rules_spreadsheet_id)
    return lines_rows, ov_rows, revision


def _line_signature(kind, mask, ph, heads, wmin, s, e) -> dict:
    return {"calendar": kind, "weekday_mask": mask, "works_ph": ph, "min_heads": heads,
            "weekday_min": {str(k): v for k, v in sorted(wmin.items())}, "shift": f"{fmt_minutes(s)}-{fmt_minutes(e)}"}


def plan_import(db: Session) -> dict:
    lines_rows, ov_rows, revision = _fetch_rules()
    rules, errors = parse_service_lines(lines_rows[0] if lines_rows else [], lines_rows[1:])
    overrides, ov_errors = parse_overrides(ov_rows[0] if ov_rows else [], ov_rows[1:])
    errors += ov_errors
    brands = {b.name.lower(): b for b in db.scalars(select(M.Brand))}
    processes = {p.code: p for p in db.scalars(select(M.Process))}
    existing = {(sl.brand.name.lower(), sl.process.code): sl
                for sl in db.scalars(select(M.ServiceLine))}

    added, changed, unchanged, valid_rules = [], [], 0, []
    for i, r in enumerate(rules):
        if r.brand.lower() not in brands:
            row_no = next((n for n, row in enumerate(lines_rows[1:], start=2)
                           if row and row[0].strip().lower() == r.brand.lower()), 0)
            errors.append(RowError("ServiceLines", row_no, "A",
                                   f"Unknown brand '{r.brand}'. Add the brand in the app first."))
            continue
        valid_rules.append(r)
        new_sig = _line_signature(r.calendar_kind, r.weekday_mask, r.works_ph, r.min_heads,
                                  r.weekday_min, r.shift_start, r.shift_end)
        cur = existing.get((r.brand.lower(), r.process))
        label = f"{brands[r.brand.lower()].name} · {r.process}"
        if cur is None:
            added.append({"line": label, "after": new_sig, "new_process": r.process not in processes})
            continue
        old_sig = _line_signature(cur.calendar_kind, cur.weekday_mask, cur.works_ph, cur.min_heads,
                                  {int(k): v for k, v in (cur.weekday_min or {}).items()},
                                  cur.shift_start, cur.shift_end)
        if old_sig != new_sig or not cur.active:
            changed.append({"line": label, "before": old_sig, "after": new_sig})
        else:
            unchanged += 1
    sheet_keys = {(r.brand.lower(), r.process) for r in valid_rules}
    removed = [f"{sl.brand.name} · {sl.process.code}" for k, sl in existing.items()
               if sl.active and k not in sheet_keys]

    checksum = hashlib.sha256(json.dumps([lines_rows, ov_rows]).encode()).hexdigest()
    last = db.scalar(select(M.RuleSet).order_by(M.RuleSet.version.desc()))
    return {
        "revision": revision, "checksum": checksum,
        "current_version": last.version if last else None,
        "current_revision": last.sheet_revision if last else None,
        "up_to_date": bool(last and last.checksum == checksum),
        "added": added, "changed": changed, "removed": removed, "unchanged": unchanged,
        "overrides": [{"line": f"{o.brand} · {o.process}", "date": o.on_date.isoformat(),
                       "min_heads": o.min_heads, "reason": o.reason} for o in overrides],
        "errors": [{"cell": e.cell, "message": e.message} for e in errors],
        "_rules": valid_rules, "_overrides": overrides,
    }


def apply_import(db: Session, actor: str) -> dict:
    plan = plan_import(db)
    version = (db.scalar(select(func.max(M.RuleSet.version))) or 0) + 1
    rs = M.RuleSet(version=version, sheet_revision=plan["revision"], checksum=plan["checksum"],
                   imported_by=actor, summary={k: (len(v) if isinstance(v, list) else v) for k, v in plan.items()
                                               if not k.startswith("_") and k in ("added", "changed", "removed", "errors", "unchanged")})
    db.add(rs)
    db.flush()
    brands = {b.name.lower(): b for b in db.scalars(select(M.Brand))}
    processes = {p.code: p for p in db.scalars(select(M.Process))}
    existing = {(sl.brand.name.lower(), sl.process.code): sl for sl in db.scalars(select(M.ServiceLine))}
    seen = set()
    for r in plan["_rules"]:
        brand = brands[r.brand.lower()]
        proc = processes.get(r.process)
        if proc is None:  # dynamic process addition straight from the sheet
            proc = M.Process(code=r.process, name=r.process)
            db.add(proc)
            db.flush()
            processes[r.process] = proc
        sl = existing.get((r.brand.lower(), r.process))
        if sl is None:
            sl = M.ServiceLine(brand_id=brand.id, process_id=proc.id)
            db.add(sl)
        sl.calendar_kind, sl.weekday_mask, sl.works_ph = r.calendar_kind, r.weekday_mask, r.works_ph
        sl.min_heads = r.min_heads
        sl.weekday_min = {str(k): v for k, v in r.weekday_min.items()}
        sl.shift_start, sl.shift_end = r.shift_start, r.shift_end
        sl.rule_set_version = version
        sl.active = True
        seen.add((r.brand.lower(), r.process))
    for k, sl in existing.items():
        if k not in seen:
            sl.active = False
    db.flush()

    lines = {(sl.brand.name.lower(), sl.process.code): sl for sl in db.scalars(select(M.ServiceLine))}
    db.query(M.CoverageOverride).delete()
    for o in plan["_overrides"]:
        sl = lines.get((o.brand.lower(), o.process))
        if sl is not None:
            db.add(M.CoverageOverride(service_line_id=sl.id, on_date=o.on_date, min_heads=o.min_heads,
                                      reason=o.reason))
    audit(db, actor, "RULES_IMPORTED", "rule_set", str(version), None,
          {"revision": plan["revision"], "added": len(plan["added"]), "changed": len(plan["changed"]),
           "removed": len(plan["removed"]), "errors": len(plan["errors"])})
    db.commit()
    return {k: v for k, v in plan.items() if not k.startswith("_")} | {"version": version}


def write_back_rules(db: Session, actor: str) -> dict:
    """An edit made in the app is written back to the Sheet, then re-imported,
    so the Sheet stays the single source of truth for rules."""
    rows = [list(RULE_HEADER)]
    for sl in db.scalars(select(M.ServiceLine).join(M.Brand).where(M.ServiceLine.active.is_(True))
                         .order_by(M.Brand.name)):
        wmin = ";".join(f"{WEEKDAY_NAMES[int(k)]}:{v}" for k, v in sorted((sl.weekday_min or {}).items()))
        days = ",".join(WEEKDAY_NAMES[i] for i in range(7) if (sl.weekday_mask >> i) & 1) \
            if sl.calendar_kind == "CUSTOM" else ""
        rows.append([sl.brand.name, sl.process.code, sl.calendar_kind, days, str(sl.min_heads), wmin,
                     f"{fmt_minutes(sl.shift_start)}-{fmt_minutes(sl.shift_end)}"])
    google().replace_tabs(get_settings().rules_spreadsheet_id, {"ServiceLines": rows})
    return apply_import(db, actor)


RULE_HEADER = ["brand", "process", "calendar", "weekdays", "min_heads", "weekday_min", "shift"]


def sync_holidays(db: Session, start: date, end: date) -> int:
    g = google()
    n = 0
    have = {(h.calendar_id, h.on_date) for h in db.scalars(select(M.Holiday))}
    for cid in get_settings().holiday_calendar_ids.split(","):
        for d, name in g.holidays(cid.strip(), start, end):
            if (cid, d) not in have:
                db.add(M.Holiday(calendar_id=cid.strip(), on_date=d, name=name))
                n += 1
    db.commit()
    return n


def push_dashboards(db: Session, p: Problem, plan: Plan, roster: M.Roster) -> dict:
    """Mirror a roster into the dashboard workbook: Company, one tab per pod,
    one per multi-person brand, a coverage heatmap and open conflicts."""
    from ..domain.validator import validate
    days = p.days
    header = ["Code", "Employee", "Pod"] + [f"{d:%d} {WEEKDAY_NAMES[d.weekday()]}" for d in days]
    pods = {pod.id: pod.name for pod in db.scalars(select(M.Pod))}

    def row(e):
        cells = []
        for d in days:
            c = plan.get(e.id, d)
            if c is None:
                cells.append("")
                continue
            code = STATUS_CODE[c.status.value]
            if c.status == Status.WORK and any(c.covers.values()):
                code += "+B"
            cells.append(code)
        return [e.code, e.name, pods.get(e.pod_id, "")] + cells

    tabs: dict[str, list[list[str]]] = {}
    tabs["Company"] = [header] + [row(e) for e in p.employees]
    for pid, pname in pods.items():
        tabs[pname] = [header] + [row(e) for e in p.employees if e.pod_id == pid]
    brands: dict[str, list] = {}
    for l in p.lines:
        brands.setdefault(l.brand_name, []).append(l)
    for bname, blines in brands.items():
        people = {a.employee_id for l in blines for a in p.assign_by_line[l.id] if a.role == "PRIMARY"}
        if len(people) >= 2:
            tabs[f"Brand - {bname}"] = [header] + [row(p.emp_by_id[e]) for e in sorted(people)]
    cov = [["Line"] + header[3:]]
    for l in p.lines:
        vals = []
        for d in days:
            req = required_heads(p, l, d)
            vals.append("" if req == 0 else f"{len(heads_on(p, plan, l.id, d))}/{req}")
        cov.append([l.label] + vals)
    tabs["Coverage"] = cov
    confl = [["Severity", "Code", "Date", "Title", "Detail"]]
    for c in validate(p, plan):
        if c.severity != "INFO":
            confl.append([c.severity, f"{c.code} {c.name}", c.date.isoformat() if c.date else "", c.title, c.detail])
    tabs["Open conflicts"] = confl
    tabs["About"] = [["Roster month", roster.month.strftime("%B %Y")], ["Version", str(roster.version)],
                     ["Status", roster.status], ["Idempotency key", f"{roster.id}:{roster.version}"],
                     ["Legend", "W work · W+B covering as backup · WO weekly off · PH holiday · L leave · CO comp-off"]]
    rows = google().replace_tabs(get_settings().dashboard_spreadsheet_id, tabs)
    return {"tabs": list(tabs), "rows": rows}
