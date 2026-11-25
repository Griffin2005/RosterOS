"""Parse and validate rows from the Google Sheet "Rules & Coverage".

Pure functions: rows in, typed rules + row-level errors out. Errors become C11
RULE_IMPORT conflicts with sheet cell references; a bad row never silently
replaces a good rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .calendar import parse_shift
from .types import CALENDAR_PRESETS, WEEKDAY_NAMES

DAY_INDEX = {n.lower(): i for i, n in enumerate(WEEKDAY_NAMES)}


@dataclass
class LineRule:
    brand: str
    process: str
    calendar_kind: str
    weekday_mask: int
    works_ph: bool
    min_heads: int
    weekday_min: dict[int, int] = field(default_factory=dict)
    shift_start: int = 540
    shift_end: int = 1080


@dataclass
class OverrideRule:
    brand: str
    process: str
    on_date: date
    min_heads: int
    reason: str


@dataclass
class RowError:
    tab: str
    row: int        # 1-based sheet row (header is row 1)
    column: str
    message: str

    @property
    def cell(self) -> str:
        return f"{self.tab}!{self.column}{self.row}"


def _mask_from_days(text: str) -> int:
    """'Mon-Fri' or 'Mon,Wed,Fri' -> weekday bitmask."""
    mask = 0
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            ia, ib = DAY_INDEX[a[:3].lower()], DAY_INDEX[b[:3].lower()]
            for i in range(ia, ib + 1):
                mask |= 1 << i
        else:
            mask |= 1 << DAY_INDEX[part[:3].lower()]
    return mask


def _parse_weekday_min(text: str) -> dict[int, int]:
    out = {}
    for part in text.replace(" ", "").split(";"):
        if not part:
            continue
        k, v = part.split(":")
        out[DAY_INDEX[k[:3].lower()]] = int(v)
    return out


COLS = "ABCDEFGHIJ"


def parse_service_lines(header: list[str], rows: list[list[str]]) -> tuple[list[LineRule], list[RowError]]:
    idx = {h.strip().lower(): i for i, h in enumerate(header)}
    rules: list[LineRule] = []
    errors: list[RowError] = []
    seen: set[tuple[str, str]] = set()

    def col(name: str) -> str:
        return COLS[idx[name]] if name in idx else "?"

    for n, row in enumerate(rows, start=2):
        get = lambda k: (row[idx[k]].strip() if k in idx and idx[k] < len(row) else "")
        brand, process, kind = get("brand"), get("process").upper(), get("calendar").upper()
        if not brand and not process:
            continue
        if not brand:
            errors.append(RowError("ServiceLines", n, col("brand"), "Brand is empty"))
            continue
        if not process:
            errors.append(RowError("ServiceLines", n, col("process"), "Process is empty"))
            continue
        if (brand.lower(), process) in seen:
            errors.append(RowError("ServiceLines", n, col("brand"), f"Duplicate row for {brand} · {process}"))
            continue
        try:
            if kind in CALENDAR_PRESETS:
                mask, works_ph = CALENDAR_PRESETS[kind]
            elif kind == "CUSTOM":
                mask = _mask_from_days(get("weekdays"))
                works_ph = False
                if mask == 0:
                    raise ValueError
            else:
                errors.append(RowError("ServiceLines", n, col("calendar"),
                                       f"Unknown calendar '{kind}'. Use ALL_DAYS, NO_PH, NO_SUN_PH or CUSTOM"))
                continue
        except (ValueError, KeyError):
            errors.append(RowError("ServiceLines", n, col("weekdays"), "CUSTOM calendar needs weekdays like Mon-Fri"))
            continue
        try:
            heads = int(get("min_heads") or "1")
            if heads < 0:
                raise ValueError
        except ValueError:
            errors.append(RowError("ServiceLines", n, col("min_heads"), "min_heads must be a whole number ≥ 0"))
            continue
        try:
            wmin = _parse_weekday_min(get("weekday_min"))
        except (ValueError, KeyError):
            errors.append(RowError("ServiceLines", n, col("weekday_min"), "Use the form Sat:2;Sun:2"))
            continue
        try:
            s, e = parse_shift(get("shift") or "09:00-18:00")
            if e <= s:
                raise ValueError
        except ValueError:
            errors.append(RowError("ServiceLines", n, col("shift"), "Shift must look like 09:30-18:30"))
            continue
        seen.add((brand.lower(), process))
        rules.append(LineRule(brand, process, kind, mask, works_ph, heads, wmin, s, e))
    return rules, errors


def parse_overrides(header: list[str], rows: list[list[str]]) -> tuple[list[OverrideRule], list[RowError]]:
    idx = {h.strip().lower(): i for i, h in enumerate(header)}
    out, errors = [], []
    for n, row in enumerate(rows, start=2):
        get = lambda k: (row[idx[k]].strip() if k in idx and idx[k] < len(row) else "")
        if not any(c.strip() for c in row):
            continue
        try:
            d = date.fromisoformat(get("date"))
        except ValueError:
            errors.append(RowError("CoverageOverrides", n, "C", "Date must be YYYY-MM-DD"))
            continue
        try:
            heads = int(get("min_heads"))
            if heads < 0:
                raise ValueError
        except ValueError:
            errors.append(RowError("CoverageOverrides", n, "D", "min_heads must be a whole number ≥ 0"))
            continue
        out.append(OverrideRule(get("brand"), get("process").upper(), d, heads, get("reason")))
    return out, errors
