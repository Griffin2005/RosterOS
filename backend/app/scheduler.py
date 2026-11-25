"""Scheduled jobs (docker `scheduler` service; EventBridge Scheduler on AWS).

* 20th of each month, 02:00 IST: draft next month's roster if none exists.
* Every night, 01:00 IST: re-validate current and next month, notify ops of new hard conflicts.
* Every 10 minutes: check the rules Sheet revision and import when it changed.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

from .db import SessionLocal
from .services import rosters as R
from .services.audit import notify
from .services.sheets_sync import apply_import, plan_import

IST = timezone(timedelta(hours=5, minutes=30))


def next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def draft_next_month() -> None:
    db = SessionLocal()
    try:
        m = next_month(datetime.now(IST).date())
        if R.latest(db, m) is None:
            R.start_job(db, "GENERATE", m, "scheduler", {"note": "Monthly auto-draft"}, background=False)
            notify(db, f"Draft roster for {m:%B %Y} is ready for review.", audience="ROLE:OPS_MANAGER")
            db.commit()
    finally:
        db.close()


def nightly_validation() -> None:
    db = SessionLocal()
    try:
        today = datetime.now(IST).date()
        for m in (today.replace(day=1), next_month(today)):
            r = R.latest(db, m)
            if r is None:
                continue
            ev = R.evaluate(db, r)
            open_hard = [c for c in ev["conflicts"] if c["severity"] == "HARD" and not c["acknowledged"]]
            if open_hard:
                notify(db, f"{m:%B %Y} v{r.version}: {len(open_hard)} open hard conflict(s) need attention.",
                       audience="ROLE:OPS_MANAGER", roster_id=r.id)
        db.commit()
    finally:
        db.close()


def poll_rules_sheet() -> None:
    db = SessionLocal()
    try:
        plan = plan_import(db)
        if not plan["up_to_date"] and not plan["errors"]:
            apply_import(db, "scheduler")
    finally:
        db.close()


def main() -> None:
    last: dict[str, str] = {}
    while True:
        now = datetime.now(IST)
        try:
            if now.minute % 10 == 0 and last.get("rules") != now.strftime("%H%M"):
                last["rules"] = now.strftime("%H%M")
                poll_rules_sheet()
            if now.hour == 1 and last.get("nightly") != now.date().isoformat():
                last["nightly"] = now.date().isoformat()
                nightly_validation()
            if now.day == 20 and now.hour == 2 and last.get("draft") != now.date().isoformat():
                last["draft"] = now.date().isoformat()
                draft_next_month()
        except Exception as exc:  # keep the scheduler alive; errors land in container logs
            print("scheduler error:", exc, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
