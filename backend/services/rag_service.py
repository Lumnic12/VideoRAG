"""
RAG Service — FAISS + OpenAI embeddings + GPT-4o-mini answer synthesis.

ADR-002: FAISS local MVP. Pinecone for production if needed.

Graceful stubs:
- No OPENAI_API_KEY → random vectors for embedding, canned answer for query
- FAISS not installed → in-memory list search fallback
"""
from __future__ import annotations

import asyncio
import json
import pickle
from pathlib import Path

import numpy as np
import structlog

from core.config import settings

logger = structlog.get_logger()

EMBED_DIM = 1536  # text-embedding-3-small

try:
    import faiss as _faiss
    _FAISS_OK = True
except ImportError:
    _faiss = None  # type: ignore
    _FAISS_OK = False

try:
    from openai import AsyncOpenAI
    _OPENAI_OK = True
except ImportError:
    AsyncOpenAI = None  # type: ignore
    _OPENAI_OK = False


class RAGService:
    """
    FAISS-backed vector store with OpenAI embeddings and GPT-4o-mini synthesis.
    """

    def __init__(self) -> None:
        self._index = None
        self._metadata: dict[int, dict] = {}
        self._counter = 0
        self._openai: "AsyncOpenAI | None" = None
        self._loaded = False

    # ── Internals ────────────────────────────────────────────────────────────

    def _get_active_clients(self) -> list[tuple["AsyncOpenAI", str, str]]:
        clients = []
        if not _OPENAI_OK:
            return clients
            
        if settings.gemini_api_key:
            clients.append((
                AsyncOpenAI(api_key=settings.gemini_api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
                "gemini-2.5-flash",
                "Gemini (Google)"
            ))
        if settings.groq_api_key:
            clients.append((
                AsyncOpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1"),
                "llama-3.1-8b-instant",
                "Groq (Llama-3.1)"
            ))
        if settings.openrouter_api_key:
            clients.append((
                AsyncOpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1"),
                "google/gemini-2.5-flash-free",
                "OpenRouter"
            ))
        return clients

    def _get_client(self):
        """First available client proxy for graceful fallback mappings."""
        c = self._get_active_clients()
        return c[0][0] if c else None

    def _get_index(self):
        if self._index is None and _FAISS_OK:
            self._index = _faiss.IndexFlatIP(EMBED_DIM)
        return self._index

    async def _embed(self, text: str) -> np.ndarray:
        """Return a 1536-dim float32 vector for the given text."""
        client = self._get_client()
        if client is None:
            logger.warning("embed_stub", reason="no OpenAI client")
            rng = np.random.default_rng(abs(hash(text)) % (2**31))
            return rng.random(EMBED_DIM).astype("float32")

        try:
            resp = await client.embeddings.create(
                input=text,
                model="text-embedding-3-small",
            )
            return np.array(resp.data[0].embedding, dtype="float32")
        except Exception as e:
            logger.warning("embed_api_error", error=str(e)[:120])
            # Fall back to deterministic stub vector so the pipeline keeps running
            rng = np.random.default_rng(abs(hash(text)) % (2**31))
            return rng.random(EMBED_DIM).astype("float32")

    def _save(self) -> None:
        idx_dir = Path(settings.faiss_index_path)
        idx_dir.mkdir(parents=True, exist_ok=True)
        if _FAISS_OK and self._index is not None:
            _faiss.write_index(self._index, str(idx_dir / "index.faiss"))
        with open(idx_dir / "metadata.pkl", "wb") as f:
            pickle.dump({"meta": self._metadata, "counter": self._counter}, f)

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        meta_path = Path(settings.faiss_index_path) / "metadata.pkl"
        idx_path = Path(settings.faiss_index_path) / "index.faiss"
        if meta_path.exists():
            with open(meta_path, "rb") as f:
                saved = pickle.load(f)
            self._metadata = saved.get("meta", {})
            self._counter = saved.get("counter", 0)
        if idx_path.exists() and _FAISS_OK:
            self._index = _faiss.read_index(str(idx_path))

    # ── Public API ────────────────────────────────────────────────────────────

    async def index_content(self, video_id: str, result: dict) -> None:
        """
        Embed and store all keyframe + transcript content for a processed video.

        Args:
            video_id: job_id used as the video identifier.
            result:   The pipeline result dict (keyframes + transcript lists).
        """
        self._load()
        idx = self._get_index()
        vectors: list[np.ndarray] = []

        # Index keyframe analyses
        for kf in result.get("keyframes", []):
            title = kf.get("slide_title", "")
            text = kf.get("extracted_text", "")
            chunk = f"[Slide: {title}] {text}".strip()
            if kf.get("code_snippets"):
                chunk += " Code: " + " ".join(kf["code_snippets"])

            vec = await self._embed(chunk)
            self._metadata[self._counter] = {
                "video_id": video_id,
                "type": "keyframe",
                "timestamp": kf.get("timestamp", 0.0),
                "text": chunk,
                "image_url": kf.get("image_url", ""),
            }
            vectors.append(vec)
            self._counter += 1

        # Index transcript in 30-second windows
        window_text = ""
        window_start = 0.0
        for seg in result.get("transcript", []):
            window_text += " " + seg.get("text", "")
            if seg.get("end", 0) - window_start >= 30.0 and window_text.strip():
                vec = await self._embed(window_text.strip())
                self._metadata[self._counter] = {
                    "video_id": video_id,
                    "type": "transcript",
                    "timestamp": window_start,
                    "text": window_text.strip(),
                }
                vectors.append(vec)
                self._counter += 1
                window_start = seg.get("end", 0)
                window_text = ""

        if vectors:
            mat = np.stack(vectors)
            if _FAISS_OK and idx is not None:
                _faiss.normalize_L2(mat)
                idx.add(mat)
            self._save()

        logger.info("rag_indexed", video_id=video_id, chunks=len(vectors))

    async def query_and_answer(
        self,
        question: str,
        video_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> dict:
        """
        Retrieve top-k relevant chunks, synthesise answer with GPT-4o-mini.

        Returns dict with 'answer' and 'sources' keys.
        """
        self._load()
        sources = await self._retrieve(question, video_ids, top_k)

        if not sources:
            return {
                "answer": "No relevant content found. Upload and process a video first.",
                "sources": [],
            }

        context = "\n\n".join(
            f"[{s['type']} @ {s['timestamp']:.1f}s] {s['text']}"
            for s in sources
        )

        clients = self._get_active_clients()
        if not clients:
            answer = (
                f"(LLM stub — add an API key in .env for real answers)\n\n"
                f"Top source: {sources[0]['text'][:200]}"
            )
        else:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a study assistant. Answer ONLY from the provided "
                        "lecture content. Always cite timestamps in your answer."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ]

            async def fetch_llm(c: "AsyncOpenAI", model: str, name: str) -> str:
                completion = await c.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=500,
                )
                txt = completion.choices[0].message.content or ""
                return f"[⚡ Fastest response via {name}]\n\n{txt}"

            tasks = [asyncio.create_task(fetch_llm(c, m, n)) for c, m, n in clients]
            
            try:
                success_answer = ""
                pending = set(tasks)
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED, timeout=12.0)
                    if not done:
                        break # timeout exhausted
                    
                    for d in done:
                        try:
                            success_answer = d.result()
                            break # We found a success!
                        except Exception as e:
                            logger.error("api_racing_provider_failed", error=str(e))
                            
                    if success_answer:
                        break # Exit the while loop
                
                # Make sure to cancel any remaining background fetch loops
                for p in pending:
                    p.cancel()
                
                if success_answer:
                    answer = success_answer
                else:
                    raise Exception("All racing providers failed or rejected the input.")
            except Exception as e:
                err_str = str(e)
                if '429' in err_str or 'insufficient_quota' in err_str:
                    answer = (
                        "⚠️ **API Quota Exceeded**: Provider free limits exhausted.\n\n"
                        f"RAG retrieval succeeded locally! Top source:\n> {sources[0]['text'][:300]}..."
                    )
                else:
                    answer = f"API error: {e}. Top chunk: {sources[0]['text'][:200]}"

        return {"answer": answer, "sources": sources}

    async def _retrieve(
        self,
        question: str,
        video_ids: list[str] | None,
        top_k: int,
    ) -> list[dict]:
        """FAISS similarity search for the question embedding."""
        idx = self._get_index()
        if not self._metadata:
            return []

        q_vec = await self._embed(question)
        q_mat = q_vec.reshape(1, -1)

        if _FAISS_OK and idx is not None and idx.ntotal > 0:
            _faiss.normalize_L2(q_mat)
            scores, indices = idx.search(q_mat, min(top_k * 2, idx.ntotal))
            hits = [
                {**self._metadata[int(i)], "score": float(s)}
                for s, i in zip(scores[0], indices[0])
                if i >= 0 and int(i) in self._metadata
            ]
        else:
            # Linear fallback (no FAISS)
            hits = list(self._metadata.values())

        # Filter by video_id if requested
        if video_ids:
            hits = [h for h in hits if h.get("video_id") in video_ids]

        return hits[:top_k]


# Singleton
rag_service = RAGService()
