from datetime import date, timedelta

from app.domain.calendar import line_operates, required_heads, weeks
from app.domain.precheck import diff_plans, precheck
from app.domain.recommender import suggest
from app.domain.solver import solve
from app.domain.types import (ALL_WEEK, MON_SAT, Assignment, Cell, Employee, Problem, ServiceLine,
                              Status, Weights)
from app.domain.validator import heads_on, validate
from conftest import build_sample_problem

W = Weights(time_limit_s=10, workers=4)


def line(id, mask=ALL_WEEK, ph=True, heads=1, start=540, end=1080, **kw):
    return ServiceLine(id=id, brand_id=id.split("|")[0], brand_name=id.split("|")[0],
                       process_code=id.split("|")[1], pod_id="p", weekday_mask=mask, works_ph=ph,
                       min_heads=heads, shift_start=start, shift_end=end, **kw)


def emp(id, **kw):
    return Employee(id=id, code=id, name=id, pod_id="p", **kw)


def problem(emps, lines, assigns, **kw):
    # 1-14 Dec 2026: Tue..Mon, includes two Sundays
    return Problem(start=date(2026, 12, 1), end=date(2026, 12, 14), employees=emps, lines=lines,
                   assignments=assigns, weights=kw.pop("weights", W), **kw)


def hard(conflicts):
    return [c for c in conflicts if c.severity == "HARD"]


# ---------------------------------------------------------------- calendars
def test_calendar_presets_and_overrides():
    xmas = date(2026, 12, 25)
    p = problem([], [line("A|CS"), line("A|ACC", MON_SAT, False), line("A|NDR", ALL_WEEK, False)], [],
                holidays={"IN-NATIONAL": {xmas}}, overrides={("A|ACC", date(2026, 12, 6)): 2})
    cs, acc, ndr = p.lines
    assert line_operates(p, cs, xmas)                 # 365-day runs on PH
    assert not line_operates(p, ndr, xmas)            # NO_PH closed on PH
    assert line_operates(p, ndr, date(2026, 12, 6))   # ...but open on Sunday
    assert not line_operates(p, acc, date(2026, 12, 13))  # Sunday off
    assert required_heads(p, acc, date(2026, 12, 6)) == 2  # override opens a Sunday


def test_weeks_partial_edges(december):
    wk = weeks(december)
    assert wk[0][0] == date(2026, 12, 1) and len(wk[0]) == 6   # Tue..Sun
    assert len(wk[-1]) == 4                                     # Mon 28..Thu 31


# ------------------------------------------------------------------ solver
def test_single_owner_gets_offs_and_backup_covers():
    p = problem([emp("owner"), emp("backup")], [line("K|CS")],
                [Assignment("owner", "K|CS", "PRIMARY", 60), Assignment("backup", "K|CS", "BACKUP", 60)])
    r = solve(p)
    conflicts = validate(p, r.plan)
    assert not r.gaps and not hard(conflicts)
    offs = [d for d in p.days if r.plan.get("owner", d).status == Status.WEEK_OFF]
    assert len(offs) >= 2                       # one per week
    for d in offs:
        assert "K|CS" in r.plan.get("backup", d).covers


def test_impossible_slot_is_reported_not_hidden():
    leave = {("solo", d): Status.LEAVE for d in [date(2026, 12, 8), date(2026, 12, 9)]}
    p = problem([emp("solo")], [line("B|ACC", MON_SAT, False)],
                [Assignment("solo", "B|ACC", "PRIMARY", 50)], leaves=leave)
    slots = precheck(p)
    assert {s.date for s in slots} == {date(2026, 12, 8), date(2026, 12, 9)}
    r = solve(p)
    assert set(d for (_, d) in r.gaps) == {date(2026, 12, 8), date(2026, 12, 9)}
    c01 = [c for c in validate(p, r.plan) if c.code == "C01"]
    assert len(c01) == 2
    assert c01[0].explanation["assignees"][0]["reason"] == "on approved leave"


def test_capacity_and_shift_clash_respected():
    # one person, two lines whose combined span is 12h -> may never carry both
    p = problem([emp("a"), emp("b")],
                [line("U|CS", heads=1, start=540, end=1080), line("U|NDR", heads=1, start=720, end=1260)],
                [Assignment("a", "U|CS", "PRIMARY", 60), Assignment("a", "U|NDR", "PRIMARY", 40),
                 Assignment("b", "U|CS", "PRIMARY", 60), Assignment("b", "U|NDR", "PRIMARY", 40)])
    r = solve(p)
    for (e, d), c in r.plan.cells.items():
        assert not ({"U|CS", "U|NDR"} <= set(c.covers))
    assert not any(c.code in ("C03", "C04") for c in validate(p, r.plan))


def test_streak_limit_with_previous_month_tail():
    p = problem([emp("a", max_consecutive=6), emp("b")], [line("X|CS")],
                [Assignment("a", "X|CS", "PRIMARY", 60), Assignment("b", "X|CS", "PRIMARY", 60)],
                prev_streak={"a": 6})
    r = solve(p)
    assert r.plan.get("a", date(2026, 12, 1)).status != Status.WORK
    assert not any(c.code == "C07" for c in validate(p, r.plan))


