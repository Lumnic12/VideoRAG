"""
Phase 1 end-to-end pipeline integration test.
Runs SSIM extractor + VLM + RAG indexing + query directly (no HTTP/Celery).

Run from: backend/
  python tests/test_pipeline.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Backend root on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.frame_extractor import extract_keyframes, save_keyframes
from services.vlm_service import analyze_all_keyframes
from services.audio_service import extract_audio, transcribe_audio
from services.rag_service import rag_service
from core.config import settings


VIDEO_PATH = Path(__file__).parent / "test_lecture.mp4"
TEST_JOB_ID = "pipeline-test-001"
SEP = "=" * 60


def header(text: str) -> None:
    print(f"\n{SEP}\n  {text}\n{SEP}")


def ok(msg: str) -> None:
    print(f"  [PASS]  {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL]  {msg}")
    sys.exit(1)


def check(condition: bool, msg: str) -> None:
    (ok if condition else fail)(msg)


async def run_test() -> None:
    header("Phase 1 Pipeline Integration Test")
    print(f"  Video : {VIDEO_PATH}")
    check(VIDEO_PATH.exists(), f"Test video found at {VIDEO_PATH}")

    # Step 1 — SSIM Extraction
    header("Step 1: SSIM Keyframe Extraction")
    t0 = time.monotonic()
    keyframes = extract_keyframes(str(VIDEO_PATH), threshold=settings.ssim_threshold)
    elapsed = time.monotonic() - t0

    check(len(keyframes) >= 1, f"Got >= 1 keyframe (found {len(keyframes)})")
    check(keyframes[0].timestamp_sec == 0.0, "First keyframe at t=0.0s")
    print(f"  Time   : {elapsed:.2f}s")
    print(f"  Frames : {len(keyframes)}")
    for kf in keyframes:
        print(f"    kf[{kf.index:02d}]  t={kf.timestamp_sec:.2f}s  ssim_delta={kf.ssim_delta:.4f}")

    # Step 2 — Save keyframes
    header("Step 2: Save Keyframes to Disk")
    out_dir = Path(settings.keyframe_dir) / TEST_JOB_ID
    image_paths = save_keyframes(keyframes, str(out_dir))
    check(len(image_paths) == len(keyframes), f"Saved {len(image_paths)} JPEG files")
    check(all(Path(p).exists() for p in image_paths), "All JPEG files exist on disk")
    for p in image_paths:
        print(f"    {Path(p).name}  ({Path(p).stat().st_size // 1024} KB)")

    timestamps = [kf.timestamp_sec for kf in keyframes]

    # Step 3 — VLM Analysis
    header("Step 3: VLM Keyframe Analysis (stubs if no HF_API_TOKEN)")
    analyses = await analyze_all_keyframes(image_paths, timestamps)
    check(len(analyses) == len(keyframes), f"Got {len(analyses)} SlideAnalysis objects")
    print(f"  Sample slide_title  : {analyses[0].slide_title!r}")
    print(f"  Sample key_concepts : {analyses[0].key_concepts}")

    # Step 4 — Audio
    header("Step 4: Audio Extraction + Transcription")
    audio_path = extract_audio(str(VIDEO_PATH), str(out_dir))
    if audio_path:
        print(f"  Audio extracted: {audio_path}")
    else:
        print("  ffmpeg not on PATH -- audio skipped (stub mode)")

    transcript = await transcribe_audio(audio_path)
    print(f"  Transcript segments: {len(transcript)}")

    # Step 5 — Build result
    header("Step 5: Build Result Payload")
    result: dict = {
        "keyframes": [
            {
                "index": a.keyframe_index,
                "timestamp": a.timestamp_sec,
                "image_url": f"/static/keyframes/{TEST_JOB_ID}/{Path(p).name}",
                "extracted_text": a.extracted_text,
                "slide_title": a.slide_title,
                "code_snippets": a.code_snippets,
                "key_concepts": a.key_concepts,
            }
            for a, p in zip(analyses, image_paths)
        ],
        "transcript": [{"start": s.start, "end": s.end, "text": s.text} for s in transcript],
    }
    check(len(result["keyframes"]) > 0, "Result has keyframes")
    print(f"  keyframes  : {len(result['keyframes'])}")
    print(f"  transcript : {len(result['transcript'])} segments")

    # Step 6 — RAG Indexing
    header("Step 6: FAISS RAG Indexing")
    await rag_service.index_content(TEST_JOB_ID, result)
    ok("Content indexed into FAISS/memory store")

    # Step 7 — Query
    header("Step 7: RAG Query")
    query_result = await rag_service.query_and_answer(
        question="What is SSIM and how does keyframe extraction work?",
        video_ids=[TEST_JOB_ID],
    )
    check("answer" in query_result, "Query returned an answer")
    check(isinstance(query_result["sources"], list), "Query returned sources list")
    answer_snippet = query_result["answer"][:200].replace("\n", " ")
    print(f"  Answer   : {answer_snippet}...")
    print(f"  Sources  : {len(query_result['sources'])} chunk(s)")

    # Summary
    header("Phase 1 Quality Gate -- ALL CHECKS PASSED")
    print(f"  keyframe_count = {len(keyframes)}")
    print(f"  status         = done")
    print(f"  rag_indexed    = yes")
    print(f"  query_works    = yes")
    print()


if __name__ == "__main__":
    asyncio.run(run_test())
