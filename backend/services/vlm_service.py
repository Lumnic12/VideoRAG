"""
VLM Service — 100% LOCAL keyframe analysis. No API keys needed.

Text extraction:
  1. winocr (Windows built-in OCR via WinRT) — zero external install
  2. Tesseract OCR (if installed)
  3. Basic OpenCV fallback

Enrichment:
  - Ollama gemma3:1b — extracts title/concepts from OCR text

Everything runs locally. No cloud APIs. No PyTorch.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field

import cv2
import numpy as np
import httpx
import structlog

from core.config import settings

logger = structlog.get_logger()

# Check for winocr (Windows built-in OCR wrapper)
try:
    import winocr
    _WINOCR_OK = True
    logger.info("winocr_available")
except ImportError:
    _WINOCR_OK = False


@dataclass
class SlideAnalysis:
    keyframe_index: int
    timestamp_sec: float
    extracted_text: str
    slide_title: str
    code_snippets: list[str] = field(default_factory=list)
    key_concepts: list[str] = field(default_factory=list)


# ── Windows OCR via winocr ────────────────────────────────────────────────────

async def _extract_text_winocr(image_path: str) -> str:
    """Use Windows built-in OCR (via winocr). Zero external install."""
    if not _WINOCR_OK:
        return ""
    try:
        # winocr needs raw BGRA pixel bytes + dimensions
        img = cv2.imread(image_path)
        if img is None:
            return ""
        # Convert BGR to BGRA (Windows OCR expects 4 channels)
        bgra = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        h, w = bgra.shape[:2]
        img_bytes = bgra.tobytes()

        result = await winocr.recognize_bytes(img_bytes, w, h, lang="en")
        text = result.text.strip() if result and result.text else ""
        if text:
            lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 1]
            return "\n".join(lines)
        return ""
    except Exception as e:
        logger.debug("winocr_error", error=str(e)[:80])
        return ""


# ── Tesseract OCR (if installed) ──────────────────────────────────────────────

def _tesseract_available() -> bool:
    try:
        subprocess.run(["tesseract", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

_HAS_TESSERACT = _tesseract_available()

def _extract_text_tesseract(image_path: str) -> str:
    if not _HAS_TESSERACT:
        return ""
    try:
        result = subprocess.run(
            ["tesseract", image_path, "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=15,
        )
        lines = [l.strip() for l in result.stdout.strip().split("\n") if len(l.strip()) > 2]
        return " ".join(lines)
    except Exception:
        return ""


# ── Combined OCR ─────────────────────────────────────────────────────────────

async def _extract_text(image_path: str) -> str:
    # 1. Windows OCR via winocr
    text = await _extract_text_winocr(image_path)
    if text and len(text) > 5:
        logger.info("ocr_winocr_success", chars=len(text))
        return text

    # 2. Tesseract
    text = await asyncio.to_thread(_extract_text_tesseract, image_path)
    if text and len(text) > 5:
        logger.info("ocr_tesseract_success", chars=len(text))
        return text

    return ""


# ── Ollama enrichment ────────────────────────────────────────────────────────

async def _enrich_with_ollama(text: str, index: int) -> dict:
    if not settings.ollama_base_url or not text.strip():
        return {"slide_title": "", "key_concepts": [], "code_snippets": []}

    base = settings.ollama_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]

    prompt = f"""From this lecture slide text, extract JSON:
{{"slide_title":"main heading","key_concepts":["topic1","topic2"],"code_snippets":["any code"]}}
Text: {text[:1000]}
Return ONLY JSON."""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{base}/api/chat", json={
                "model": settings.ollama_model,  # respects OLLAMA_MODEL env var
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 200},
            })
            resp.raise_for_status()
            raw = resp.json().get("message", {}).get("content", "").strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1])
            return json.loads(raw)
    except Exception:
        return {"slide_title": "", "key_concepts": [], "code_snippets": []}


# ── Basic OpenCV fallback ────────────────────────────────────────────────────

def _analyze_image_basic(image_path: str) -> str:
    try:
        img = cv2.imread(image_path)
        if img is None:
            return "empty frame"
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        brightness = int(np.mean(gray))
        edges = cv2.Canny(gray, 50, 150)
        edge_pct = round(np.count_nonzero(edges) / edges.size * 100, 1)
        parts = [f"{w}x{h}"]
        if brightness < 60: parts.append("dark background")
        elif brightness > 200: parts.append("light/white background")
        if edge_pct > 15: parts.append("high text density")
        elif edge_pct > 5: parts.append("moderate content")
        return f"Visual frame: {', '.join(parts)}"
    except Exception:
        return "frame"


# ── Main Entrypoint ──────────────────────────────────────────────────────────

async def analyze_keyframe(
    image_path: str, keyframe_index: int, timestamp_sec: float,
) -> SlideAnalysis:
    """100% local: Windows OCR / Tesseract for text, no cloud APIs."""
    ocr_text = await _extract_text(image_path)

    if ocr_text and len(ocr_text) > 5:
        # Use first line as title (heuristic — works for slides)
        lines = [l.strip() for l in ocr_text.split("\n") if l.strip()]
        title = lines[0][:80] if lines else f"Frame {keyframe_index + 1}"
        return SlideAnalysis(
            keyframe_index=keyframe_index,
            timestamp_sec=timestamp_sec,
            extracted_text=ocr_text,
            slide_title=title,
        )

    basic = await asyncio.to_thread(_analyze_image_basic, image_path)
    return SlideAnalysis(
        keyframe_index=keyframe_index,
        timestamp_sec=timestamp_sec,
        extracted_text=basic,
        slide_title=f"Frame {keyframe_index + 1}",
    )


async def analyze_all_keyframes(
    image_paths: list[str], timestamps: list[float],
) -> list[SlideAnalysis]:
    semaphore = asyncio.Semaphore(3)

    async def _bounded(path: str, idx: int, ts: float) -> SlideAnalysis:
        async with semaphore:
            return await analyze_keyframe(path, idx, ts)

    tasks = [_bounded(p, i, t) for i, (p, t) in enumerate(zip(image_paths, timestamps))]
    results = list(await asyncio.gather(*tasks))

    ocr_count = sum(1 for r in results if not r.extracted_text.startswith("Visual frame"))
    logger.info("vlm_complete", total=len(results), with_ocr_text=ocr_count)
    return results
