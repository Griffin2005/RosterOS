"""CP-SAT roster model.

Hard rules (H1-H8) are constraints. Coverage (H2) uses penalised slack so that
an impossible month still yields the *best possible* roster plus an exact list of
the slots that could not be filled, instead of "INFEASIBLE". Preferences are
weighted penalties, always cheaper than a coverage gap.

The function is pure: Problem in, SolveResult out. Solver workers run it without
database access.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from ortools.sat.python import cp_model

from .calendar import (employee_holiday, fixed_status, line_operates, required_heads,
                       required_offs, shifts_compatible, weeks)
from .types import Cell, Plan, Problem, Status, Weights


@dataclass
class SolveResult:
    plan: Plan
    status: str
    objective: float | None
    wall_ms: int
    gaps: dict[tuple[str, date], int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"plan": self.plan.to_dict(), "status": self.status, "objective": self.objective,
                "wall_ms": self.wall_ms,
                "gaps": [[l, d.isoformat(), n] for (l, d), n in self.gaps.items()],
                "notes": self.notes, "stats": self.stats}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "SolveResult":
        return SolveResult(Plan.from_dict(d["plan"]), d["status"], d["objective"], d["wall_ms"],
                           {(l, date.fromisoformat(x)): n for l, x, n in d["gaps"]},
                           d.get("notes", []), d.get("stats", {}))


def solve(p: Problem) -> SolveResult:
    """Decompose, solve each independent part, merge.

    Employees and lines only interact through assignments, so the connected
    components of the employee-line graph (in practice: the pods) are
    independent models whose optima add up to the optimum of the whole. The
    one exception is Sunday fairness, which becomes "fair among peers who can
    cover each other", the more meaningful definition anyway.

    Parts run one after another with every worker rather than side by side:
    CP-SAT's portfolio needs several workers on one model to prove optimality
    (measured: 3 parts x 2 workers never proved optimal in 30 s; 3 parts x 8
    workers in sequence proved optimal in 5-7 s). Time a small part doesn't use
    flows to the parts after it.
    """
    started = time.perf_counter()
    comps = components(p)
    if len(comps) <= 1 or not p.weights.decompose:
        res = _solve_with_fallbacks(p)
        res.stats["components"] = 1
    else:
        sizes = [len(E) * len(p.days) + len(L) for E, L in comps]
        deadline = started + p.weights.time_limit_s
        left_size = sum(sizes)
        parts = []
        for (E, L), size in zip(comps, sizes):
            budget = max(2.0, (deadline - time.perf_counter()) * size / left_size)
            left_size -= size
            parts.append(_solve_with_fallbacks(subproblem(p, E, L, replace(p.weights, time_limit_s=budget))))
        res = _merge(parts)
        res.stats["components"] = len(comps)
        res.stats["component_sizes"] = [len(E) for E, _ in comps]
    res.wall_ms = int((time.perf_counter() - started) * 1000)
    return res


def components(p: Problem) -> list[tuple[set[str], set[str]]]:
    """Connected components of the bipartite employee-line assignment graph."""
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in p.employees:
        parent[("e", e.id)] = ("e", e.id)
    for l in p.lines:
        parent[("l", l.id)] = ("l", l.id)
    for a in p.assignments:
        ka, kb = ("e", a.employee_id), ("l", a.line_id)
        if ka in parent and kb in parent:
            ra, rb = find(ka), find(kb)
            if ra != rb:
                parent[rb] = ra
    groups: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    for key in parent:
        E, L = groups.setdefault(find(key), (set(), set()))
        (E if key[0] == "e" else L).add(key[1])
    order = {e.id: i for i, e in enumerate(p.employees)}
    return sorted(groups.values(), key=lambda g: min((order[x] for x in g[0]), default=len(order)))


def subproblem(p: Problem, E: set[str], L: set[str], weights: Weights) -> Problem:
    return Problem(
        start=p.start, end=p.end,
        employees=[e for e in p.employees if e.id in E],
        lines=[l for l in p.lines if l.id in L],
        assignments=[a for a in p.assignments if a.employee_id in E and a.line_id in L],
        leaves={k: v for k, v in p.leaves.items() if k[0] in E},
        holidays=p.holidays, org_holiday_calendar=p.org_holiday_calendar,
        overrides={k: v for k, v in p.overrides.items() if k[0] in L},
        prev_streak={k: v for k, v in p.prev_streak.items() if k in E},
        locks={k: v for k, v in p.locks.items() if k[0] in E},
        baseline=p.baseline, repair_window=p.repair_window, weights=weights)


def _merge(parts: list[SolveResult]) -> SolveResult:
    plan = Plan()
    gaps: dict[tuple[str, date], int] = {}
    notes: list[str] = []
    for r in parts:
        plan.cells.update(r.plan.cells)
        gaps.update(r.gaps)
        notes += [n for n in r.notes if n not in notes]
    st = [r.stats for r in parts]
    return SolveResult(
        plan=plan,
        status="OPTIMAL" if all(r.status == "OPTIMAL" for r in parts) else "FEASIBLE",
        objective=sum(r.objective or 0 for r in parts), wall_ms=0, gaps=gaps, notes=notes,
        stats={"bools": sum(s.get("bools", 0) for s in st),
               "slack_vars": sum(s.get("slack_vars", 0) for s in st),
               "optimality_gap_pct": max((s.get("optimality_gap_pct", 0) for s in st), default=0),
               "branches": sum(s.get("branches", 0) for s in st),
               "coverage_proven_optimal": all(s.get("coverage_proven_optimal") for s in st),
               "component_ms": [r.wall_ms for r in parts],
               "component_status": [r.status for r in parts],
               "locks_applied": any(s.get("locks_applied") for s in st),
               "frozen_outside_window": any(s.get("frozen_outside_window") for s in st)})


class _StallStop(cp_model.CpSolverSolutionCallback):
    """Stops a search that hasn't found a better solution for stall_s seconds."""

    def __init__(self, solver: cp_model.CpSolver, stall_s: float):
        super().__init__()
        self._solver, self._stall = solver, stall_s
        self._last = time.perf_counter()
        self._running = True
        import threading
        self._t = threading.Thread(target=self._watch, daemon=True)
        self._t.start()

    def on_solution_callback(self):
        self._last = time.perf_counter()

    def _watch(self):
        while self._running:
            time.sleep(0.25)
            if self._running and time.perf_counter() - self._last > self._stall:
                self._solver.stop_search()
                return

    def done(self):
        self._running = False


