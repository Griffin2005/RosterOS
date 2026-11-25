from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import assistant, master, rosters
from .config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    from .seed import seed
    if os.getenv("AUTO_SEED", "1") == "1":
        seed()
    yield


app = FastAPI(title="RosterOS API", version="1.0.0", lifespan=lifespan)
s = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(rosters.router)
app.include_router(master.router)
app.include_router(assistant.router)

if s.sheets_mode == "embedded":
    from .integrations.google_mock import router as mock_router
    app.include_router(mock_router, prefix="/mock-google", tags=["google-mock"])


@app.get("/api/health")
def health():
    return {"ok": True, "sheets_mode": s.sheets_mode, "queue": "redis" if s.redis_url else "in-process",
            "assistant": "claude" if s.anthropic_api_key else "offline"}


# Single-container demo: serve the built SPA from the same origin.
STATIC = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC / path
        return FileResponse(f if path and f.is_file() else STATIC / "index.html")
