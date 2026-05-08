"""
Semantic Video Synthesizer — FastAPI Application v0.2.0
Phase 1: Core pipeline with pydantic-settings + structlog + lifespan
"""
from __future__ import annotations

# ── WMI Hang Bypass ───────────────────────────────────────────────────────────
# Python 3.14 platform.system() hangs on Windows when WMI service is stuck.
# We patch it early to return 'Windows' instantly and prevent celery/uvicorn hang.
import platform
import collections
platform.system = lambda: "Windows"
platform.machine = lambda: "AMD64"
platform.release = lambda: "10"
platform.version = lambda: "10.0.19041"
_Uname = collections.namedtuple("uname_result", ["system", "node", "release", "version", "machine", "processor"])
platform.uname = lambda: _Uname("Windows", "DESKTOP", "10", "10.0.19041", "AMD64", "AMD64")
platform.win32_ver = lambda *a, **k: ("10", "10.0.19041", "SP0", "Multiprocessor Free")
# ──────────────────────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager
from pathlib import Path

# ── Increase multipart upload size limit BEFORE starlette processes any request ─
# Starlette 0.38 hard-codes max_file_size = 1 MB in MultiPartParser.
# Patch it to 600 MB so large video uploads pass through to our route handler.
import starlette.formparsers as _fp
_fp.MultiPartParser.max_file_size = 600 * 1024 * 1024   # 600 MB

import redis as redis_lib
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from core.config import settings
from api.routes import video as video_router
from api.routes import query as query_router
from api.routes import ws as ws_router
from services.task_orchestrator import celery_app

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create required directories on startup."""
    logger.info("startup", upload_dir=settings.upload_dir, keyframe_dir=settings.keyframe_dir)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.keyframe_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.faiss_index_path).mkdir(parents=True, exist_ok=True)
    yield
    logger.info("shutdown")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Semantic Video Synthesizer",
    description="Process lecture videos → SSIM keyframes → VLM analysis → RAG knowledge base",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://svs-frontend:3000",   # Docker internal name
        "http://frontend:3000",       # Docker compose service name
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve keyframe images as static files
app.mount(
    "/static/keyframes",
    StaticFiles(directory=settings.keyframe_dir, check_dir=False),
    name="keyframes",
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(video_router.router)
app.include_router(query_router.router)
app.include_router(ws_router.router)


# ── Health ────────────────────────────────────────────────────────────────────

def _redis_ok() -> bool:
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=1)
        return bool(r.ping())
    except Exception:
        return False


def _celery_ok() -> bool:
    try:
        inspect = celery_app.control.inspect(timeout=0.5)
        return inspect.active() is not None
    except Exception:
        return _redis_ok()


@app.get("/health", tags=["Meta"])
async def health() -> dict:
    """Phase 0 quality gate: must return 200 with redis=true."""
    redis_alive = _redis_ok()
    return {
        "status": "ok" if redis_alive else "degraded",
        "redis": redis_alive,
        "celery": _celery_ok() if redis_alive else False,
        "version": "0.2.0",
    }


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse({"message": "Semantic Video Synthesizer API — see /docs"})
