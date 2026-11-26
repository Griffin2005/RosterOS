from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import account, assistant, master, rosters
from .config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    from .bootstrap import bootstrap_credentials, check_production_config
    from .seed import seed
    check_production_config()
    if os.getenv("AUTO_SEED", "1") == "1":
        seed()
    else:
        from .db import init_db
        init_db()
    bootstrap_credentials()
    yield


s = get_settings()
app = FastAPI(title="RosterOS API", version="1.1.0", lifespan=lifespan,
              # interactive API docs are a map for attackers; keep them to development
              docs_url=None if s.production else "/docs", redoc_url=None,
              openapi_url=None if s.production else "/openapi.json")

CSP = ("default-src 'self'; script-src 'self'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
       "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Content-Security-Policy"] = CSP
    if request.url.scheme == "https":
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    path = request.url.path
    if path.startswith("/api/"):
        h["Cache-Control"] = "no-store"           # personal data never sits in a shared cache
    elif path.startswith("/assets/"):
        h["Cache-Control"] = "public, max-age=31536000, immutable"   # content-hashed file names
    else:
        h["Cache-Control"] = "no-cache"
    return resp


app.add_middleware(GZipMiddleware, minimum_size=1024)   # the month grid JSON shrinks ~10x
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"])

app.include_router(account.router)
app.include_router(rosters.router)
app.include_router(master.router)
app.include_router(assistant.router)

if s.sheets_mode == "embedded":
    # The app talks to the embedded mock in-process; this HTTP surface exists
    # for inspection only, so it sits behind the same manager-only check as
    # the rules import (it can rewrite the rules sheet).
    from fastapi import Depends

    from .auth import MANAGE, require
    from .integrations.google_mock import router as mock_router
    app.include_router(mock_router, prefix="/mock-google", tags=["google-mock"],
                       dependencies=[Depends(require(MANAGE))])


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
        # unknown API routes (and the docs, when disabled) are 404s, not the app shell
        if path.startswith(("api/", "mock-google/")) or path in ("docs", "redoc", "openapi.json"):
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        f = (STATIC / path).resolve()
        inside = STATIC.resolve() in f.parents
        return FileResponse(f if path and inside and f.is_file() else STATIC / "index.html")
