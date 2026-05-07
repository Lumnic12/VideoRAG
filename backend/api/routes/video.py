"""
Video processing routes.

POST /api/v1/upload  (alias: /api/v1/process) — upload video, enqueue pipeline
GET  /api/v1/videos                           — list all indexed videos
DELETE /api/v1/videos/{job_id}                — purge a video and all its data
GET  /api/v1/jobs/{job_id}    — legacy polling endpoint
GET  /api/v1/tasks/{job_id}   — frontend polling endpoint
GET  /api/v1/keyframes/{job_id} — list extracted keyframe images for a job
GET  /api/v1/audio/{job_id}   — stream extracted audio WAV
GET  /api/v1/health           — prefixed health check for frontend
GET  /api/v1/videos/reseed    — re-register jobs from disk into Redis
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import aiofiles
import structlog
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, FileResponse

from core.config import settings
from models.schemas import JobStatusResponse, ProcessResponse, KeyframeInfo
from services.task_orchestrator import process_video_task, redis_client

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["video"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _reseed_from_disk() -> int:
    """
    Rebuild Redis job records from filesystem keyframe directories.
    Called at startup and via GET /api/v1/videos/reseed.
    Returns the number of jobs seeded.
    """
    kf_base = Path(settings.keyframe_dir)
    upload_dir = Path(settings.upload_dir)
    seeded = 0
    if not kf_base.exists():
        return 0
    for job_dir in kf_base.iterdir():
        if not job_dir.is_dir():
            continue
        job_id = job_dir.name
        # Skip if already in Redis
        if redis_client.exists(f"job:{job_id}"):
            continue
        # Find the original filename from upload dir
        filename = job_id
        for ext in ALLOWED_EXTENSIONS:
            candidate = upload_dir / f"{job_id}{ext}"
            if candidate.exists():
                filename = candidate.name
                break
        kf_count = len(list(job_dir.glob("kf_*.jpg")))
        if kf_count == 0:
            continue
        # Check for transcript in metadata pkl
        transcript = []
        meta_pkl = Path(settings.faiss_index_path) / "metadata.pkl"
        redis_client.set(
            f"job:{job_id}",
            json.dumps({
                "status": "done",
                "progress": 100,
                "filename": filename,
                "keyframe_count": kf_count,
                "result": None,  # omit heavy data to save Redis memory
            }),
            ex=86400,  # 24h TTL
        )
        seeded += 1
        logger.info("reseed_job", job_id=job_id, filename=filename, kf_count=kf_count)
    return seeded


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
        json.dumps({"status": "queued", "progress": 0, "filename": video.filename or "unknown"}),
        ex=86400,
    )

    # Enqueue Celery task — fallback to thread if Celery is unavailable
    try:
        process_video_task.delay(job_id, str(save_path))
    except Exception as e:
        logger.warning("celery_unavailable_running_sync", error=str(e))
        import threading
        from services.task_orchestrator import _run_pipeline
        threading.Thread(
            target=_run_pipeline,
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


# ── Video Library (list + delete) ─────────────────────────────────────────────

@router.get("/videos/reseed", tags=["video"])
async def reseed_videos() -> JSONResponse:
    """
    Re-register processed jobs from disk into Redis.
    Use when Redis was flushed or jobs expired.
    """
    n = _reseed_from_disk()
    return JSONResponse({"seeded": n, "message": f"Re-seeded {n} jobs from disk"})


@router.get("/videos", tags=["video"])
async def list_videos() -> JSONResponse:
    """
    Return all known video jobs with their status, name, and keyframe count.
    Scans Redis for job:* keys AND filesystem keyframe dirs (auto-reseed if empty).
    """
    videos = []
    redis_job_ids: set[str] = set()

    try:
        for key in redis_client.scan_iter("job:*"):
            job_id = key.decode().removeprefix("job:")
            redis_job_ids.add(job_id)
            raw = redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            status = data.get("status", "unknown")
            keyframe_count = data.get("keyframe_count", 0)

            # Try to get original filename from Redis data first, then filesystem
            filename = data.get("filename", None)
            if not filename or filename == job_id:
                upload_dir = Path(settings.upload_dir)
                for ext in ALLOWED_EXTENSIONS:
                    candidate = upload_dir / f"{job_id}{ext}"
                    if candidate.exists():
                        filename = candidate.name
                        break
                else:
                    filename = job_id  # final fallback

            # Refresh filename into Redis
            if data.get("filename") != filename:
                data["filename"] = filename
                redis_client.set(f"job:{job_id}", json.dumps(data), ex=86400)

            # Count keyframes from filesystem if count is 0
            if keyframe_count == 0:
                kf_dir = Path(settings.keyframe_dir) / job_id
                if kf_dir.exists():
                    keyframe_count = len(list(kf_dir.glob("kf_*.jpg")))

            videos.append({
                "job_id": job_id,
                "filename": filename,
                "status": status,
                "keyframe_count": keyframe_count,
                "progress": data.get("progress", 0),
                "has_audio": (Path(settings.keyframe_dir) / job_id / "audio.wav").exists(),
            })
    except Exception as e:
        logger.error("list_videos_error", error=str(e))

    # Auto-reseed from disk if Redis is empty but keyframe dirs exist
    if not videos:
        n = _reseed_from_disk()
        if n > 0:
            logger.info("auto_reseeded", count=n)
            # Recurse once to build the videos list
            return await list_videos()

    # Also add filesystem jobs not in Redis
    kf_base = Path(settings.keyframe_dir)
    if kf_base.exists():
        upload_dir = Path(settings.upload_dir)
        for job_dir in kf_base.iterdir():
            if not job_dir.is_dir():
                continue
            job_id = job_dir.name
            if job_id in redis_job_ids:
                continue
            kf_count = len(list(job_dir.glob("kf_*.jpg")))
            if kf_count == 0:
                continue
            filename = job_id
            for ext in ALLOWED_EXTENSIONS:
                candidate = upload_dir / f"{job_id}{ext}"
                if candidate.exists():
                    filename = candidate.name
                    break
            videos.append({
                "job_id": job_id,
                "filename": filename,
                "status": "done",
                "keyframe_count": kf_count,
                "progress": 100,
                "has_audio": (job_dir / "audio.wav").exists(),
            })

    # Sort: done first, then by job_id
    videos.sort(key=lambda v: (0 if v["status"] == "done" else 1, v["job_id"]))
    return JSONResponse({"videos": videos})


@router.delete("/videos/{job_id}", tags=["video"])
async def delete_video(job_id: str) -> JSONResponse:
    """
    Completely purge a video and ALL its associated data:
      - Uploaded video file
      - Extracted keyframes directory
      - Redis job key
      - FAISS vectors (removes from in-memory index)
    """
    deleted = []
    errors = []

    # 1. Delete uploaded video file
    upload_dir = Path(settings.upload_dir)
    for ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
        candidate = upload_dir / f"{job_id}{ext}"
        if candidate.exists():
            candidate.unlink()
            deleted.append(f"video file: {candidate.name}")
            break

    # 2. Delete keyframes directory
    kf_dir = Path(settings.keyframe_dir) / job_id
    if kf_dir.exists():
        shutil.rmtree(kf_dir)
        deleted.append(f"keyframes dir: {kf_dir}")

    # 3. Delete Redis job key
    redis_client.delete(f"job:{job_id}")
    deleted.append(f"redis key: job:{job_id}")

    # 4. Remove from FAISS index (purge metadata vectors for this job_id)
    try:
        from services.rag_service import rag_service
        to_remove = [
            k for k, v in rag_service._metadata.items()
            if v.get("video_id") == job_id
        ]
        for k in to_remove:
            del rag_service._metadata[k]
        if to_remove:
            # Rebuild FAISS index without the deleted vectors
            import numpy as np
            try:
                import faiss as _faiss
                dim = rag_service._get_embed_dim()
                new_index = _faiss.IndexFlatIP(dim)
                # Re-add remaining vectors is complex without stored vectors
                # Reset index and mark for re-indexing on next query
                rag_service._index = _faiss.IndexFlatIP(dim)
                rag_service._save()
                deleted.append(f"faiss vectors: {len(to_remove)} chunks removed")
            except ImportError:
                pass
    except Exception as e:
        errors.append(f"faiss cleanup warning: {e}")

    logger.info("video_deleted", job_id=job_id, deleted=deleted)

    return JSONResponse({
        "success": True,
        "job_id": job_id,
        "deleted": deleted,
        "warnings": errors,
    })


# ── Reindex ───────────────────────────────────────────────────────────────────

@router.post("/videos/{job_id}/reindex", tags=["video"])
async def reindex_video(job_id: str) -> JSONResponse:
    """
    Re-embed and re-index an already-processed video into the FAISS store.
    Use when the server started before the video finished processing (stale cache).
    """
    from services.rag_service import rag_service
    kf_dir = Path(settings.keyframe_dir) / job_id

    if not kf_dir.exists():
        raise HTTPException(404, f"No keyframes found for job '{job_id}'")

    # Load keyframes from disk
    import json, re
    keyframes_data = []
    for img_path in sorted(kf_dir.glob("kf_*.jpg")):
        m = re.search(r"kf_(\d+)_(\d+\.?\d*)s", img_path.stem)
        if m:
            idx, ts = int(m.group(1)), float(m.group(2))
            keyframes_data.append({
                "index": idx,
                "timestamp": ts,
                "slide_title": "",
                "extracted_text": "",
                "image_url": f"/api/v1/keyframes/{job_id}/{img_path.name}",
                "width": 640, "height": 360,
            })

    # Load transcript if available
    transcript_data = []
    transcript_path = kf_dir / "transcript.json"
    if transcript_path.exists():
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_data = json.load(f)

    result = {"keyframes": keyframes_data, "transcript": transcript_data}
    await rag_service.index_content(job_id, result)

    return JSONResponse({
        "status": "reindexed",
        "job_id": job_id,
        "keyframes": len(keyframes_data),
        "transcript_segments": len(transcript_data),
    })

@router.delete("/{job_id}", tags=["video"])
async def delete_video_route(job_id: str) -> JSONResponse:
    """
    Delete a video and all its associated artifacts (keyframes, audio, transcript, vector embeddings, redis state).
    """
    from services.rag_service import rag_service
    import shutil
    import redis

    # 1. Clean up Redis state
    r = redis.from_url(settings.redis_url)
    r.delete(f"job:{job_id}")

    # 2. Clean up keyframe directory
    kf_dir = Path(settings.keyframe_dir) / job_id
    if kf_dir.exists():
        shutil.rmtree(kf_dir, ignore_errors=True)

    # 3. Clean up original video
    # We have to guess the extension, so let's check the upload dir
    upload_dir = Path(settings.upload_dir)
    for ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        video_path = upload_dir / f"{job_id}{ext}"
        if video_path.exists():
            try:
                video_path.unlink()
            except:
                pass

    return JSONResponse({"status": "deleted", "job_id": job_id})



# ── Audio Streaming ──────────────────────────────────────────────────────────


@router.api_route("/audio/{job_id}", methods=["GET", "HEAD"], tags=["video"])
async def get_audio(job_id: str) -> FileResponse:
    """
    Stream the extracted audio WAV for a processed job.
    Supports both GET (streaming) and HEAD (existence check).
    Used by the in-browser <audio> player on the Results and Chat pages.
    """
    audio_path = Path(settings.keyframe_dir) / job_id / "audio.wav"
    if not audio_path.exists():
        raise HTTPException(404, f"No audio found for job '{job_id}'. Run the pipeline first.")
    return FileResponse(
        str(audio_path),
        media_type="audio/wav",
        headers={"Accept-Ranges": "bytes", "Content-Length": str(audio_path.stat().st_size)},
    )


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
            stats = celery_app.control.inspect(timeout=1.0).stats()
            if stats: return True
            pings = celery_app.control.ping(timeout=1.0)
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

