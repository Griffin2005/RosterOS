"""Standalone Google Sheets / Drive / Calendar mock (docker service `sheets-mock`).

Run: uvicorn mocks.sheets:app --port 8100
"""
from fastapi import FastAPI

from app.integrations.google_mock import router

app = FastAPI(title="Google APIs mock (Sheets v4, Drive v3, Calendar v3)")
app.include_router(router)
