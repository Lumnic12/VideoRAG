"""
VLM Service — Jina-VLM via HuggingFace Inference API.
Sends keyframe images to jinaai/jina-vlm-v1 and parses structured JSON output.

Graceful stub: if HF_API_TOKEN is missing or the call fails, returns synthetic
SlideAnalysis so the rest of the pipeline continues uninterrupted.
"""
from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field

import httpx
import structlog

from core.config import settings

logger = structlog.get_logger()

HF_INFERENCE_URL = (
    "https://router.huggingface.co/hf-inference/models/jinaai/jina-vlm-v1"
)

PROMPT = """Analyze this lecture slide image. Return ONLY a valid JSON object with these keys:
{
  "slide_title": "the title or heading visible on the slide",
  "extracted_text": "all readable text on the slide verbatim",
  "code_snippets": ["any code blocks found as strings"],
  "key_concepts": ["3-5 key technical concepts mentioned"]
}
No markdown fences. No explanation. JSON only."""


@dataclass
class SlideAnalysis:
    """Structured analysis of a single keyframe image."""

    keyframe_index: int
    timestamp_sec: float
    extracted_text: str
    slide_title: str
    code_snippets: list[str] = field(default_factory=list)
    key_concepts: list[str] = field(default_factory=list)


def _encode_image(image_path: str) -> str:
    """Base64-encode an image file."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _stub_analysis(index: int, timestamp: float, reason: str) -> SlideAnalysis:
    """Return a synthetic analysis when VLM is unavailable."""
    logger.warning("vlm_stub_used", index=index, reason=reason)
    return SlideAnalysis(
        keyframe_index=index,
        timestamp_sec=timestamp,
        extracted_text=f"[VLM stub — {reason}]",
        slide_title=f"Slide {index + 1}",
        code_snippets=[],
        key_concepts=["lecture content", "educational material"],
    )


async def analyze_keyframe(
    image_path: str,
    keyframe_index: int,
    timestamp_sec: float,
) -> SlideAnalysis:
    """
    Send a single keyframe to Jina-VLM for analysis.

    Args:
        image_path:     Path to JPEG image on disk.
        keyframe_index: Sequential keyframe number (for logging).
        timestamp_sec:  Video timestamp in seconds.

    Returns:
        SlideAnalysis with extracted text and concepts.
    """
    if not settings.hf_api_token:
        return _stub_analysis(keyframe_index, timestamp_sec, "no HF_API_TOKEN")

    try:
        b64 = _encode_image(image_path)
    except OSError as e:
        return _stub_analysis(keyframe_index, timestamp_sec, f"image read error: {e}")

    payload = {
        "inputs": [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            },
            {"type": "text", "text": PROMPT},
        ],
        "parameters": {"max_new_tokens": 512, "temperature": 0.1},
    }
    headers = {"Authorization": f"Bearer {settings.hf_api_token}"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(HF_INFERENCE_URL, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPStatusError as e:
        return _stub_analysis(keyframe_index, timestamp_sec, f"HF API {e.response.status_code}")
    except Exception as e:
        return _stub_analysis(keyframe_index, timestamp_sec, f"HTTP error: {e}")

    # Parse model output defensively
    try:
        text_out = (
            result[0]["generated_text"]
            if isinstance(result, list)
            else result.get("generated_text", "")
        )
        parsed = json.loads(text_out)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        logger.warning("vlm_parse_failed", index=keyframe_index, raw=str(result)[:200])
        parsed = {
            "slide_title": "",
            "extracted_text": str(result)[:500],
            "code_snippets": [],
            "key_concepts": [],
        }

    logger.info("vlm_success", index=keyframe_index, timestamp=timestamp_sec)
    return SlideAnalysis(
        keyframe_index=keyframe_index,
        timestamp_sec=timestamp_sec,
        extracted_text=parsed.get("extracted_text", ""),
        slide_title=parsed.get("slide_title", ""),
        code_snippets=parsed.get("code_snippets", []),
        key_concepts=parsed.get("key_concepts", []),
    )


async def analyze_all_keyframes(
    image_paths: list[str],
    timestamps: list[float],
) -> list[SlideAnalysis]:
    """
    Process all keyframes with bounded concurrency (max 3 parallel API calls).

    Args:
        image_paths: List of keyframe JPEG paths on disk.
        timestamps:  Corresponding video timestamps.

    Returns:
        List of SlideAnalysis in the same order as image_paths.
    """
    semaphore = asyncio.Semaphore(3)

    async def _bounded(path: str, idx: int, ts: float) -> SlideAnalysis:
        async with semaphore:
            return await analyze_keyframe(path, idx, ts)

    tasks = [
        _bounded(path, idx, ts)
        for idx, (path, ts) in enumerate(zip(image_paths, timestamps))
    ]
    return list(await asyncio.gather(*tasks))
