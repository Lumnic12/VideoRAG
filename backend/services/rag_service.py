"""
RAG Service — FAISS vector store + multi-provider LLM racing.

Embedding strategy (in priority order):
  1. Ollama nomic-embed-text  (local, 768-dim)   — if OLLAMA_BASE_URL set
  2. OpenAI text-embedding-3-small (1536-dim)     — if any API key works
  3. Deterministic random stub                    — always works, poor quality

LLM racing strategy:
  All configured providers race in parallel; first successful response wins.
  Providers: Local Ollama → Groq → Gemini → OpenRouter
"""
from __future__ import annotations

import asyncio
import pickle
from pathlib import Path

import httpx
import numpy as np
import structlog

from core.config import settings

logger = structlog.get_logger()

# FAISS index dimension — set at startup based on which embedder is active
_EMBED_DIM_OPENAI = 1536
_EMBED_DIM_OLLAMA = 768

# FAISS — re-enabled with graceful fallback
try:
    import faiss as _faiss
    _FAISS_OK = True
    logger.info("faiss_loaded", backend="faiss-cpu")
except ImportError:
    _faiss = None
    _FAISS_OK = False
    logger.warning("faiss_not_available", fallback="numpy cosine similarity")

try:
    from openai import AsyncOpenAI
    _OPENAI_OK = True
except ImportError:
    AsyncOpenAI = None  # type: ignore
    _OPENAI_OK = False


# ── Embedding helpers ─────────────────────────────────────────────────────────

def _using_ollama_embed() -> bool:
    """True when Ollama is configured (prefer local embeddings)."""
    return bool(settings.ollama_base_url)


def _embed_dim() -> int:
    return _EMBED_DIM_OLLAMA if _using_ollama_embed() else _EMBED_DIM_OPENAI


async def _embed_via_ollama(text: str) -> np.ndarray:
    """Call Ollama /api/embeddings with nomic-embed-text."""
    # Ollama base_url is like http://host.docker.internal:11434/v1 — strip /v1
    base = settings.ollama_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base}/api/embeddings"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"model": "nomic-embed-text", "prompt": text})
            resp.raise_for_status()
            data = resp.json()
            vec = np.array(data["embedding"], dtype="float32")
            return vec
    except Exception as e:
        logger.warning("ollama_embed_error", error=str(e)[:120])
        # Deterministic fallback
        rng = np.random.default_rng(abs(hash(text)) % (2**31))
        return rng.random(_EMBED_DIM_OLLAMA).astype("float32")


async def _embed_via_openai(text: str, client: "AsyncOpenAI") -> np.ndarray:
    """Call OpenAI-compatible /embeddings endpoint."""
    try:
        resp = await client.embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )
        return np.array(resp.data[0].embedding, dtype="float32")
    except Exception as e:
        logger.warning("openai_embed_error", error=str(e)[:120])
        rng = np.random.default_rng(abs(hash(text)) % (2**31))
        return rng.random(_EMBED_DIM_OPENAI).astype("float32")


# ── RAG Service ───────────────────────────────────────────────────────────────

