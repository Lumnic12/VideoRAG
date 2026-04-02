"""
RAG Engine — FAISS-based semantic retrieval
Phase 0: Class skeleton with full interface defined.
Phase 2: Will implement real embedding + search.

ADR-002: FAISS locally for MVP; Pinecone for production if needed.
"""
from __future__ import annotations

import dataclasses
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np

# These imports are guarded so the module loads even without GPU/FAISS installed
try:
    import faiss
    _FAISS_OK = True
except ImportError:
    _FAISS_OK = False

try:
    from sentence_transformers import SentenceTransformer
    _ST_OK = True
except ImportError:
    _ST_OK = False


INDEX_DIR = Path(os.getenv("FAISS_INDEX_DIR", "./indexes"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_DIM = 384  # dimension of all-MiniLM-L6-v2


@dataclasses.dataclass
class RetrievedChunk:
    text: str
    timestamp_sec: float
    score: float
    video_id: str = ""


class RAGEngine:
    """
    Manages a FAISS flat-L2 index for video content chunks.

    Usage (Phase 2):
        engine = RAGEngine()
        engine.index_video("task_123", keyframes)
        results = engine.query("What is SSIM?", top_k=5)
    """

    def __init__(self):
        self._model: Any = None
        self._index: Any = None
        self._chunks: list[dict] = []
        INDEX_DIR.mkdir(parents=True, exist_ok=True)

    def _load_model(self):
        if self._model is None and _ST_OK:
            self._model = SentenceTransformer(EMBED_MODEL)

    def _embed(self, texts: list[str]) -> np.ndarray:
        self._load_model()
        if self._model is None:
            # Stub: return random vectors
            return np.random.rand(len(texts), EMBED_DIM).astype("float32")
        vecs = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return vecs.astype("float32")

    def index_video(self, video_id: str, chunks: list[dict]) -> None:
        """
        Embed and index a list of text chunks for a video.

        Args:
            video_id: Unique identifier for the video (task_id).
            chunks:   List of dicts with keys: 'text', 'timestamp_sec'.
        """
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        vecs = self._embed(texts)

        if not _FAISS_OK:
            # Phase 0 stub: skip actual index
            self._chunks.extend([{**c, "video_id": video_id} for c in chunks])
            return

        if self._index is None:
            self._index = faiss.IndexFlatIP(EMBED_DIM)  # inner product (cosine after normalize)

        faiss.normalize_L2(vecs)
        self._index.add(vecs)
        self._chunks.extend([{**c, "video_id": video_id} for c in chunks])
        self._save()

    def query(self, question: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Retrieve top-k most relevant chunks for a question."""
        if not self._chunks:
            return self._stub_results(question)

        q_vec = self._embed([question])

        if not _FAISS_OK or self._index is None:
            return self._stub_results(question)

        faiss.normalize_L2(q_vec)
        scores, idxs = self._index.search(q_vec, min(top_k, len(self._chunks)))

        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0:
                continue
            c = self._chunks[idx]
            results.append(RetrievedChunk(
                text=c["text"],
                timestamp_sec=c.get("timestamp_sec", 0.0),
                score=float(score),
                video_id=c.get("video_id", ""),
            ))
        return results

    def _stub_results(self, question: str) -> list[RetrievedChunk]:
        """Phase 0/1 stub — no real index yet."""
        return [
            RetrievedChunk(text=f"[stub] Relevant chunk for: {question}", timestamp_sec=0.0, score=0.9),
        ]

    def _save(self):
        if not _FAISS_OK or self._index is None:
            return
        faiss.write_index(self._index, str(INDEX_DIR / "main.faiss"))
        with open(INDEX_DIR / "chunks.pkl", "wb") as f:
            pickle.dump(self._chunks, f)

    def load(self):
        idx_path = INDEX_DIR / "main.faiss"
        chunk_path = INDEX_DIR / "chunks.pkl"
        if idx_path.exists() and _FAISS_OK:
            self._index = faiss.read_index(str(idx_path))
        if chunk_path.exists():
            with open(chunk_path, "rb") as f:
                self._chunks = pickle.load(f)


# Singleton instance
rag_engine = RAGEngine()
