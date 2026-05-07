"""
Celery Task Orchestrator — Phase 1 full pipeline.
Each step writes progress to Redis for frontend polling.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import redis as redis_lib
import structlog
from celery import Celery

from core.config import settings

logger = structlog.get_logger()

celery_app = Celery("svs", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_expires=86400,
)

redis_client = redis_lib.from_url(settings.redis_url)


# ── Job state helpers ─────────────────────────────────────────────────────────

def update_job(
    job_id: str,
    status: str,
    progress: int,
    data: dict | None = None,
    error: str | None = None,
) -> None:
    """Write job state to Redis, preserving existing filename."""
    # Read existing state to preserve filename
    existing: dict = {}
    raw = redis_client.get(f"job:{job_id}")
    if raw:
        try:
            existing = json.loads(raw)
        except Exception:
            pass
    state: dict = {
        "status": status,
        "progress": progress,
        "filename": existing.get("filename", ""),
    }
    if data:
        state["result"] = data
    if error:
        state["error"] = error
    redis_client.set(f"job:{job_id}", json.dumps(state), ex=86400)


# ── Core pipeline (pure function — no Celery binding) ─────────────────────────

def _run_pipeline(job_id: str, video_path: str) -> dict:
    """
    Core pipeline logic — called by both the Celery task AND the thread fallback.

    Steps:
      1. SSIM keyframe extraction         → 10→30 %
      2. Extract audio via ffmpeg          → 30→40 %
      3. VLM + transcription in parallel   → 40→80 %
      4. Build result dict                 → 80→90 %
      5. Index into FAISS RAG              → 90→100 %
    """
    from services.frame_extractor import extract_keyframes, save_keyframes
    from services.vlm_service import analyze_all_keyframes
    from services.audio_service import extract_audio, transcribe_audio
    from services.rag_service import rag_service

    try:
        # ── Step 1: SSIM extraction ───────────────────────────────────────────
        update_job(job_id, "processing", 10)
        logger.info("pipeline_step1_ssim", job_id=job_id)

        keyframes = extract_keyframes(video_path, threshold=settings.ssim_threshold)
        job_kf_dir = str(Path(settings.keyframe_dir) / job_id)
        image_paths = save_keyframes(keyframes, job_kf_dir)
        timestamps = [kf.timestamp_sec for kf in keyframes]

        update_job(job_id, "processing", 30)
        logger.info("pipeline_ssim_done", job_id=job_id, keyframes=len(keyframes))

        # ── Step 2: Extract audio ─────────────────────────────────────────────
        update_job(job_id, "processing", 35)
        logger.info("pipeline_step2_audio", job_id=job_id)
        audio_path = extract_audio(video_path, job_kf_dir)

        # ── Step 3: VLM + transcription concurrently ──────────────────────────
        update_job(job_id, "processing", 40)
        logger.info("pipeline_step3_vlm_transcript", job_id=job_id)

        async def _parallel() -> tuple:
            vlm_coro = analyze_all_keyframes(image_paths, timestamps)
            tr_coro = transcribe_audio(audio_path)
            return await asyncio.gather(vlm_coro, tr_coro)

        loop = asyncio.new_event_loop()
        try:
            analyses, transcript = loop.run_until_complete(_parallel())
        finally:
            loop.close()

        update_job(job_id, "processing", 80)
        logger.info("pipeline_vlm_done", job_id=job_id, analyses=len(analyses))

        result: dict = {
            "keyframes": [
                {
                    "index": a.keyframe_index,
                    "timestamp": a.timestamp_sec,
                    "image_url": f"/static/keyframes/{job_id}/{Path(p).name}",
                    "extracted_text": a.extracted_text,
                    "slide_title": a.slide_title,
                    "code_snippets": a.code_snippets,
                    "key_concepts": a.key_concepts,
                }
                for a, p in zip(analyses, image_paths)
            ],
            "transcript": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in transcript
            ],
        }

        # Save transcript to disk for later re-indexing
        transcript_path = Path(job_kf_dir) / "transcript.json"
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(result["transcript"], f, indent=2)

        update_job(job_id, "processing", 90)

        # ── Step 5: RAG indexing ──────────────────────────────────────────────
        logger.info("pipeline_step5_rag", job_id=job_id)
        loop2 = asyncio.new_event_loop()
        try:
            loop2.run_until_complete(rag_service.index_content(job_id, result))
        finally:
            loop2.close()

        # Preserve filename from initial Redis entry
        existing_raw = redis_client.get(f"job:{job_id}")
        filename = ""
        if existing_raw:
            try:
                filename = json.loads(existing_raw).get("filename", "")
            except Exception:
                pass

        redis_client.set(
            f"job:{job_id}",
            json.dumps({
                "status": "done",
                "progress": 100,
                "filename": filename,
                "result": result,
                "keyframe_count": len(keyframes),
            }),
            ex=86400,
        )
        logger.info("pipeline_complete", job_id=job_id)
        return {"status": "done", "keyframe_count": len(keyframes)}

    except Exception as exc:
        logger.error("pipeline_failed", job_id=job_id, error=str(exc))
        update_job(job_id, "failed", 0, error=str(exc))
        raise


# ── Celery task wrapper ───────────────────────────────────────────────────────

@celery_app.task(name="process_video", bind=True)
def process_video_task(self, job_id: str, video_path: str) -> dict:
    """Celery task wrapper — delegates to _run_pipeline."""
    return _run_pipeline(job_id, video_path)