class RAGService:
    """FAISS-backed vector store with adaptive embedding + LLM racing."""

    def __init__(self) -> None:
        self._index = None
        self._metadata: dict[int, dict] = {}
        self._counter = 0
        self._embed_dim: int | None = None
        self._loaded = False
        self._last_mtime: float = 0.0


    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_embed_dim(self) -> int:
        if self._embed_dim is None:
            self._embed_dim = _embed_dim()
        return self._embed_dim

    def _get_index(self):
        if self._index is None and _FAISS_OK:
            self._index = _faiss.IndexFlatIP(self._get_embed_dim())
        return self._index

    def _get_chat_clients(self) -> list[tuple["AsyncOpenAI", str, str]]:
        """Return configured LLM providers — local Ollama only."""
        clients = []
        if AsyncOpenAI is None:   # openai package not installed
            return clients
        # Use ONLY local Ollama (user requested no API keys)
        if settings.ollama_base_url:
            clients.append((
                AsyncOpenAI(
                    api_key="ollama",
                    base_url=settings.ollama_base_url,
                ),
                settings.ollama_model,
                f"Local Ollama ({settings.ollama_model})",
            ))
        return clients

    async def _embed(self, text: str) -> np.ndarray:
        """Embed text using the best available provider."""
        if _using_ollama_embed():
            return await _embed_via_ollama(text)

        # Try OpenAI-compatible embedding with the first available key
        if _OPENAI_OK:
            client = None
            if settings.groq_api_key:
                # Groq doesn't support embeddings — skip
                pass
            if settings.gemini_api_key:
                client = AsyncOpenAI(
                    api_key=settings.gemini_api_key,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                )
            if client:
                return await _embed_via_openai(text, client)

        # Pure stub fallback
        logger.warning("embed_stub_random", reason="no embedding provider configured")
        rng = np.random.default_rng(abs(hash(text)) % (2**31))
        return rng.random(self._get_embed_dim()).astype("float32")

    def _save(self) -> None:
        idx_dir = Path(settings.faiss_index_path)
        idx_dir.mkdir(parents=True, exist_ok=True)
        if _FAISS_OK and self._index is not None:
            _faiss.write_index(self._index, str(idx_dir / "index.faiss"))
        # Strip raw numpy vectors before pickling — they live in the FAISS index
        meta_clean = {
            k: {kk: vv for kk, vv in v.items() if kk != "vector"}
            for k, v in self._metadata.items()
        }
        with open(idx_dir / "metadata.pkl", "wb") as f:
            pickle.dump({
                "meta": meta_clean,
                "counter": self._counter,
                "embed_dim": self._get_embed_dim(),
            }, f)

    def _load(self) -> None:
        meta_path = Path(settings.faiss_index_path) / "metadata.pkl"
        idx_path = Path(settings.faiss_index_path) / "index.faiss"
        # Re-read from disk if the file changed (handles hot-indexing of new videos)
        try:
            current_mtime = meta_path.stat().st_mtime if meta_path.exists() else 0.0
        except OSError:
            current_mtime = 0.0
        if self._loaded and current_mtime == self._last_mtime:
            return
        self._loaded = True
        self._last_mtime = current_mtime
        if meta_path.exists():
            with open(meta_path, "rb") as f:
                saved = pickle.load(f)
            self._metadata = saved.get("meta", {})
            self._counter = saved.get("counter", 0)
            # Restore dimension from saved index — if it changed, rebuild
            saved_dim = saved.get("embed_dim", _EMBED_DIM_OPENAI)
            current_dim = _embed_dim()
            if saved_dim != current_dim:
                logger.warning(
                    "faiss_dim_mismatch",
                    saved=saved_dim,
                    current=current_dim,
                    action="rebuilding index — old data lost",
                )
                self._metadata = {}
                self._counter = 0
                self._index = None
                return
            self._embed_dim = saved_dim
        if _FAISS_OK and idx_path.exists() and self._embed_dim:
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

        # ── Index keyframe analyses ───────────────────────────────────────────
        for kf in result.get("keyframes", []):
            title = kf.get("slide_title", "") or ""
            text = kf.get("extracted_text", "") or ""

            # Skip pure VLM stubs that are just error tags
            is_stub = text.startswith("[VLM") or text.startswith("[Vision")

            ts = kf.get("timestamp", 0.0)
            ts_fmt = f"{int(ts // 60)}:{int(ts % 60):02d}"

            if is_stub or not (title + text).strip():
                # Always index with a minimal timestamp chunk so the frame is searchable
                chunk = f"[Slide @ {ts:.1f}s] Frame {kf.get('index', 0) + 1}: Visual frame: {kf.get('width', 640)}x{kf.get('height', 360)}"
            else:
                chunk = f"[Slide @ {ts:.1f}s] {title}: {text}".strip()

            # Append code snippets if present
            snippets = kf.get("code_snippets", []) or []
            if snippets:
                chunk += "\nCode: " + " | ".join(s for s in snippets if s)

            # Append key concepts
            concepts = kf.get("key_concepts", []) or []
            if concepts:
                chunk += "\nConcepts: " + ", ".join(c for c in concepts if c)

            vec = await self._embed(chunk)
            self._metadata[self._counter] = {
                "video_id": video_id,
                "type": "keyframe",
                "timestamp": ts,
                "text": chunk,
                "image_url": kf.get("image_url", ""),
                "vector": vec,
            }
            vectors.append(vec)
            self._counter += 1


        # ── Index transcript segments ─────────────────────────────────────────
        transcript = result.get("transcript", [])
        logger.info("rag_transcript_segments", count=len(transcript))

        # Index each individual segment (for fine-grained retrieval)
        for seg in transcript:
            seg_text = (seg.get("text") or "").strip()
            if not seg_text or seg_text.startswith("["):
                continue  # skip stubs
            ts = seg.get("start", 0.0)
            chunk = f"[Transcript @ {ts:.1f}s] {seg_text}"
            vec = await self._embed(chunk)
            self._metadata[self._counter] = {
                "video_id": video_id,
                "type": "transcript",
                "timestamp": ts,
                "text": chunk,
                "vector": vec,
            }
            vectors.append(vec)
            self._counter += 1

        # Also index in 15-second windows for broader context retrieval
        window_text = ""
        window_start = 0.0
        WINDOW_SEC = 15.0
        for seg in transcript:
            seg_text = (seg.get("text") or "").strip()
            if not seg_text or seg_text.startswith("["):
                continue
            seg_end = seg.get("end", seg.get("start", 0) + 5)
            window_text += " " + seg_text
            if seg_end - window_start >= WINDOW_SEC and window_text.strip():
                chunk = f"[Transcript {window_start:.1f}s–{seg_end:.1f}s] {window_text.strip()}"
                vec = await self._embed(chunk)
                self._metadata[self._counter] = {
                    "video_id": video_id,
                    "type": "transcript_window",
                    "timestamp": window_start,
                    "text": chunk,
                    "vector": vec,
                }
                vectors.append(vec)
                self._counter += 1
                window_start = seg_end
                window_text = ""

        # Flush remaining window
        if window_text.strip() and len(window_text.strip()) > 20:
            chunk = f"[Transcript {window_start:.1f}s+] {window_text.strip()}"
            vec = await self._embed(chunk)
            self._metadata[self._counter] = {
                "video_id": video_id,
                "type": "transcript_window",
                "timestamp": window_start,
                "text": chunk,
            }
            vectors.append(vec)
            self._counter += 1

        # ── Index structured transcript sections (LLM-synthesised) ────────────
        # These are the HIGH-QUALITY chunks: topic title + structured summary +
        # key terms. They give the embedding model rich semantic text instead of
        # raw choppy speech, dramatically improving retrieval precision.
        structured = result.get("structured_transcript", [])
        logger.info("rag_structured_sections", count=len(structured))

        for sec in structured:
            topic   = (sec.get("topic") or "").strip()
            summary = (sec.get("summary") or "").strip()
            terms   = sec.get("key_terms") or []
            ts      = sec.get("start", 0.0)

            if not (topic or summary):
                continue

            ts_fmt = f"{int(ts // 60)}:{int(ts % 60):02d}"
            chunk = f"[Lecture @ {ts_fmt}] Topic: {topic}\nSummary: {summary}"
            if terms:
                chunk += "\nKey Terms: " + ", ".join(t for t in terms if t)

            vec = await self._embed(chunk)
            self._metadata[self._counter] = {
                "video_id": video_id,
                "type": "structured_transcript",
                "timestamp": ts,
                "text": chunk,
                "topic": topic,
                "vector": vec,
            }
            vectors.append(vec)
            self._counter += 1

        if vectors:
            mat = np.stack(vectors)
            if _FAISS_OK and idx is not None:
                _faiss.normalize_L2(mat)
                idx.add(mat)
            self._save()

        logger.info("rag_indexed", video_id=video_id, chunks=len(vectors),
                    keyframes=len(result.get("keyframes", [])),
                    transcript_segs=len(transcript),
                    structured_sections=len(structured))

    async def query_and_answer(
        self,
        question: str,
        video_ids: list[str] | None = None,
        top_k: int = 5,
        chat_history: list[dict] | None = None,
    ) -> dict:
        """
        Retrieve top-k relevant chunks, synthesise answer via LLM racing.
        Supports multi-turn conversation via chat_history.

        Args:
            question:     Current user question.
            video_ids:    Optional list of video IDs to scope retrieval.
            top_k:        Number of context chunks to retrieve.
            chat_history: List of {role, content} dicts from prior conversation turns.

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

        clients = self._get_chat_clients()
        if not clients:
            answer = (
                "(LLM stub — configure OLLAMA_BASE_URL or an API key in .env)\n\n"
                f"Top RAG source: {sources[0]['text'][:300]}"
            )
        else:
            system_msg = {
                "role": "system",
                "content": (
                    "You are an expert tutor and study assistant analyzing video/lecture content. "
                    "You have access to extracted keyframe descriptions and audio transcripts from the video. "
                    "When answering:\n"
                    "- Base your answers ONLY on the provided video context below.\n"
                    "- DO NOT use speculative language like 'will likely explain', 'probably', or 'might'. Speak definitively about what IS in the context.\n"
                    "- Cite specific timestamps (e.g., '@2:30') when referencing content.\n"
                    "- If asked to teach or explain, break concepts down clearly with examples.\n"
                    "- For follow-up questions, reference your prior answers and the conversation history.\n"
                    "- If the context doesn't contain enough information to summarize the whole video, state exactly what the provided context covers.\n"
                    "- Use markdown formatting: **bold**, `code`, bullet points, etc.\n\n"
                    f"=== VIDEO CONTEXT ===\n{context}\n=== END CONTEXT ==="
                ),
            }

            # Build multi-turn messages array
            messages = [system_msg]

            # Add conversation history (if any)
            if chat_history:
                for msg in chat_history[-10:]:  # Keep last 10 turns to avoid token overflow
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role in ("user", "assistant") and content:
                        messages.append({"role": role, "content": content})

            # Add the current question
            messages.append({"role": "user", "content": question})

            async def fetch_llm(c: "AsyncOpenAI", model: str, name: str) -> str:
                completion = await c.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1200,
                    timeout=600.0,
                )
                txt = completion.choices[0].message.content or ""
                return f"[⚡ via {name}]\n\n{txt}"

            tasks = [asyncio.create_task(fetch_llm(c, m, n)) for c, m, n in clients]
            answer = ""
            pending = set(tasks)
            try:
                while pending:
                    done, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED, timeout=600.0
                    )
                    if not done:
                        break  # timeout
                    for d in done:
                        try:
                            answer = d.result()
                            break
                        except Exception as e:
                            logger.error("llm_race_provider_failed", error=str(e)[:200])
                    if answer:
                        break
            finally:
                for p in pending:
                    p.cancel()

            if not answer:
                answer = (
                    "⚠️ All LLM providers failed or timed out.\n\n"
                    f"Top RAG source: {sources[0]['text'][:300]}"
                )

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
            # Pure Numpy cosine similarity linear scanner
            hits = []
            q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-10)
            for md in self._metadata.values():
                v = md.get("vector")
                if v is not None:
                    v_norm = v / (np.linalg.norm(v) + 1e-10)
                    score = float(np.dot(q_norm, v_norm))
                    cc = md.copy()
                    cc.pop("vector", None)
                    hits.append({**cc, "score": score})
            hits.sort(key=lambda x: x["score"], reverse=True)

        # Filter by video_id if requested
        if video_ids:
            hits = [h for h in hits if h.get("video_id") in video_ids]

        return hits[:top_k]


# Singleton
rag_service = RAGService()
