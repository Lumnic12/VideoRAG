"""
Unit tests for rag_service.py — Phase 3.

Tests both the stub path (no OpenAI key) and structural contracts
of RAGService without making real network calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Ensure backend/ is on sys.path
_BACKEND_DIR = Path(__file__).parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from services.rag_service import RAGService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_service(tmp_path, monkeypatch):
    """
    A RAGService with a temp FAISS index path and no OpenAI key.
    Guarantees a clean state and uses stub embeddings.
    """
    monkeypatch.setenv("FAISS_INDEX_PATH", str(tmp_path / "faiss_index"))
    # Patch settings on the already-imported module
    from core import config
    monkeypatch.setattr(config.settings, "faiss_index_path", str(tmp_path / "faiss_index"))
    monkeypatch.setattr(config.settings, "openai_api_key", "", raising=False)
    svc = RAGService()
    return svc


# ── Empty state ───────────────────────────────────────────────────────────────

class TestRAGServiceEmptyState:

    @pytest.mark.asyncio
    async def test_query_on_empty_index_returns_no_sources(self, fresh_service):
        """Querying an empty index must return no sources and not raise."""
        result = await fresh_service.query_and_answer("What is SSIM?")
        assert "answer" in result
        assert "sources" in result
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_empty_answer_contains_helpful_message(self, fresh_service):
        """Answer for empty index must tell user to upload a video."""
        result = await fresh_service.query_and_answer("Hello?")
        assert "upload" in result["answer"].lower() or "process" in result["answer"].lower()


# ── Index + retrieve ──────────────────────────────────────────────────────────

SAMPLE_RESULT = {
    "keyframes": [
        {
            "slide_title": "Introduction to SSIM",
            "extracted_text": "Structural Similarity Index Measure compares images perceptually.",
            "code_snippets": [],
            "timestamp": 5.0,
            "image_url": "/static/keyframes/test-job/kf_000_5.0s.jpg",
        },
        {
            "slide_title": "FAISS Vector Store",
            "extracted_text": "FAISS enables billion-scale similarity search in milliseconds.",
            "code_snippets": ["index = faiss.IndexFlatIP(1536)"],
            "timestamp": 30.0,
            "image_url": "/static/keyframes/test-job/kf_001_30.0s.jpg",
        },
    ],
    "transcript": [
        {"start": 0.0, "end": 10.0, "text": "Today we will discuss SSIM and its applications."},
        {"start": 10.0, "end": 45.0, "text": "FAISS is a library for efficient similarity search."},
    ],
}


class TestRAGServiceIndexing:

    @pytest.mark.asyncio
    async def test_index_content_does_not_raise(self, fresh_service):
        """index_content must complete without exceptions (stub embedding path)."""
        await fresh_service.index_content("video-001", SAMPLE_RESULT)

    @pytest.mark.asyncio
    async def test_metadata_populated_after_indexing(self, fresh_service):
        """Internal metadata store must have entries after indexing."""
        await fresh_service.index_content("video-001", SAMPLE_RESULT)
        assert len(fresh_service._metadata) > 0

    @pytest.mark.asyncio
    async def test_counter_increments_per_chunk(self, fresh_service):
        """Counter tracks each indexed chunk (keyframes + transcript windows)."""
        await fresh_service.index_content("video-001", SAMPLE_RESULT)
        # 2 keyframes = 2 chunks; 1 transcript window (45s < 30s boundary only once)
        assert fresh_service._counter >= 2

    @pytest.mark.asyncio
    async def test_retrieval_returns_results_after_indexing(self, fresh_service):
        """After indexing, query must return at least one source."""
        await fresh_service.index_content("video-001", SAMPLE_RESULT)
        result = await fresh_service.query_and_answer("What is SSIM?")
        assert len(result["sources"]) > 0

    @pytest.mark.asyncio
    async def test_video_id_filter_works(self, fresh_service):
        """video_ids filter must exclude chunks from other videos."""
        await fresh_service.index_content("video-A", SAMPLE_RESULT)
        await fresh_service.index_content("video-B", SAMPLE_RESULT)
        result = await fresh_service.query_and_answer(
            "SSIM", video_ids=["video-A"]
        )
        for src in result["sources"]:
            assert src.get("video_id") == "video-A"

    @pytest.mark.asyncio
    async def test_index_idempotent_for_same_video(self, fresh_service):
        """Indexing same video twice must not corrupt the store."""
        await fresh_service.index_content("video-001", SAMPLE_RESULT)
        count_after_first = fresh_service._counter
        await fresh_service.index_content("video-001", SAMPLE_RESULT)
        # Counter just keeps incrementing — no crash expected
        assert fresh_service._counter > count_after_first


# ── Persistence ───────────────────────────────────────────────────────────────

class TestRAGServicePersistence:

    @pytest.mark.asyncio
    async def test_save_creates_metadata_file(self, fresh_service, tmp_path):
        """_save() must write metadata.pkl to the index directory."""
        from core import config
        idx_dir = Path(config.settings.faiss_index_path)
        await fresh_service.index_content("video-001", SAMPLE_RESULT)
        assert (idx_dir / "metadata.pkl").exists()

    @pytest.mark.asyncio
    async def test_load_restores_metadata(self, tmp_path, monkeypatch):
        """A new RAGService instance must load persisted metadata."""
        from core import config
        monkeypatch.setattr(config.settings, "faiss_index_path", str(tmp_path / "faiss_index"))
        monkeypatch.setattr(config.settings, "openai_api_key", "", raising=False)

        svc1 = RAGService()
        await svc1.index_content("video-persist", SAMPLE_RESULT)
        chunk_count = svc1._counter

        svc2 = RAGService()
        svc2._load()
        assert svc2._counter == chunk_count
        assert len(svc2._metadata) == len(svc1._metadata)