def _solve_with_fallbacks(p: Problem) -> SolveResult:
    started = time.perf_counter()
    notes: list[str] = []
    res = _solve_once(p, use_locks=True, freeze=True)
    if res is None and p.locks:
        notes.append("Manual locks made the month infeasible; solved again without locks. "
                     "Review the locked cells flagged in the conflict list.")
        res = _solve_once(p, use_locks=False, freeze=True)
    if res is None and p.repair_window:
        notes.append("Frozen cells outside the repair window conflicted with current rules; "
                     "solved the whole month instead.")
        res = _solve_once(p, use_locks=False, freeze=False)
    if res is None:
        raise RuntimeError("Roster model infeasible even without locks; check weekly-off and streak settings.")
    res.notes = notes + res.notes
    res.wall_ms = int((time.perf_counter() - started) * 1000)
    return res


def _solve_once(p: Problem, use_locks: bool, freeze: bool) -> SolveResult | None:
    w = p.weights
    m = cp_model.CpModel()
    days = p.days
    fixed: dict[tuple[str, date], Status | None] = {
        (e.id, d): fixed_status(p, e, d) for e in p.employees for d in days}
    in_window = (lambda d: True) if not (p.repair_window and freeze) else (
        lambda d: p.repair_window[0] <= d <= p.repair_window[1])

    work: dict[tuple[str, date], cp_model.IntVar] = {}
    cover: dict[tuple[str, str, date], cp_model.IntVar] = {}
    obj: list[Any] = []

    # ---- variables, H1, H3, H4, H5 ------------------------------------
    for e in p.employees:
        assigns = p.assign_by_emp.get(e.id, [])
        for d in days:
            if fixed[(e.id, d)] is not None:
                continue  # H1: no variable -> cannot work
            wv = m.NewBoolVar(f"w_{e.id}_{d}")
            work[(e.id, d)] = wv
            cvs = []
            loads = []
            for a in assigns:
                line = p.line_by_id[a.line_id]
                if not line_operates(p, line, d):
                    continue
                cv = m.NewBoolVar(f"c_{e.id}_{a.line_id}_{d}")
                cover[(e.id, a.line_id, d)] = cv
                m.AddImplication(cv, wv)                 # H3
                cvs.append((a, cv))
                loads.append(a.load_pct * cv)
                if a.role == "BACKUP":
                    obj.append(w.backup * cv)
                else:
                    obj.append(-w.primary_reward * cv)
            if cvs:
                m.Add(wv <= sum(cv for _, cv in cvs))   # no idle working days
                m.Add(sum(loads) <= e.capacity)         # H4
                for i in range(len(cvs)):               # H5
                    for j in range(i + 1, len(cvs)):
                        la = p.line_by_id[cvs[i][0].line_id]
                        lb = p.line_by_id[cvs[j][0].line_id]
                        if not shifts_compatible(la, lb, w.max_shift_span_minutes):
                            m.Add(cvs[i][1] + cvs[j][1] <= 1)
            else:
                m.Add(wv == 0)
            # soft: preferred off weekday, working a public holiday
            if employee_holiday(p, e, d):
                obj.append(w.ph_work * wv)
            elif d.weekday() in e.preferred_off_weekdays:
                obj.append(w.preference * wv)

    # ---- H2 coverage with slack ----------------------------------------
    slack: dict[tuple[str, date], cp_model.IntVar] = {}
    for line in p.lines:
        for d in days:
            req = required_heads(p, line, d)
            if req <= 0:
                continue
            terms = [cover[(a.employee_id, line.id, d)] for a in p.assign_by_line.get(line.id, [])
                     if (a.employee_id, line.id, d) in cover]
            s = m.NewIntVar(0, req, f"s_{line.id}_{d}")
            slack[(line.id, d)] = s
            m.Add(sum(terms) + s >= req)
            obj.append(w.gap * s)

    # ---- H6 weekly offs, H7 streaks -------------------------------------
    for e in p.employees:
        for wk in weeks(p):
            countable = [d for d in wk if (e.id, d) in work and not employee_holiday(p, e, d)]
            if not countable:
                continue
            k = min(required_offs(e, len(wk)), len(countable))
            closed = sum(1 for d in countable
                         if not any((e.id, a.line_id, d) in cover for a in p.assign_by_emp.get(e.id, [])))
            offs = sum(1 - work[(e.id, d)] for d in countable)
            m.Add(offs >= k)
            extra = m.NewIntVar(0, len(countable), f"x_{e.id}_{wk[0]}")
            m.Add(extra >= offs - max(k, closed))
            obj.append(w.extra_off * extra)
            if e.weekly_offs >= 2:
                for d1, d2 in zip(countable, countable[1:]):
                    if (d2 - d1).days == 1:
                        adj = m.NewBoolVar(f"adj_{e.id}_{d1}")
                        m.AddImplication(adj, work[(e.id, d1)].Not())
                        m.AddImplication(adj, work[(e.id, d2)].Not())
                        obj.append(-w.adjacent_off * adj)

        mc = e.max_consecutive
        seq: list[Any] = [1] * min(p.prev_streak.get(e.id, 0), mc + 1)
        offset = len(seq)
        seq += [work.get((e.id, d), 0) for d in days]
        for start in range(0, len(seq) - mc):
            window = seq[start:start + mc + 1]
            if start + mc < offset:
                continue
            var_terms = [x for x in window if not isinstance(x, int)]
            const = sum(x for x in window if isinstance(x, int))
            if var_terms:
                m.Add(sum(var_terms) + const <= mc)

    # ---- fairness: spread Sunday work among line owners -----------------
    sunday_owners = [e for e in p.employees if not e.is_lead and any(
        a.role == "PRIMARY" and any(line_operates(p, p.line_by_id[a.line_id], d) for d in days if d.weekday() == 6)
        for a in p.assign_by_emp.get(e.id, []))]
    sundays = [d for d in days if d.weekday() == 6]
    if len(sunday_owners) >= 2 and sundays:
        counts = []
        for e in sunday_owners:
            c = m.NewIntVar(0, len(sundays), f"sun_{e.id}")
            m.Add(c == sum(work.get((e.id, d), 0) for d in sundays))
            counts.append(c)
        hi = m.NewIntVar(0, len(sundays), "sun_hi")
        lo = m.NewIntVar(0, len(sundays), "sun_lo")
        m.AddMaxEquality(hi, counts)
        m.AddMinEquality(lo, counts)
        obj.append(w.fairness * (hi - lo))

    # ---- H8 locks ---------------------------------------------------------
    if use_locks:
        for (eid, d), cell in p.locks.items():
            if (eid, d) not in work:
                continue
            if cell.status == Status.WORK:
                m.Add(work[(eid, d)] == 1)
                for a in p.assign_by_emp.get(eid, []):
                    key = (eid, a.line_id, d)
                    if key in cover:
                        m.Add(cover[key] == (1 if a.line_id in cell.covers else 0))
            else:
                m.Add(work[(eid, d)] == 0)

    # ---- repair mode: stability ----------------------------------------
    base = p.baseline
    if base is not None:
        for (eid, d), wv in work.items():
            bc = base.get(eid, d)
            if bc is None:
                continue
            was = 1 if bc.status == Status.WORK else 0
            m.AddHint(wv, was)
            if freeze and not in_window(d):
                m.Add(wv == was)
            else:
                obj.append(w.change * (wv if was == 0 else (1 - wv)))
            for a in p.assign_by_emp.get(eid, []):
                key = (eid, a.line_id, d)
                if key not in cover:
                    continue
                had = 1 if (bc.status == Status.WORK and a.line_id in bc.covers) else 0
                m.AddHint(cover[key], had)
                if freeze and not in_window(d):
                    m.Add(cover[key] == had)
                else:
                    obj.append(w.cover_change * (cover[key] if had == 0 else (1 - cover[key])))

    # ---- lexicographic solve -------------------------------------------
    # Phase 1 minimises only the number of uncovered line-days and proves that
    # minimum (an easy model with a tight LP bound). Phase 2 pins coverage at
    # the proven minimum and optimises everything else from phase 1's solution.
    # Coverage is never traded for preferences, and a slow phase 2 still hands
    # back a roster whose coverage is provably as good as the rules allow.
    t0 = time.perf_counter()
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = w.workers
    solver.parameters.random_seed = w.seed
    phases: dict[str, Any] = {}
    if slack and w.lexicographic:
        total_gap = sum(slack.values())
        m.Minimize(total_gap)
        # coverage gets most of the budget: it usually proves in ~1 s, but on a
        # throttled host (0.1 vCPU) wall time buys little CPU and this phase matters most
        solver.parameters.max_time_in_seconds = max(1.0, w.time_limit_s * 0.8)
        st1 = solver.Solve(m)
        if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        best_gap = int(round(solver.ObjectiveValue()))
        phases["coverage"] = {"status": "OPTIMAL" if st1 == cp_model.OPTIMAL else "FEASIBLE",
                              "uncovered": best_gap, "ms": int((time.perf_counter() - t0) * 1000)}
        hint = {v: solver.Value(v) for v in (*work.values(), *cover.values())}
        m.ClearHints()
        for v, val in hint.items():
            m.AddHint(v, val)
        m.Add(total_gap <= best_gap)
    m.Minimize(sum(obj))
    budget = max(1.0, w.time_limit_s - (time.perf_counter() - t0))
    solver.parameters.max_time_in_seconds = budget
    if w.workers <= 2:
        # small host: stop once the quality phase stops improving instead of
        # spending the whole limit trying to prove the last few points optimal
        stopper = _StallStop(solver, stall_s=max(3.0, budget * 0.25))
        st = solver.Solve(m, stopper)
        stopper.done()
    else:
        st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    phases["quality"] = {"status": "OPTIMAL" if st == cp_model.OPTIMAL else "FEASIBLE",
                         "ms": int((time.perf_counter() - t0) * 1000) - phases.get("coverage", {}).get("ms", 0)}

    plan = Plan()
    for e in p.employees:
        for d in days:
            fs = fixed[(e.id, d)]
            if fs is not None:
                plan.cells[(e.id, d)] = Cell(fs)
                continue
            if solver.Value(work[(e.id, d)]):
                covers = {a.line_id: a.role == "BACKUP" for a in p.assign_by_emp.get(e.id, [])
                          if (e.id, a.line_id, d) in cover and solver.Value(cover[(e.id, a.line_id, d)])}
                plan.cells[(e.id, d)] = Cell(Status.WORK, covers)
            else:
                plan.cells[(e.id, d)] = Cell(Status.HOLIDAY if employee_holiday(p, e, d) else Status.WEEK_OFF)
            lock = p.locks.get((e.id, d)) if use_locks else None
            if lock is not None:
                plan.cells[(e.id, d)].locked = True
                plan.cells[(e.id, d)].source = "MANUAL"

    gaps = {k: solver.Value(v) for k, v in slack.items() if solver.Value(v) > 0}
    gap_pct = 0.0
    if st == cp_model.FEASIBLE and solver.ObjectiveValue():
        gap_pct = abs(solver.ObjectiveValue() - solver.BestObjectiveBound()) / max(1.0, abs(solver.ObjectiveValue())) * 100
    return SolveResult(
        plan=plan,
        status="OPTIMAL" if st == cp_model.OPTIMAL else "FEASIBLE",
        objective=solver.ObjectiveValue(),
        wall_ms=0,
        gaps=gaps,
        stats={"bools": len(work) + len(cover), "slack_vars": len(slack),
               "optimality_gap_pct": round(gap_pct, 2), "branches": solver.NumBranches(),
               "phases": phases,
               "coverage_proven_optimal": phases.get("coverage", {}).get("status", "OPTIMAL") == "OPTIMAL"
               or st == cp_model.OPTIMAL,
               "locks_applied": use_locks and bool(p.locks), "frozen_outside_window": bool(p.repair_window and freeze)},
    )
