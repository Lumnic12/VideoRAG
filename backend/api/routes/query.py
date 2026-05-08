"""
RAG query routes.
POST /api/v1/query        — non-streaming (existing, unchanged)
GET  /api/v1/query/stream — SSE streaming (new: tokens arrive word-by-word)
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import httpx
import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core.config import settings
from models.schemas import QueryRequest, QueryResponse, QuerySource
from services.rag_service import rag_service

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["query"])


# ── helpers ────────────────────────────────────────────────────────────────────

async def _stream_ollama(messages: list[dict]) -> AsyncIterator[str]:
    """
    Stream tokens from Ollama /api/chat endpoint.
    Yields raw text chunks as they arrive.
    """
    base = settings.ollama_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base}/api/chat"

    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.3, "num_predict": 1200},
    }

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                    except Exception:
                        continue
    except Exception as e:
        yield f"\n\n⚠️ Ollama error: {str(e)[:120]}"


# ── non-streaming endpoint (unchanged) ─────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
async def ask_second_brain(req: QueryRequest) -> QueryResponse:
    """Non-streaming RAG query. Returns full answer when complete."""
    logger.info("query_received", question=req.question[:80],
                has_history=bool(req.chat_history))
    t0 = time.monotonic()

    vid_ids: list[str] | None = req.video_ids
    if req.video_id and not vid_ids:
        vid_ids = [req.video_id]

    history_dicts = None
    if req.chat_history:
        history_dicts = [{"role": m.role, "content": m.content} for m in req.chat_history]

    result = await rag_service.query_and_answer(
        question=req.question,
        video_ids=vid_ids,
        top_k=20,
        chat_history=history_dicts,
    )

    latency_ms = round((time.monotonic() - t0) * 1000, 1)

    sources = []
    for s in result["sources"]:
        vid = s.get("video_id", "")
        ts = float(s.get("timestamp", 0.0))
        txt = s.get("text", s.get("chunk_text", ""))[:300]
        score = float(s.get("score", 0.0))
        sources.append(QuerySource(
            video_id=vid, timestamp=ts, timestamp_sec=ts,
            chunk_text=txt, text=txt, score=score,
        ))

    return QueryResponse(answer=result["answer"], sources=sources, latency_ms=latency_ms)


# ── streaming SSE endpoint ──────────────────────────────────────────────────────

@router.post("/query/stream")
async def ask_stream(req: QueryRequest) -> StreamingResponse:
    """
    Streaming RAG query via Server-Sent Events.
    Streams Ollama tokens immediately — no more blank wait screen.

    SSE protocol:
      data: <token>\\n\\n        — text token
      data: [SOURCES]<json>\\n\\n — sources at end
      data: [DONE]\\n\\n          — stream complete
    """
    vid_ids: list[str] | None = req.video_ids
    if req.video_id and not vid_ids:
        vid_ids = [req.video_id]

    history_dicts = None
    if req.chat_history:
        history_dicts = [{"role": m.role, "content": m.content} for m in req.chat_history]

    async def event_generator() -> AsyncIterator[str]:
        # Step 1: retrieve RAG context (fast — local FAISS)
        rag_service._load()
        sources = await rag_service._retrieve(req.question, vid_ids, top_k=10)

        if not sources:
            yield "data: No relevant content found. Please upload and process a video first.\n\n"
            yield "data: [DONE]\n\n"
            return

        # Step 2: build video summary (compact orientation)
        video_summary = await rag_service._build_video_summary(vid_ids)

        # Step 3: build context for LLM
        rag_context = "\n\n".join(
            f"[{s['type']} @ {s['timestamp']:.1f}s] {s['text']}"
            for s in sources
        )

        # Step 4: low-confidence fallback
        top_score = sources[0].get("score", 1.0) if sources else 0.0
        fallback = ""
        if top_score < 0.3:
            import redis as _r
            r2 = _r.from_url(settings.redis_url, decode_responses=True)
            for key in r2.keys("job:*"):
                raw = r2.get(key)
                if not raw:
                    continue
                try:
                    job = json.loads(raw)
                except Exception:
                    continue
                jid = key.replace("job:", "")
                if vid_ids and jid not in vid_ids:
                    continue
                if job.get("status") != "done":
                    continue
                segs = (job.get("result") or {}).get("transcript", [])
                if segs:
                    joined = " ".join(s.get("text", "") for s in segs[:10])
                    fallback = f"\n\n[Transcript excerpt] {joined[:500]}"
                break

        system_content = (
            "You are an expert tutor analyzing video/lecture content.\n"
            "Answer ONLY from the provided context. Cite timestamps like '@2:30'.\n"
            "Use markdown: **bold**, bullet points, `code`.\n\n"
        )
        if video_summary:
            system_content += f"=== VIDEO INFO ===\n{video_summary}\n\n"
        system_content += f"=== RETRIEVED CONTEXT (top {len(sources)} chunks) ===\n{rag_context}"
        if fallback:
            system_content += fallback

        messages: list[dict] = [{"role": "system", "content": system_content}]
        if history_dicts:
            messages.extend(history_dicts[-8:])  # last 8 turns
        messages.append({"role": "user", "content": req.question})

        # Step 5: stream tokens from Ollama
        try:
            async for token in _stream_ollama(messages):
                # Escape SSE special chars
                safe = token.replace("\n", "\\n")
                yield f"data: {safe}\n\n"
                await asyncio.sleep(0)  # yield control to event loop
        except Exception as e:
            yield f"data: ⚠️ Stream error: {str(e)[:100]}\n\n"

        # Step 6: send sources at end
        src_data = [
            {
                "video_id": s.get("video_id", ""),
                "timestamp": float(s.get("timestamp", 0)),
                "timestamp_sec": float(s.get("timestamp", 0)),
                "text": s.get("text", "")[:300],
                "chunk_text": s.get("text", "")[:300],
                "score": float(s.get("score", 0)),
                "type": s.get("type", ""),
            }
            for s in sources
        ]
        yield f"data: [SOURCES]{json.dumps(src_data)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