def test_preference_yields_to_coverage():
    # owner prefers Sunday off, but the backup is on leave every Sunday -> coverage wins
    sundays = {("bk", date(2026, 12, 6)): Status.LEAVE, ("bk", date(2026, 12, 13)): Status.LEAVE}
    p = problem([emp("o", preferred_off_weekdays=(6,)), emp("bk")],
                [line("S|CS"), line("S|ACC", MON_SAT, False)],
                [Assignment("o", "S|CS", "PRIMARY", 50), Assignment("o", "S|ACC", "PRIMARY", 50),
                 Assignment("bk", "S|CS", "BACKUP", 50), Assignment("bk", "S|ACC", "BACKUP", 50)],
                leaves=sundays)
    r = solve(p)
    assert not r.gaps
    sunday = date(2026, 12, 6)
    assert r.plan.get("o", sunday).status == Status.WORK
    assert any(c.code == "C09" for c in validate(p, r.plan))


# --------------------------------------------------------------- validator
def test_validator_flags_manual_edits():
    p = problem([emp("a"), emp("b")], [line("V|CS")],
                [Assignment("a", "V|CS", "PRIMARY", 60), Assignment("b", "V|CS", "PRIMARY", 60)],
                leaves={("a", date(2026, 12, 3)): Status.LEAVE})
    plan = solve(p).plan
    plan.cells[("a", date(2026, 12, 3))] = Cell(Status.WORK, {"V|CS": False}, "MANUAL")
    for d in p.days:                     # b works every day: streak + no weekly off
        plan.cells[("b", d)] = Cell(Status.WORK, {"V|CS": False}, "MANUAL")
    codes = {c.code for c in validate(p, plan)}
    assert {"C05", "C06", "C07"} <= codes


# ------------------------------------------------------- change handling
def test_repair_after_leave_changes_few_cells():
    base_p = problem([emp("o"), emp("bk1"), emp("bk2")], [line("K|CS"), line("L|CS", MON_SAT, False)],
                     [Assignment("o", "K|CS", "PRIMARY", 60), Assignment("bk1", "K|CS", "BACKUP", 60),
                      Assignment("bk1", "L|CS", "PRIMARY", 60), Assignment("bk2", "K|CS", "BACKUP", 60),
                      Assignment("bk2", "L|CS", "BACKUP", 60)])
    base = solve(base_p).plan
    leave_day = next(d for d in base_p.days
                     if d.day > 4 and heads_on(base_p, base, "K|CS", d) == ["o"])
    p2 = problem(base_p.employees, base_p.lines, base_p.assignments,
                 leaves={("o", leave_day): Status.LEAVE}, baseline=base,
                 repair_window=(leave_day - timedelta(days=4), leave_day + timedelta(days=4)))
    assert hard(validate(p2, base))                      # the change opens a gap
    sugg = suggest(p2, base, leave_day, ["K|CS"])
    assert sugg and all(s.reasons for s in sugg)        # every candidate explained
    assert any(s.employee_id == "o" and s.verdict == "REJECTED" for s in sugg)
    # single-step fixes may all be blocked (backups at capacity); the repair
    # solver can chain moves (hand L|CS to bk2, free bk1 for K|CS)
    r = solve(p2)
    assert not hard(validate(p2, r.plan))
    changed = diff_plans(base, r.plan)
    assert 1 <= len(changed) <= 6


# ------------------------------------------------------------ sample month
def test_sample_december_is_valid_except_structural_gap(december):
    r = solve(december)
    conflicts = validate(december, r.plan)
    hard_c = hard(conflicts)
    structural = {(s.line_id, s.date) for s in precheck(december)}
    # Priya (Bloom Basket ACC) is on leave 21-23 Dec; her only backup, the East lead,
    # is also away on the 22nd -> exactly one slot no roster can fill
    assert structural == {("Bloom Basket|ACC", date(2026, 12, 22))}
    assert {(c.line_id, c.date) for c in hard_c} == structural
    assert set(r.gaps) == structural
    assert r.wall_ms < 25_000


# ---------------------------------------------------------- optimisation
def test_decomposition_follows_the_assignment_graph(december):
    from app.domain.solver import components
    comps = components(december)
    # North and South are linked by a cross-pod backup (Rahul backs up Kesar Kitchen),
    # East and West stand alone -> three independent models
    assert len(comps) == 3
    for E, L in comps:
        for a in december.assignments:
            assert (a.employee_id in E) == (a.line_id in L)


def test_single_core_still_proves_minimum_coverage_gap():
    """On a one-core host (Render free tier) the weighted model used to return
    16 false gaps after 60 s. Lexicographic phase 1 proves the true minimum."""
    p = build_sample_problem(weights=Weights(time_limit_s=12, workers=1))
    r = solve(p)
    assert r.stats["coverage_proven_optimal"]
    assert set(r.gaps) == {("Bloom Basket|ACC", date(2026, 12, 22))}
    assert len(hard(validate(p, r.plan))) == 1


def test_decomposed_and_whole_model_agree_on_coverage(december):
    from dataclasses import replace
    whole = solve(build_sample_problem(weights=replace(december.weights, decompose=0, time_limit_s=15)))
    parts = solve(build_sample_problem(weights=replace(december.weights, decompose=1, time_limit_s=15)))
    assert set(whole.gaps) == set(parts.gaps)
    assert parts.stats["components"] == 3 and whole.stats["components"] == 1
