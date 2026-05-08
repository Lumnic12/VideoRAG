"""
Celery Task Orchestrator — Phase 1 full pipeline.
Each step writes progress to Redis for frontend polling.
"""
from __future__ import annotations

# ── WMI Hang Bypass ───────────────────────────────────────────────────────────
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
      2. Extract audio via ffmpeg          → 30→35 %
      3. VLM + transcription in parallel   → 35→70 %
      4. LLM transcript structuring        → 70→85 %
         (Ollama converts raw speech → topic sections + summaries)
      5. Build result dict                 → 85→90 %
      6. Index into FAISS RAG              → 90→100 %
    """
    from services.frame_extractor import extract_keyframes, save_keyframes
    from services.vlm_service import analyze_all_keyframes
    from services.audio_service import extract_audio, transcribe_audio
    from services.transcript_structurer import structure_transcript
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

        analyses, transcript = asyncio.run(_parallel())

        update_job(job_id, "processing", 70)
        logger.info("pipeline_vlm_done", job_id=job_id, analyses=len(analyses))

        # ── Step 4: LLM transcript structuring ────────────────────────────────
        # Converts raw choppy speech → topic sections with summaries & key terms
        # so the RAG has dense, concept-rich text to embed instead of fragments.
        update_job(job_id, "processing", 72)
        logger.info("pipeline_step4_structure", job_id=job_id,
                    segments=len(transcript))

        raw_segs = [{"start": s.start, "end": s.end, "text": s.text}
                    for s in transcript]

        try:
            structured_sections = asyncio.run(
                structure_transcript(raw_segs)
            )
        except Exception:
            structured_sections = []

        update_job(job_id, "processing", 85)
        logger.info("pipeline_structure_done", job_id=job_id,
                    sections=len(structured_sections))

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
            "transcript": raw_segs,
            # Structured sections — the primary RAG input for spoken content
            "structured_transcript": [
                {
                    "start": sec.start_sec,
                    "end": sec.end_sec,
                    "topic": sec.topic,
                    "summary": sec.summary,
                    "key_terms": sec.key_terms,
                    "raw_text": sec.raw_text,
                }
                for sec in structured_sections
            ],
        }

        # Save transcript and structured transcript to disk for later re-indexing
        transcript_path = Path(job_kf_dir) / "transcript.json"
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(result["transcript"], f, indent=2)

        structured_path = Path(job_kf_dir) / "structured_transcript.json"
        with open(structured_path, "w", encoding="utf-8") as f:
            json.dump(result["structured_transcript"], f, indent=2)

        update_job(job_id, "processing", 90)

        # ── Step 5: RAG indexing ──────────────────────────────────────────────
        logger.info("pipeline_step5_rag", job_id=job_id)
        try:
            asyncio.run(rag_service.index_content(job_id, result))
        except Exception as idx_err:
            logger.error("rag_index_failed", job_id=job_id, error=str(idx_err))

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
