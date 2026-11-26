"""Formula-driven Excel export.

The workbook is a small linked model, not a dump of values. Master data and
the solver's decisions are stored once; everything derived is a formula that
references them across sheets:

  Employees, Pods, Lines, Assignments   master data (values + lookups)
  Roster        status per person per day: the one sheet meant for editing
  Covers        who the solver put on which line each day; "Counts" checks
                Roster live: =IF(INDEX(RosterGrid, MATCH(code), MATCH(date))="W",1,0)
  Requirements  required heads per line per day (from the rules sheet)
  Coverage      scheduled heads = SUMIFS(Covers) vs Requirements, gaps in red
  Overview      KPIs and pod table computed from the sheets above

Change a "W" to "L" on Roster and Coverage, Pods, Employees and Overview
recalculate, so a planner can test a what-if in Excel before making the change
in RosterOS. Named ranges (RosterGrid, RosterCodes, RosterDates, CoverCounts,
CoverDates, CoverLines) keep the formulas readable. Every text value from the
database goes through safe_cell() so a name like "=HYPERLINK(...)" can never
execute.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as col
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from ..security import safe_cell

GREEN, GREEN_BG, GREY_BG, BLUE_BG, RED_BG, AMBER_BG = "1E5B3E", "DDF0E3", "EEF0EE", "E3EEF7", "FBE7E4", "FBF0DC"
RED = "B23A30"
HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor=GREEN)
THIN = Border(bottom=Side(style="thin", color="E1E7E2"))
DAY_W = 8.4   # wide enough for a bold "Tue 8" header in Excel and LibreOffice
STATUS_CODE = {"WORK": "W", "WEEK_OFF": "WO", "HOLIDAY": "PH", "LEAVE": "L", "COMP_OFF": "CO"}
STATUS_FILL = {"W": GREEN_BG, "WO": GREY_BG, "PH": BLUE_BG, "L": RED_BG, "CO": AMBER_BG}


def cf_fill(hex_: str) -> PatternFill:
    """Conditional-format fills are differential formats: Excel paints a solid
    dxf fill with bgColor, so both colours are set (fgColor alone shows nothing)."""
    return PatternFill(fill_type="solid", fgColor=hex_, bgColor=hex_)


def _header(ws, labels: list, row: int = 1, widths: dict[int, float] | None = None):
    for i, v in enumerate(labels, start=1):
        c = ws.cell(row, i, v)
        c.font, c.fill = HEAD, HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, w in (widths or {}).items():
        ws.column_dimensions[col(i)].width = w
    ws.row_dimensions[row].height = 30


def _name(wb, name: str, ref: str):
    wb.defined_names[name] = DefinedName(name, attr_text=ref)


def build_workbook(g: dict, *, lines_meta: dict[str, dict], exported_by: str, app_url: str = "") -> bytes:
    days = [date.fromisoformat(d) for d in g["days"]]
    D = len(days)
    emps = g["employees"]
    lines = g["coverage"]
    N, L = max(len(emps), 1), max(len(lines), 1)
    pods = {p["id"]: p for p in g["pods"]}
    code_of = {e["id"]: e["code"] for e in emps}
    label_of = {c["line_id"]: c["label"] for c in lines}
    pod_name = lambda pid: pods.get(pid, {}).get("name", pid or "")  # noqa: E731
    r = g["roster"]
    month = days[0]

    wb = Workbook()
    ov = wb.active
    ov.title = "Overview"
    ws_r = wb.create_sheet("Roster")
    ws_cov = wb.create_sheet("Coverage")
    ws_req = wb.create_sheet("Requirements")
    ws_cv = wb.create_sheet("Covers")
    ws_e = wb.create_sheet("Employees")
    ws_p = wb.create_sheet("Pods")
    ws_l = wb.create_sheet("Lines")
    ws_a = wb.create_sheet("Assignments")
    ws_c = wb.create_sheet("Conflicts")
    for ws, color in ((ov, GREEN), (ws_r, "49A36F"), (ws_cov, "49A36F"), (ws_c, RED)):
        ws.sheet_properties.tabColor = color

    # ---------------------------------------------------------- Employees
    _header(ws_e, ["Code", "Employee", "Pod", "Pod lead", "Primary lines", "Backup lines", "Working days",
                   "Leave days"], widths={1: 9, 2: 24, 3: 14, 4: 22, 5: 12, 6: 12, 7: 12, 8: 11})
    for i, e in enumerate(emps, start=2):
        ws_e.cell(i, 1, safe_cell(e["code"]))
        ws_e.cell(i, 2, safe_cell(e["name"]))
        ws_e.cell(i, 3, safe_cell(pod_name(e["pod_id"])))
        ws_e.cell(i, 4, f'=IFERROR(INDEX(Pods!$D:$D,MATCH(C{i},Pods!$B:$B,0)),"")')
        ws_e.cell(i, 5, f'=COUNTIFS(Assignments!$A:$A,A{i},Assignments!$D:$D,"PRIMARY")')
        ws_e.cell(i, 6, f'=COUNTIFS(Assignments!$A:$A,A{i},Assignments!$D:$D,"BACKUP")')
        ws_e.cell(i, 7, f'=COUNTIF(INDEX(RosterGrid,MATCH(A{i},RosterCodes,0),0),"W")')
        ws_e.cell(i, 8, f'=COUNTIF(INDEX(RosterGrid,MATCH(A{i},RosterCodes,0),0),"L")'
                        f'+COUNTIF(INDEX(RosterGrid,MATCH(A{i},RosterCodes,0),0),"CO")')
    ws_e.freeze_panes = "C2"

    # --------------------------------------------------------------- Pods
    used_pods = [p for p in g["pods"] if any(e["pod_id"] == p["id"] for e in emps)]
    _header(ws_p, ["Pod ID", "Pod", "Lead code", "Pod lead", "People", "Working person-days",
                   "Uncovered line-days"], widths={1: 12, 2: 16, 3: 10, 4: 22, 5: 9, 6: 14, 7: 14})
    gap_col = col(4 + D + 2)        # Coverage: uncovered line-days column
    work_col = col(3 + D + 1)       # Roster: working days column
    for i, p in enumerate(used_pods, start=2):
        ws_p.cell(i, 1, safe_cell(p["id"]))
        ws_p.cell(i, 2, safe_cell(p["name"]))
        ws_p.cell(i, 3, safe_cell(code_of.get(p["lead_id"], "")))
        ws_p.cell(i, 4, f'=IFERROR(INDEX(Employees!$B:$B,MATCH(C{i},Employees!$A:$A,0)),"(outside scope)")')
        ws_p.cell(i, 5, f"=COUNTIF(Employees!$C:$C,B{i})")
        ws_p.cell(i, 6, f"=SUMIF(Roster!$C:$C,B{i},Roster!${work_col}:${work_col})")
        ws_p.cell(i, 7, f"=SUMIF(Coverage!$D:$D,B{i},Coverage!${gap_col}:${gap_col})")

    # -------------------------------------------------------------- Lines
    _header(ws_l, ["Line", "Brand", "Process", "Pod", "Calendar", "Min heads", "Shift", "Primary staff",
                   "Trained backups", "Single-resource", "Uncovered days"],
            widths={1: 28, 2: 20, 3: 9, 4: 13, 5: 14, 6: 10, 7: 13, 8: 12, 9: 12, 10: 13, 11: 13})
    for i, c in enumerate(lines, start=2):
        meta = lines_meta.get(c["line_id"], {})
        ws_l.cell(i, 1, safe_cell(c["label"]))
        ws_l.cell(i, 2, safe_cell(c["brand"]))
        ws_l.cell(i, 3, safe_cell(c["process"]))
        ws_l.cell(i, 4, safe_cell(pod_name(c["pod_id"])))
        ws_l.cell(i, 5, safe_cell(c["calendar"].replace("_", " ").title()))
        ws_l.cell(i, 6, meta.get("min_heads"))
        ws_l.cell(i, 7, safe_cell(meta.get("shift", "")))
        ws_l.cell(i, 8, f'=COUNTIFS(Assignments!$B:$B,A{i},Assignments!$D:$D,"PRIMARY")')
        ws_l.cell(i, 9, f'=COUNTIFS(Assignments!$B:$B,A{i},Assignments!$D:$D,"BACKUP")')
        ws_l.cell(i, 10, f'=IF(H{i}=1,"Yes","No")')
        ws_l.cell(i, 11, f"=IFERROR(INDEX(Coverage!${gap_col}:${gap_col},MATCH(A{i},Coverage!$A:$A,0)),0)")
    ws_l.freeze_panes = "B2"

    # -------------------------------------------------------- Assignments
    _header(ws_a, ["Employee code", "Line", "Employee", "Role", "Load %"], widths={1: 12, 2: 28, 3: 24, 4: 10, 5: 9})
    row = 2
    for c in lines:
        for a in c["assignees"]:
            if a["employee_id"] not in code_of:
                continue
            ws_a.cell(row, 1, safe_cell(code_of[a["employee_id"]]))
            ws_a.cell(row, 2, safe_cell(c["label"]))
            ws_a.cell(row, 3, f'=IFERROR(INDEX(Employees!$B:$B,MATCH(A{row},Employees!$A:$A,0)),"")')
            ws_a.cell(row, 4, a["role"])
            ws_a.cell(row, 5, a["load"])
            row += 1

    # ------------------------------------------------------------- Roster
    last = col(3 + D)
    _header(ws_r, ["Code", "Employee", "Pod"] + days + ["Working", "Weekly offs", "Leave / comp-off",
                                                       "Holidays", "Sundays worked"],
            widths={1: 8, 2: 22, 3: 13})
    hol = set(g.get("holidays", []))
    for j, d in enumerate(days):
        c = ws_r.cell(1, 4 + j)
        c.number_format = "ddd d"
        ws_r.column_dimensions[col(4 + j)].width = DAY_W
        if d.isoformat() in hol:
            c.fill = PatternFill("solid", fgColor="2F5E86")
        elif d.weekday() >= 5:
            c.fill = PatternFill("solid", fgColor="2A7A4F")
    for k in range(5):
        ws_r.column_dimensions[col(4 + D + k)].width = 11
    for i, e in enumerate(emps, start=2):
        ws_r.cell(i, 1, safe_cell(e["code"]))
        ws_r.cell(i, 2, f'=IFERROR(INDEX(Employees!$B:$B,MATCH($A{i},Employees!$A:$A,0)),"")')
        ws_r.cell(i, 3, f'=IFERROR(INDEX(Employees!$C:$C,MATCH($A{i},Employees!$A:$A,0)),"")')
        for j, cell in enumerate(e["cells"]):
            x = ws_r.cell(i, 4 + j, STATUS_CODE[cell["status"]] if cell else "")
            x.alignment = Alignment(horizontal="center")
        rng = f"D{i}:{last}{i}"
        ws_r.cell(i, 4 + D, f'=COUNTIF({rng},"W")')
        ws_r.cell(i, 5 + D, f'=COUNTIF({rng},"WO")')
        ws_r.cell(i, 6 + D, f'=COUNTIF({rng},"L")+COUNTIF({rng},"CO")')
        ws_r.cell(i, 7 + D, f'=COUNTIF({rng},"PH")')
        ws_r.cell(i, 8 + D, f'=SUMPRODUCT((WEEKDAY($D$1:${last}$1,2)=7)*({rng}="W"))')
    grid = f"Roster!$D$2:${last}${N + 1}"
    _name(wb, "RosterGrid", grid)
    _name(wb, "RosterCodes", f"Roster!$A$2:$A${N + 1}")
    _name(wb, "RosterDates", f"Roster!$D$1:${last}$1")
    dv = DataValidation(type="list", formula1='"W,WO,PH,L,CO"', allow_blank=True, showErrorMessage=True,
                        errorTitle="Status code", error="Use W, WO, PH, L or CO.")
    dv.prompt, dv.promptTitle = "W work · WO weekly off · PH holiday · L leave · CO comp-off", "Status"
    ws_r.add_data_validation(dv)
    dv.add(f"D2:{last}{N + 1}")
    for code, fill in STATUS_FILL.items():
        ws_r.conditional_formatting.add(f"D2:{last}{N + 1}", CellIsRule(
            operator="equal", formula=[f'"{code}"'], fill=cf_fill(fill)))
    ws_r.freeze_panes = "D2"

    # ------------------------------------------------------------- Covers
    _header(ws_cv, ["Date", "Line", "Code", "Employee", "As", "Counts (status still W?)"],
            widths={1: 12, 2: 28, 3: 8, 4: 22, 5: 9, 6: 16})
    row = 2
    for e in emps:
        for j, cell in enumerate(e["cells"]):
            if not cell or cell["status"] != "WORK":
                continue
            for line_id, as_backup in cell["covers"].items():
                if line_id not in label_of:
                    continue
                ws_cv.cell(row, 1, days[j]).number_format = "yyyy-mm-dd"
                ws_cv.cell(row, 2, safe_cell(label_of[line_id]))
                ws_cv.cell(row, 3, safe_cell(e["code"]))
                ws_cv.cell(row, 4, f'=IFERROR(INDEX(Employees!$B:$B,MATCH(C{row},Employees!$A:$A,0)),"")')
                ws_cv.cell(row, 5, "Backup" if as_backup else "Primary")
                ws_cv.cell(row, 6, f'=IF(INDEX(RosterGrid,MATCH(C{row},RosterCodes,0),'
                                   f'MATCH(A{row},RosterDates,0))="W",1,0)')
                row += 1
    M = max(row - 1, 2)
    _name(wb, "CoverDates", f"Covers!$A$2:$A${M}")
    _name(wb, "CoverLines", f"Covers!$B$2:$B${M}")
    _name(wb, "CoverCounts", f"Covers!$F$2:$F${M}")
    ws_cv.freeze_panes = "A2"
    ws_cv.auto_filter.ref = f"A1:F{M}"

    # ------------------------------------------- Requirements and Coverage
    dlast = col(4 + D)
    for ws, title in ((ws_req, "Required heads"), (ws_cov, "Scheduled heads")):
        extra = ["Required line-days", "Uncovered line-days", "Missing heads"] if ws is ws_cov else []
        _header(ws, ["Line", "Brand", "Process", "Pod"] + days + extra, widths={1: 28, 2: 18, 3: 8, 4: 12})
        for j in range(D):
            ws.cell(1, 5 + j).number_format = "ddd d"
            ws.column_dimensions[col(5 + j)].width = DAY_W
        for k in range(len(extra)):
            ws.column_dimensions[col(5 + D + k)].width = 12
        ws.freeze_panes = "E2"
    for i, c in enumerate(lines, start=2):
        for ws in (ws_req, ws_cov):
            ws.cell(i, 1, safe_cell(c["label"]))
            ws.cell(i, 2, safe_cell(c["brand"]))
            ws.cell(i, 3, safe_cell(c["process"]))
            ws.cell(i, 4, safe_cell(pod_name(c["pod_id"])))
        for j, dd in enumerate(c["days"]):
            ws_req.cell(i, 5 + j, dd["req"]).alignment = Alignment(horizontal="center")
            x = ws_cov.cell(i, 5 + j, f"=SUMIFS(CoverCounts,CoverDates,{col(5 + j)}$1,CoverLines,$A{i})")
            x.alignment = Alignment(horizontal="center")
        rq, sc = f"Requirements!E{i}:{dlast}{i}", f"E{i}:{dlast}{i}"
        ws_cov.cell(i, 5 + D, f'=COUNTIF({rq},">0")')
        ws_cov.cell(i, 6 + D, f"=SUMPRODUCT(({rq}>0)*({sc}<{rq}))")
        ws_cov.cell(i, 7 + D, f"=SUMPRODUCT(({rq}>{sc})*({rq}-{sc}))")
    area = f"E2:{dlast}{L + 1}"
    ws_cov.conditional_formatting.add(area, FormulaRule(
        formula=["AND(Requirements!E2>0,E2<Requirements!E2)"],
        fill=cf_fill(RED_BG), font=Font(bold=True, color=RED), stopIfTrue=True))
    ws_cov.conditional_formatting.add(area, FormulaRule(
        formula=["Requirements!E2=0"], font=Font(color="BFC8C1"), stopIfTrue=True))
    ws_cov.conditional_formatting.add(area, FormulaRule(
        formula=["E2>=Requirements!E2"], fill=cf_fill(GREEN_BG)))
    ws_cov.conditional_formatting.add(f"{col(6 + D)}2:{col(6 + D)}{L + 1}", CellIsRule(
        operator="greaterThan", formula=["0"], fill=cf_fill(RED_BG), font=Font(color=RED)))
    ws_req.conditional_formatting.add(f"E2:{dlast}{L + 1}", CellIsRule(
        operator="equal", formula=["0"], font=Font(color="BFC8C1")))

    # ---------------------------------------------------------- Conflicts
    _header(ws_c, ["Severity", "Code", "Title", "Date", "Line", "Employee", "Detail", "Acknowledged"],
            widths={1: 10, 2: 7, 3: 34, 4: 12, 5: 26, 6: 20, 7: 60, 8: 40})
    names = {e["id"]: e["name"] for e in emps}
    order = {"HARD": 0, "SOFT": 1, "INFO": 2}
    for i, c in enumerate(sorted(g["conflicts"], key=lambda c: (order.get(c["severity"], 3), c.get("date") or "")),
                          start=2):
        ack = c.get("acknowledged")
        vals = [c["severity"], c["code"], c["title"], c.get("date") or "", label_of.get(c.get("line_id"), ""),
                names.get(c.get("employee_id"), ""), c["detail"], f'{ack["reason"]} ({ack["by"]})' if ack else ""]
        for k, v in enumerate(vals, start=1):
            ws_c.cell(i, k, safe_cell(v)).alignment = Alignment(vertical="top", wrap_text=k in (3, 7, 8))
        if c["severity"] == "HARD":
            ws_c.cell(i, 1).font = Font(bold=True, color=RED)
    ws_c.freeze_panes = "A2"

    # ----------------------------------------------------------- Overview
    ov.column_dimensions["A"].width = 30
    ov.column_dimensions["B"].width = 22
    ov.column_dimensions["C"].width = 60
    ov["A1"] = f"RosterOS · {month:%B %Y} roster · v{r['version']} ({r['status'].lower()})"
    ov["A1"].font = Font(bold=True, size=16, color=GREEN)
    meta = [("Exported", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
            ("Exported by", safe_cell(exported_by)),
            ("Scope", "Filtered to the exporter's scope" if g.get("scoped") else "Whole company"),
            ("Rule set", f"v{r.get('rule_set_version') or '-'} (imported from the rules Google Sheet)"),
            ("Note", safe_cell(r.get("note") or ""))]
    for k, (a, b) in enumerate(meta, start=3):
        ov.cell(k, 1, a).font = Font(color="56655B")
        ov.cell(k, 2, b)
    ov["A9"] = "Live figures (recalculate when you edit the Roster sheet)"
    ov["A9"].font = Font(bold=True, size=12)
    kpis = [
        ("Employees", "=COUNTA(Employees!A2:A{n})".format(n=N + 1), "0", "Employees sheet"),
        ("Service lines (brand × process)", f"=COUNTA(Lines!A2:A{L + 1})", "0", "Lines sheet"),
        ("Required line-days", f"=SUM(Coverage!{col(5 + D)}2:{col(5 + D)}{L + 1})", "0",
         "Requirements sheet: days each line must be staffed"),
        ("Uncovered line-days", f"=SUM(Coverage!{gap_col}2:{gap_col}{L + 1})", "0",
         "Coverage sheet: scheduled heads below required"),
        ("Coverage", "=IF(B12=0,1,1-B13/B12)", "0.0%", "1 - uncovered / required"),
        ("Working person-days", '=COUNTIF(RosterGrid,"W")', "0", "Roster sheet"),
        ("Leave and comp-off days", '=COUNTIF(RosterGrid,"L")+COUNTIF(RosterGrid,"CO")', "0", "Roster sheet"),
        ("Hard conflicts at export", f'=COUNTIF(Conflicts!A2:A{max(len(g["conflicts"]), 1) + 1},"HARD")', "0",
         "Conflicts sheet (validator snapshot, does not recalculate)"),
    ]
    for k, (label, formula, fmt, src) in enumerate(kpis, start=10):
        ov.cell(k, 1, label)
        x = ov.cell(k, 2, formula)
        x.number_format, x.font = fmt, Font(bold=True, size=12)
        ov.cell(k, 3, src).font = Font(color="8A978E", italic=True)
        for c_ in (1, 2, 3):
            ov.cell(k, c_).border = THIN
    ov.conditional_formatting.add("B13", CellIsRule(operator="greaterThan", formula=["0"],
                                                    font=Font(bold=True, size=12, color=RED)))
    ov["A20"] = "Sheets"
    ov["A20"].font = Font(bold=True, size=12)
    guide = [("Roster", "Status per person per day. Edit codes here (W, WO, PH, L, CO)."),
             ("Coverage", "Scheduled vs required heads per line per day. Red = gap."),
             ("Requirements", "Required heads from the brand/process rules."),
             ("Covers", "Who the solver assigned to each line, and whether they still count."),
             ("Employees", "People, pod, pod lead and live day counts."),
             ("Pods", "Pod lead, headcount, working days and gaps per pod."),
             ("Lines", "Rules per brand and process, staffing depth, single-resource flag."),
             ("Assignments", "Who is trained on which line, as primary or backup."),
             ("Conflicts", "Validator findings at export time.")]
    for k, (sheet, text) in enumerate(guide, start=21):
        ov.cell(k, 1, f'=HYPERLINK("#\'{sheet}\'!A1","{sheet} →")').font = Font(color=GREEN, underline="single")
        ov.cell(k, 2, text)
        ov.merge_cells(start_row=k, start_column=2, end_row=k, end_column=3)
    if app_url:
        ov["A31"] = f'=HYPERLINK("{app_url}/roster","Open this roster in RosterOS")'
        ov["A32"] = f'=HYPERLINK("{app_url}/sheets","Open the rules Google Sheet view")'
        for ref in ("A31", "A32"):
            ov[ref].font = Font(color=GREEN, underline="single")

    # read-only by intent: derived sheets are protected (no password; it stops
    # accidental overwrites of formulas, it is not access control)
    for ws in (ov, ws_cov, ws_req):
        ws.protection.sheet = True
        ws.protection.formatCells = False
        ws.protection.formatColumns = False
    wb.properties.creator = "RosterOS"
    wb.properties.title = f"Roster {month:%Y-%m} v{r['version']}"
    wb.calculation.fullCalcOnLoad = True
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
