"""Pydantic schemas — single source of truth for API contracts."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel


# ── Job / Processing ──────────────────────────────────────────────────────────

class ProcessResponse(BaseModel):
    task_id: str
    status: str = "queued"


class KeyframeResult(BaseModel):
    index: int
    timestamp: float
    image_url: str
    extracted_text: str
    slide_title: str
    code_snippets: list[str]
    key_concepts: list[str]


class KeyframeInfo(BaseModel):
    """Shape returned by GET /api/v1/keyframes/{job_id} — matches frontend type."""
    index: int
    frame_number: int
    timestamp_sec: float
    ssim_delta: float
    image_url: str
    image_b64: str | None = None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class JobResultData(BaseModel):
    keyframes: list[KeyframeResult]
    transcript: list[TranscriptSegment]


class JobStatusResponse(BaseModel):
    task_id: str
    status: str          # queued | processing | done | failed
    progress: int
    result: Any = None   # dict with keyframes, transcript, structured_transcript
    error: str | None = None
    keyframe_count: int | None = None


# ── RAG Query ─────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    """A single message in a multi-turn conversation."""
    role: str        # "user" or "assistant"
    content: str


class QueryRequest(BaseModel):
    question: str
    video_id: str | None = None      # convenience singular
    video_ids: list[str] | None = None
    chat_history: list[ChatMessage] | None = None  # multi-turn conversation history


class QuerySource(BaseModel):
    video_id: str
    timestamp: float
    timestamp_sec: float             # alias kept for frontend compat
    chunk_text: str
    text: str                        # alias kept for frontend compat
    score: float = 0.0


class QueryResponse(BaseModel):
    answer: str
    sources: list[QuerySource]
    latency_ms: float = 0.0


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    redis: bool
    celery: bool
    version: str = "0.2.0"
