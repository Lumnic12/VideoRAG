"""
RAG query route.
POST /api/v1/query — retrieve context from FAISS, synthesise answer with GPT-4o-mini.
"""
from __future__ import annotations

import time

import structlog
from fastapi import APIRouter

from models.schemas import QueryRequest, QueryResponse, QuerySource
from services.rag_service import rag_service

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def ask_second_brain(req: QueryRequest) -> QueryResponse:
    """
    Retrieve relevant chunks from FAISS, synthesise answer with GPT-4o-mini.
    Returns grounded answer + source citations.
    """
    logger.info("query_received", question=req.question[:80])
    t0 = time.monotonic()

    # Merge video_id (singular) and video_ids (list)
    vid_ids: list[str] | None = req.video_ids
    if req.video_id and not vid_ids:
        vid_ids = [req.video_id]

    result = await rag_service.query_and_answer(
        question=req.question,
        video_ids=vid_ids,
        top_k=5,
    )

    latency_ms = round((time.monotonic() - t0) * 1000, 1)

    sources = []
    for s in result["sources"]:
        vid = s.get("video_id", "")
        ts = float(s.get("timestamp", 0.0))
        txt = s.get("text", s.get("chunk_text", ""))[:300]
        score = float(s.get("score", 0.0))
        sources.append(QuerySource(
            video_id=vid,
            timestamp=ts,
            timestamp_sec=ts,
            chunk_text=txt,
            text=txt,
            score=score,
        ))

    return QueryResponse(
        answer=result["answer"],
        sources=sources,
        latency_ms=latency_ms,
    )
