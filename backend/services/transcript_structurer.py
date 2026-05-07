"""
transcript_structurer.py

Takes raw Whisper / Deepgram transcript segments and passes them through
the local Ollama LLM to produce a structured document BEFORE RAG indexing.

Why this matters
----------------
Raw transcript segments are just choppy speech fragments:
    "[Transcript @ 4.2s] uh so basically what we want to do here is..."
    "[Transcript @ 8.1s] we use a queue data structure because..."

This makes RAG retrieval poor — the embedding model has nothing rich to
match against. After structuring, we get:

    Topic: Queue Data Structure
    Summary: The lecturer explains that a queue is used because it guarantees
             FIFO ordering. Elements are enqueued at the rear and dequeued at
             the front, ensuring tasks are processed in arrival order.
    Key Terms: queue, FIFO, enqueue, dequeue, rear, front

Each structured section is then indexed as a SEPARATE high-quality chunk,
giving the RAG dense, concept-rich embeddings it can actually retrieve.

The raw segments are ALSO kept and indexed separately for fine-grained
timestamp lookups (nothing is lost).
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

import httpx
import structlog

from core.config import settings

logger = structlog.get_logger()

# How many seconds of transcript to feed per LLM call.
# ~90 s = ~150-300 words — comfortably fits in a 2k-token context.
_WINDOW_SEC = 90.0

# Minimum meaningful text length before we bother calling the LLM.
_MIN_CHARS = 80


@dataclass
class StructuredSection:
    """One LLM-structured segment of the transcript."""

    start_sec: float
    end_sec: float
    topic: str
    summary: str
    key_terms: list[str] = field(default_factory=list)
    raw_text: str = ""        # original transcript text for this window

    def as_rag_chunk(self) -> str:
        """Return the rich string that will be embedded into the FAISS index."""
        ts = f"{int(self.start_sec // 60)}:{int(self.start_sec % 60):02d}"
        parts = [f"[Lecture @ {ts}] Topic: {self.topic}", f"Summary: {self.summary}"]
        if self.key_terms:
            parts.append("Key Terms: " + ", ".join(self.key_terms))
        return "\n".join(parts)


# ── LLM call ─────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a lecture content analyst. You will receive a raw spoken transcript
segment from a lecture video. Your job is to produce a structured JSON object
that captures the core educational content.

Rules:
- Respond ONLY with a single valid JSON object — no markdown, no explanation.
- If the segment is mostly filler words or silence markers, still give a brief summary.
- Be concise: summary ≤ 3 sentences.
- key_terms: up to 8 important nouns/concepts mentioned.

JSON schema:
{
  "topic": "<one-line topic title>",
  "summary": "<2-3 sentence structured explanation of what was said>",
  "key_terms": ["term1", "term2", ...]
}
"""


async def _structure_window(raw_text: str, start_sec: float) -> dict | None:
    """
    Call Ollama to structure a single transcript window.
    Returns parsed JSON dict, or None on failure (raw text is still indexed).
    """
    if not settings.ollama_base_url:
        return None

    base = settings.ollama_base_url.rstrip("/")
    # Use the chat completions endpoint (OpenAI-compatible)
    url = f"{base}/chat/completions"

    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript segment (starts at {start_sec:.1f}s):\n\n{raw_text}"},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Strip markdown code fences if model wraps output
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            return json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("transcript_structure_json_error",
                        start=start_sec, error=str(e)[:100])
        return None
    except Exception as e:
        logger.warning("transcript_structure_llm_error",
                        start=start_sec, error=str(e)[:120])
        return None


# ── Main public function ──────────────────────────────────────────────────────

async def structure_transcript(
    segments: list[dict],
    window_sec: float = _WINDOW_SEC,
    max_concurrent: int = 3,
) -> list[StructuredSection]:
    """
    Takes raw transcript segments (list of {start, end, text} dicts) and
    returns a list of StructuredSection objects, one per time window.

    Processing is done in overlapping windows with limited concurrency so
    we don't overwhelm the local Ollama instance.

    Args:
        segments:        Raw transcript segments from Whisper/Deepgram.
        window_sec:      Seconds of speech per LLM call (~90s default).
        max_concurrent:  Max parallel Ollama requests (default 3).

    Returns:
        List of StructuredSection — one per window.
        Falls back gracefully: if Ollama is unavailable or the model fails,
        returns an empty list (raw segments are still indexed separately).
    """
    if not segments:
        return []

    # Group segments into time windows
    windows: list[tuple[float, float, str]] = []   # (start, end, text)
    window_text = ""
    window_start = segments[0].get("start", 0.0)
    window_end = window_start

    for seg in segments:
        seg_text = (seg.get("text") or "").strip()
        if not seg_text or seg_text.startswith("["):
            continue
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", seg_start + 1.0)

        window_text += " " + seg_text
        window_end = seg_end

        if seg_end - window_start >= window_sec:
            if len(window_text.strip()) >= _MIN_CHARS:
                windows.append((window_start, window_end, window_text.strip()))
            window_text = ""
            window_start = seg_end

    # Flush last window
    if len(window_text.strip()) >= _MIN_CHARS:
        windows.append((window_start, window_end, window_text.strip()))

    if not windows:
        logger.info("transcript_structurer_no_windows", reason="transcript too short")
        return []

    logger.info("transcript_structurer_start",
                windows=len(windows), total_segments=len(segments))

    # Run LLM calls with bounded concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _process_window(start: float, end: float, text: str) -> StructuredSection:
        async with semaphore:
            parsed = await _structure_window(text, start)

        if parsed:
            return StructuredSection(
                start_sec=start,
                end_sec=end,
                topic=parsed.get("topic", "Lecture Content"),
                summary=parsed.get("summary", text[:200]),
                key_terms=parsed.get("key_terms", [])[:8],
                raw_text=text,
            )
        else:
            # Graceful fallback: use the raw text as the summary
            return StructuredSection(
                start_sec=start,
                end_sec=end,
                topic=f"Lecture @ {int(start // 60)}:{int(start % 60):02d}",
                summary=text[:300],
                key_terms=[],
                raw_text=text,
            )

    tasks = [_process_window(s, e, t) for s, e, t in windows]
    results = await asyncio.gather(*tasks)

    logger.info("transcript_structurer_done",
                sections=len(results),
                topics=[r.topic[:40] for r in results[:5]])

    return list(results)
