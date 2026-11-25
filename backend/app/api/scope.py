"""Filter roster payloads to what a user's scope allows (company / pod / brand /
process / self). Applied server-side; the UI never receives out-of-scope rows."""
from __future__ import annotations

from ..auth import User


def filter_grid(g: dict, user: User) -> dict:
    lvl = user.scope_level
    if lvl == "COMPANY":
        return g
    if lvl == "POD":
        emp_ok = {e["id"] for e in g["employees"] if e["pod_id"] == user.scope_id}
        line_ok = {c["line_id"] for c in g["coverage"] if c["pod_id"] == user.scope_id}
        # include cross-pod backups who covered this pod's lines
        for e in g["employees"]:
            if any(any(l in line_ok for l in (cell or {}).get("covers", {})) for cell in e["cells"]):
                emp_ok.add(e["id"])
    elif lvl == "BRAND":
        line_ok = {c["line_id"] for c in g["coverage"] if c["brand_id"] == user.scope_id}
        emp_ok = {a["employee_id"] for c in g["coverage"] if c["line_id"] in line_ok for a in c["assignees"]}
    elif lvl == "PROCESS":
        line_ok = {c["line_id"] for c in g["coverage"] if c["process"] == user.scope_id}
        emp_ok = {a["employee_id"] for c in g["coverage"] if c["line_id"] in line_ok for a in c["assignees"]}
    else:  # SELF
        emp_ok = {user.employee_id}
        line_ok = {a["line_id"] for e in g["employees"] if e["id"] == user.employee_id for a in e["assignments"]}
        # colleagues who cover my lines, so I can see who has my brand on my off-days
        emp_ok |= {a["employee_id"] for c in g["coverage"] if c["line_id"] in line_ok for a in c["assignees"]}
    out = dict(g)
    out["employees"] = [e for e in g["employees"] if e["id"] in emp_ok]
    out["coverage"] = [c for c in g["coverage"] if c["line_id"] in line_ok]
    out["conflicts"] = [c for c in g["conflicts"]
                        if (c.get("line_id") in line_ok) or (c.get("employee_id") in emp_ok)
                        or (c.get("line_id") is None and c.get("employee_id") is None)]
    out["scoped"] = True
    return out
