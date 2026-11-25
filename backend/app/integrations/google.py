"""Google Sheets / Drive / Calendar client.

One interface, two transports:
  * EmbeddedGoogle - calls the in-process mock store (local dev, tests).
  * HttpGoogle     - real HTTP. Points at the sheets-mock container in docker,
                     or at googleapis.com with a bearer token in production
                     (token from Workload Identity Federation; see docs).
"""
from __future__ import annotations

from datetime import date
from typing import Protocol

import httpx

from ..config import get_settings
from . import google_mock


class GoogleClient(Protocol):
    def get_values(self, sid: str, rng: str) -> list[list[str]]: ...
    def replace_tabs(self, sid: str, tabs: dict[str, list[list[str]]]) -> int: ...
    def file_version(self, sid: str) -> str: ...
    def holidays(self, cid: str, start: date, end: date) -> list[tuple[date, str]]: ...


class EmbeddedGoogle:
    def get_values(self, sid, rng):
        return google_mock.get_values(sid, rng)

    def replace_tabs(self, sid, tabs):
        google_mock.batch_clear(sid, [f"{t}!A:Z" for t in tabs])
        return google_mock.batch_update(sid, [{"range": f"{t}!A1", "values": v} for t, v in tabs.items()])

    def file_version(self, sid):
        return google_mock.file_version(sid)

    def holidays(self, cid, start, end):
        return [(date.fromisoformat(e["start"]["date"]), e["summary"])
                for e in google_mock.calendar_events(cid, start.isoformat(), end.isoformat())]


class HttpGoogle:
    def __init__(self, base_url: str, token: str | None):
        real = "googleapis.com" in base_url
        self.sheets = "https://sheets.googleapis.com" if real else base_url.rstrip("/")
        self.drive = "https://www.googleapis.com" if real else base_url.rstrip("/")
        self.cal = "https://www.googleapis.com" if real else base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(timeout=15, headers=headers)

    def get_values(self, sid, rng):
        r = self.http.get(f"{self.sheets}/v4/spreadsheets/{sid}/values/{rng}")
        r.raise_for_status()
        return r.json().get("values", [])

    def replace_tabs(self, sid, tabs):
        self.http.post(f"{self.sheets}/v4/spreadsheets/{sid}/values:batchClear",
                       json={"ranges": [f"{t}!A:Z" for t in tabs]}).raise_for_status()
        r = self.http.post(f"{self.sheets}/v4/spreadsheets/{sid}/values:batchUpdate",
                           json={"valueInputOption": "RAW",
                                 "data": [{"range": f"{t}!A1", "values": v} for t, v in tabs.items()]})
        r.raise_for_status()
        return r.json().get("totalUpdatedRows", 0)

    def file_version(self, sid):
        r = self.http.get(f"{self.drive}/drive/v3/files/{sid}", params={"fields": "version"})
        r.raise_for_status()
        return str(r.json()["version"])

    def holidays(self, cid, start, end):
        r = self.http.get(f"{self.cal}/calendar/v3/calendars/{cid}/events",
                          params={"timeMin": f"{start}T00:00:00Z", "timeMax": f"{end}T23:59:59Z",
                                  "singleEvents": "true"})
        r.raise_for_status()
        return [(date.fromisoformat(e["start"]["date"]), e.get("summary", "Holiday"))
                for e in r.json().get("items", []) if "date" in e.get("start", {})]


_client: GoogleClient | None = None


def google() -> GoogleClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = EmbeddedGoogle() if s.sheets_mode == "embedded" else HttpGoogle(s.sheets_base_url, s.google_access_token)
    return _client
