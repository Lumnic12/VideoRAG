"""
WebSocket routes — real-time job progress streaming.

GET /ws/jobs/{job_id}
  Streams JSON frames: {type, status, progress, message, result?}
  until the job reaches 'done' or 'failed'.
"""
from __future__ import annotations

import asyncio
import json

import redis as redis_lib
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import settings

logger = structlog.get_logger()
router = APIRouter(tags=["websocket"])

_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

TERMINAL_STATUSES = {"done", "failed", "complete"}
POLL_INTERVAL = 0.5   # seconds between Redis reads


@router.websocket("/ws/jobs/{job_id}")
async def stream_job(websocket: WebSocket, job_id: str) -> None:
    """
    Stream job progress updates over WebSocket.

    Message envelope:
      { "type": "progress", "status": str, "progress": int, "message": str }
      { "type": "done",     "status": "done", "progress": 100, "result": {...} }
      { "type": "error",    "status": "failed", "error": str }
    """
    await websocket.accept()
    logger.info("ws_connected", job_id=job_id)

    last_progress = -1

    try:
        while True:
            raw = _redis.get(f"job:{job_id}")
            if not raw:
                await websocket.send_json({
                    "type": "error",
                    "status": "not_found",
                    "error": f"Job '{job_id}' not found",
                })
                break

            data: dict = json.loads(raw)
            status = data.get("status", "processing")
            progress = data.get("progress", 0)

            # Only push when something changed
            if progress != last_progress or status in TERMINAL_STATUSES:
                last_progress = progress

                if status in TERMINAL_STATUSES:
                    await websocket.send_json({
                        "type": "done" if status != "failed" else "error",
                        "status": status,
                        "progress": progress,
                        "result": data.get("result"),
                        "keyframe_count": data.get("keyframe_count", 0),
                        "error": data.get("error"),
                    })
                    break
                else:
                    step = _progress_to_step(progress)
                    await websocket.send_json({
                        "type": "progress",
                        "status": status,
                        "progress": progress,
                        "message": step,
                    })

            await asyncio.sleep(POLL_INTERVAL)

    except WebSocketDisconnect:
        logger.info("ws_disconnected", job_id=job_id)
    except Exception as exc:
        logger.error("ws_error", job_id=job_id, error=str(exc))
        try:
            await websocket.send_json({"type": "error", "error": str(exc)})
        except Exception:
            pass


def _progress_to_step(progress: int) -> str:
    """Map progress % to a human-readable pipeline step name."""
    if progress < 10:
        return "Queued — waiting for worker..."
    if progress < 30:
        return "Step 1/5 — Extracting keyframes via SSIM..."
    if progress < 40:
        return "Step 2/5 — Extracting audio track..."
    if progress < 80:
        return "Step 3/5 — Analyzing keyframes with VLM + transcribing..."
    if progress < 90:
        return "Step 4/5 — Building result payload..."
    if progress < 100:
        return "Step 5/5 — Indexing into FAISS RAG store..."
    return "Done!"
