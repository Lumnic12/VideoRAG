"""
Video processing routes.

POST /api/v1/upload  (alias: /api/v1/process) — upload video, enqueue pipeline
GET  /api/v1/jobs/{job_id}    — legacy polling endpoint
GET  /api/v1/tasks/{job_id}   — frontend polling endpoint
GET  /api/v1/keyframes/{job_id} — list extracted keyframe images for a job
GET  /api/v1/health           — prefixed health check for frontend
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import aiofiles
import structlog
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from core.config import settings
from models.schemas import JobStatusResponse, ProcessResponse, KeyframeInfo
from services.task_orchestrator import process_video_task, redis_client

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["video"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


# ── Upload / Process ───────────────────────────────────────────────────────────

async def _handle_upload(video: UploadFile) -> ProcessResponse:
    """Shared logic for both /upload and /process endpoints."""
    ext = Path(video.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format '{ext}'. Use: {ALLOWED_EXTENSIONS}")

    job_id = str(uuid.uuid4())
    save_path = Path(settings.upload_dir) / f"{job_id}{ext}"

    # Stream-write to disk in 1 MB chunks — avoids Starlette's 1 MB in-memory cap
    size_bytes = 0
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    async with aiofiles.open(save_path, "wb") as f:
        while True:
            chunk = await video.read(1024 * 1024)  # 1 MB at a time
            if not chunk:
                break
            size_bytes += len(chunk)
            if size_bytes > max_bytes:
                save_path.unlink(missing_ok=True)
                raise HTTPException(
                    413, f"File too large (> {settings.max_upload_size_mb} MB)"
                )
            await f.write(chunk)
    size_mb = size_bytes / 1024 / 1024

    logger.info("video_uploaded", job_id=job_id, filename=video.filename, size_mb=round(size_mb, 2))

    # Initialise job state in Redis immediately
    redis_client.set(
        f"job:{job_id}",
        json.dumps({"status": "queued", "progress": 0}),
        ex=3600,
    )

    # Enqueue Celery task — fallback to thread if Celery is unavailable
    try:
        process_video_task.delay(job_id, str(save_path))
    except Exception as e:
        logger.warning("celery_unavailable_running_sync", error=str(e))
        import threading
        threading.Thread(
            target=process_video_task,
            args=(job_id, str(save_path)),
            daemon=True,
        ).start()

    return ProcessResponse(task_id=job_id, status="queued")


@router.post("/upload", response_model=ProcessResponse)
async def upload_video(video: UploadFile = File(...)) -> ProcessResponse:
    """
    Accept a video upload (field name: 'video'), save to UPLOAD_DIR,
    dispatch Celery pipeline task.

    Returns task_id for polling via GET /api/v1/tasks/{task_id}.
    """
    return await _handle_upload(video)


@router.post("/process", response_model=ProcessResponse)
async def process_video(video: UploadFile = File(...)) -> ProcessResponse:
    """Alias for /upload — kept for API compatibility."""
    return await _handle_upload(video)


# ── Job / Task Status ──────────────────────────────────────────────────────────

def _read_job(job_id: str) -> dict:
    raw = redis_client.get(f"job:{job_id}")
    if not raw:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return json.loads(raw)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Legacy polling endpoint."""
    data = _read_job(job_id)
    return JobStatusResponse(
        task_id=job_id,
        status=data.get("status", "processing"),
        progress=data.get("progress", 0),
        result=data.get("result"),
        error=data.get("error"),
        keyframe_count=data.get("keyframe_count"),
    )


@router.get("/tasks/{job_id}", response_model=JobStatusResponse)
async def get_task_status(job_id: str) -> JobStatusResponse:
    """Frontend polling endpoint — identical to /jobs/{job_id}."""
    data = _read_job(job_id)
    return JobStatusResponse(
        task_id=job_id,
        status=data.get("status", "processing"),
        progress=data.get("progress", 0),
        result=data.get("result"),
        error=data.get("error"),
        keyframe_count=data.get("keyframe_count"),
    )


# ── Keyframes ─────────────────────────────────────────────────────────────────

@router.get("/keyframes/{job_id}", response_model=list[KeyframeInfo])
async def get_keyframes(job_id: str) -> list[KeyframeInfo]:
    """
    Return list of extracted keyframe metadata for a completed job.
    Images are served from /static/keyframes/{job_id}/.
    """
    kf_dir = Path(settings.keyframe_dir) / job_id
    if not kf_dir.exists():
        raise HTTPException(404, f"No keyframes found for job '{job_id}'")

    frames: list[KeyframeInfo] = []
    for i, img_path in enumerate(sorted(kf_dir.glob("kf_*.jpg"))):
        # Parse timestamp from filename: kf_000_0.0s.jpg
        name = img_path.stem  # e.g. kf_000_0.0s
        parts = name.split("_")
        try:
            ts = float(parts[2].rstrip("s"))
        except (IndexError, ValueError):
            ts = 0.0

        frames.append(KeyframeInfo(
            index=i,
            frame_number=i,
            timestamp_sec=ts,
            ssim_delta=0.0,
            image_url=f"/static/keyframes/{job_id}/{img_path.name}",
        ))

    return frames


# ── Health (prefixed) ─────────────────────────────────────────────────────────

@router.get("/health", tags=["Meta"])
async def api_health() -> JSONResponse:
    """Prefixed health check — frontend polls this endpoint."""
    import redis as redis_lib
    from core.config import settings as cfg

    def _redis_ok() -> bool:
        try:
            r = redis_lib.from_url(cfg.redis_url, socket_connect_timeout=1)
            return bool(r.ping())
        except Exception:
            return False

    def _celery_ok() -> bool:
        try:
            from services.task_orchestrator import celery_app
            pings = celery_app.control.ping(timeout=0.5)
            return len(pings) > 0
        except Exception:
            return False

    redis_alive = _redis_ok()
    celery_alive = _celery_ok() if redis_alive else False

    return JSONResponse({
        "status": "ok" if redis_alive else "degraded",
        "redis": redis_alive,
        "celery": celery_alive,
        "version": "0.2.0",
    })


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", tags=["Meta"])
async def get_stats() -> JSONResponse:
    """
    Return real usage stats from Redis + filesystem.
    Frontend Home dashboard polls this every 30s.
    """
    # Count completed jobs (status: done) from Redis scan
    kf_base = Path(settings.keyframe_dir)
    videos_indexed = 0
    keyframes_total = 0
    jobs_in_progress = 0

    try:
        for key in redis_client.scan_iter("job:*"):
            raw = redis_client.get(key)
            if not raw:
                continue
            import json as _json
            job = _json.loads(raw)
            status = job.get("status", "")
            if status == "done":
                videos_indexed += 1
                keyframes_total += job.get("keyframe_count", 0)
            elif status in ("queued", "processing"):
                jobs_in_progress += 1
    except Exception:
        pass

    # Fallback: count keyframe dirs on disk if Redis is empty
    if videos_indexed == 0 and kf_base.exists():
        job_dirs = [d for d in kf_base.iterdir() if d.is_dir()]
        videos_indexed = len(job_dirs)
        keyframes_total = sum(len(list(d.glob("kf_*.jpg"))) for d in job_dirs)

    return JSONResponse({
        "videos_indexed": videos_indexed,
        "keyframes_extracted": keyframes_total,
        "jobs_in_progress": jobs_in_progress,
    })

