"""In-memory stand-in for Google Sheets v4, Drive v3 (file version) and
Calendar v3 (holiday events).

It implements the same URL shapes and JSON payloads the real APIs use, so the
client in `google.py` talks to it exactly as it would to Google. It can run
in-process (SHEETS_MODE=embedded) or as its own container (mocks/sheets.py).
"""
from __future__ import annotations

import copy
import threading
from datetime import date

from fastapi import APIRouter, Body, HTTPException

from .. import sample_data as S

_lock = threading.Lock()


def _initial() -> dict:
    return {
        "spreadsheets": {
            "rules-and-coverage": {
                "title": "Rules & Coverage",
                "revision": 1,
                "tabs": {
                    "ServiceLines": [S.RULE_SHEET_HEADER] + [list(r) for r in S.RULE_SHEET_ROWS],
                    "CoverageOverrides": [S.OVERRIDE_SHEET_HEADER] + [list(r) for r in S.OVERRIDE_SHEET_ROWS],
                },
            },
            "roster-dashboards": {"title": "Roster dashboards", "revision": 1, "tabs": {}},
        },
        "calendars": {cid: [{"summary": n, "start": {"date": d}, "end": {"date": d}} for d, n in items]
                      for cid, items in S.HOLIDAYS.items()},
    }


STORE = _initial()


def reset() -> None:
    global STORE
    with _lock:
        STORE = _initial()


def _sheet(sid: str) -> dict:
    s = STORE["spreadsheets"].get(sid)
    if s is None:
        raise KeyError(sid)
    return s


# ---- functions used directly in embedded mode ------------------------------
def get_values(sid: str, rng: str) -> list[list[str]]:
    tab = rng.split("!")[0].strip("'")
    with _lock:
        return copy.deepcopy(_sheet(sid)["tabs"].get(tab, []))


def batch_clear(sid: str, ranges: list[str]) -> None:
    with _lock:
        s = _sheet(sid)
        for r in ranges:
            s["tabs"].pop(r.split("!")[0].strip("'"), None)


def batch_update(sid: str, data: list[dict]) -> int:
    with _lock:
        s = _sheet(sid)
        for item in data:
            tab = item["range"].split("!")[0].strip("'")
            s["tabs"][tab] = [[("" if v is None else str(v)) for v in row] for row in item["values"]]
        s["revision"] += 1
        return sum(len(i["values"]) for i in data)


def file_version(sid: str) -> str:
    with _lock:
        return str(_sheet(sid)["revision"])


def calendar_events(cid: str, time_min: str | None, time_max: str | None) -> list[dict]:
    lo = date.fromisoformat(time_min[:10]) if time_min else date.min
    hi = date.fromisoformat(time_max[:10]) if time_max else date.max
    with _lock:
        return [e for e in STORE["calendars"].get(cid, []) if lo <= date.fromisoformat(e["start"]["date"]) <= hi]


def spreadsheet_view(sid: str) -> dict:
    with _lock:
        s = _sheet(sid)
        return {"id": sid, "title": s["title"], "revision": s["revision"], "tabs": copy.deepcopy(s["tabs"])}


# ---- HTTP surface (same paths as Google) -----------------------------------
router = APIRouter()


@router.get("/v4/spreadsheets/{sid}/values/{rng}")
def http_get_values(sid: str, rng: str):
    try:
        return {"range": rng, "majorDimension": "ROWS", "values": get_values(sid, rng)}
    except KeyError:
        raise HTTPException(404, "Requested entity was not found.")


@router.post("/v4/spreadsheets/{sid}/values:batchClear")
def http_batch_clear(sid: str, body: dict = Body(...)):
    batch_clear(sid, body.get("ranges", []))
    return {"spreadsheetId": sid, "clearedRanges": body.get("ranges", [])}


@router.post("/v4/spreadsheets/{sid}/values:batchUpdate")
def http_batch_update(sid: str, body: dict = Body(...)):
    try:
        n = batch_update(sid, body.get("data", []))
    except KeyError:
        raise HTTPException(404, "Requested entity was not found.")
    return {"spreadsheetId": sid, "totalUpdatedRows": n}


@router.get("/drive/v3/files/{sid}")
def http_file(sid: str):
    try:
        return {"id": sid, "version": file_version(sid)}
    except KeyError:
        raise HTTPException(404, "File not found")


@router.get("/calendar/v3/calendars/{cid}/events")
def http_events(cid: str, timeMin: str | None = None, timeMax: str | None = None):
    return {"kind": "calendar#events", "items": calendar_events(cid, timeMin, timeMax)}


# ---- mock-only helpers: let a demo "edit the Google Sheet" -----------------
@router.get("/mock/spreadsheets/{sid}")
def http_view(sid: str):
    try:
        return spreadsheet_view(sid)
    except KeyError:
        raise HTTPException(404, "Not found")


@router.put("/mock/spreadsheets/{sid}/tabs/{tab}")
def http_replace_tab(sid: str, tab: str, rows: list[list[str]] = Body(...)):
    batch_update(sid, [{"range": f"{tab}!A1", "values": rows}])
    return spreadsheet_view(sid)


@router.post("/mock/reset")
def http_reset():
    reset()
    return {"ok": True}
