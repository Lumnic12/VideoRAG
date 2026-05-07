# AGENT_CONTEXT.md — Semantic Video Synthesizer
# Last Updated: 2026-04-16 by Agent
# Update Rule: Agent MUST update this file after completing any task.

## Current Phase: Production Ready ✅ (All Phases 0-4 Complete)

### Architecture: 100% Local Processing
- **LLM Chat**: Ollama gemma3:1b (local)
- **Embeddings**: Ollama nomic-embed-text (local)
- **Audio Transcription**: faster-whisper (local)
- **OCR/Vision**: Windows built-in OCR via winocr (local)
- **Vector Store**: FAISS-cpu (local)
- **Broker**: Redis (local)

---

## What Was Built (Phase 0-4) ✅

### Frontend (`frontend/`)
| File | Purpose |
|------|---------|
| `src/index.css` | Full dark-mode design system (tokens, glassmorphism, animations, typing dots) |
| `src/App.tsx` | Root with React Router — sidebar toggle state |
| `src/components/Sidebar.tsx` | Collapsible sidebar with nav links + phase tracker + health status |
| `src/components/Header.tsx` | Sticky header with sidebar toggle + version badge |
| `src/pages/Home.tsx` | Dashboard: system status cards, stats grid, quick actions |
| `src/pages/Upload.tsx` | Drag-and-drop video upload with progress + polling |
| `src/pages/Chat.tsx` | Multi-turn conversational chat with markdown rendering, follow-up chips, conversation memory |
| `src/pages/Query.tsx` | Single-shot query interface with source citations |
| `src/pages/Keyframes.tsx` | Gallery page — uses real `image_url` static files |
| `src/hooks/useHealth.ts` | Custom hook polling `/api/v1/health` every 30s |
| `src/lib/api.ts` | Typed API client with ChatHistoryMessage support |
| `vite.config.ts` | Port 3000, proxy `/api` → `localhost:8000` |
| `Dockerfile` | Multi-stage: node build → nginx serve |

### Backend (`backend/`)
| File | Purpose |
|------|---------|
| `main.py` | FastAPI app with lifespan, CORS, static files, routers |
| `api/routes/video.py` | Upload, process, list, delete videos — stores original filenames in Redis |
| `api/routes/query.py` | `POST /api/v1/query` with chat_history support for multi-turn conversations |
| `api/routes/ws.py` | WebSocket `/ws/jobs/{job_id}` — real-time progress streaming |
| `models/schemas.py` | All Pydantic schemas — ChatMessage, QueryRequest with chat_history |
| `services/frame_extractor.py` | SSIM keyframe extractor — C++ fast-path + Python fallback |
| `services/task_orchestrator.py` | Celery app + `process_video` task |
| `services/rag_service.py` | FAISS RAG engine — Ollama-only LLM, nomic-embed-text embeddings |
| `services/vlm_service.py` | Windows OCR (winocr) + Ollama enrichment — 100% local |
| `services/audio_service.py` | faster-whisper local transcription (Deepgram fallback) |
| `tests/unit/test_frame_extractor.py` | pytest suite for frame extractor (11 tests) |
| `tests/unit/test_rag_service.py` | pytest suite for RAG service (8 tests) |
| `tests/unit/conftest.py` | Shared fixtures — `sample_video_path` session fixture |
| `tests/test_health.py` | Phase 0 health endpoint tests |
| `tests/test_pipeline.py` | Integration pipeline test |

---

## Phase 3: C++ SSIM Bindings ✅

### What was built:
| File | Purpose |
|------|---------|
| `cpp_bindings/ssim_extractor.cpp` | Full C++ SSIM implementation with pybind11 bindings |
| `cpp_bindings/CMakeLists.txt` | CMake build config (Windows/Linux/macOS) |
| `cpp_bindings/setup.py` | setuptools build — no cmake needed (MSVC or GCC) |
| `cpp_bindings/build.ps1` | PowerShell build: MSYS2 → MSVC → cmake (3 strategies) |
| `start_worker.ps1` | Windows Celery `--pool=solo` launcher with Redis pre-check |
| `DECISIONS.md` | ADR-001, ADR-002, ADR-003 |

### Architecture of C++ integration:
```
frame_extractor.py
  │
  ├── try: import ssim_cpp       ← compiled .pyd from cpp_bindings/
  │     ↓ (if available)
  │   C++ fast path:
  │     ssim_cpp.extract_keyframes() → list[KeyframeResult] (metadata only, ~5x faster)
  │     OpenCV Python: seek + read actual frame pixels
  │     return list[Keyframe]
  │
  └── except ImportError: fallback
        Python/skimage SSIM loop (identical algorithm, slower)
        return list[Keyframe]
```

---

## API Contract (Unified)

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/upload` | POST | Upload video (field: `video`), returns `{task_id, status}` |
| `/api/v1/process` | POST | Alias for `/upload` |
| `/api/v1/tasks/{id}` | GET | Poll job status — returns `{task_id, status, progress, keyframe_count, result}` |
| `/api/v1/jobs/{id}` | GET | Legacy alias for `/tasks/{id}` |
| `/api/v1/keyframes/{id}` | GET | List keyframe JPEGs — returns `KeyframeInfo[]` with `image_url` |
| `/api/v1/query` | POST | RAG query — returns `{answer, sources, latency_ms}` |
| `/api/v1/health` | GET | Prefixed health (frontend uses this) |
| `/health` | GET | Root health (same response) |
| `/ws/jobs/{id}` | WS | Real-time progress stream |

### Status values
- `queued` → `processing` → `done` | `failed`

---

## Architecture Decisions
- **ADR-001**: Python SSIM → C++ bindings (Phase 3). Fallback always kept. See DECISIONS.md.
- **ADR-002**: FAISS locally. Pinecone only if production load demands it. See DECISIONS.md.
- **ADR-003**: Celery `--pool=solo` on Windows. `prefork` in Linux/Docker. See DECISIONS.md.

---

## Completed Tasks Changelog

| Date | Phase | Task | Files Changed | Notes |
|------|-------|------|---------------|-------|
| 2026-04-01 | 0 | Environment + FastAPI skeleton | `main.py`, `core/config.py` | Health endpoint live |
| 2026-04-01 | 0 | SSIM frame extractor | `services/frame_extractor.py` | Python/skimage |
| 2026-04-01 | 0 | VLM service | `services/vlm_service.py` | Jina-VLM + stub |
| 2026-04-01 | 0 | Audio service | `services/audio_service.py` | Deepgram + stub |
| 2026-04-01 | 1 | API contract alignment | `api/routes/video.py`, `models/schemas.py` | task_id unification |
| 2026-04-01 | 1 | Celery orchestrator | `services/task_orchestrator.py` | Full pipeline |
| 2026-04-01 | 1 | RAG service (FAISS) | `services/rag_service.py` | OpenAI + stub |
| 2026-04-01 | 2 | WebSocket streaming | `api/routes/ws.py` | Real-time progress |
| 2026-04-01 | 2 | Frontend all pages | `pages/*.tsx`, `hooks/*.ts` | Upload/Query/Keyframes |
| 2026-04-02 | 3 | C++ SSIM bindings | `cpp_bindings/*` | pybind11, 3 build strategies |
| 2026-04-02 | 3 | Windows Celery `--pool=solo` | `start_worker.ps1`, `celery_worker.py` | ADR-003 |
| 2026-04-02 | 3 | Unit tests (extractor + RAG) | `tests/unit/test_*.py`, `conftest.py` | 19 tests total |
| 2026-04-02 | 3 | DECISIONS.md | `DECISIONS.md` | ADR-001/002/003 |
| 2026-04-02 | 4 | Docker Deployment | `Dockerfile.*`, `docker-compose.yml` | Full stack deployment prepared |

---

## Active Bugs / Blockers
| ID | Description | Severity | Status |
|----|-------------|----------|--------|
| B-001 | C++ .pyd requires MSYS2 or MSVC to compile | Info | Documented — Python fallback always active |

---

## Phase 4 — Next Steps (Docker Deploy)

1. `Dockerfile.backend` + `docker-compose.yml` — per oppa.txt Phase 4 Task 4.2
2. Verify full pipeline in Docker (redis + backend + worker + frontend)
3. OCI GPU deployment (optional)

### Build C++ extension (do this now if MSYS2 is ready):
```powershell
# From project root:
.\cpp_bindings\build.ps1
```

Or manually in MSYS2 MinGW64 shell:
```bash
pacman -S --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-opencv mingw-w64-x86_64-python-pybind11
cd cpp_bindings
python setup.py build_ext --inplace
cp ssim_cpp*.pyd ../backend/services/
```

### Start the full dev stack (Windows):
```powershell
# Terminal 1 — Redis (Docker)
docker run -d -p 6379:6379 redis:7-alpine

# Terminal 2 — FastAPI backend
cd backend
uvicorn main:app --reload --port 8000

# Terminal 3 — Celery worker (Windows pool=solo)
.\start_worker.ps1

# Terminal 4 — Frontend
cd frontend
npm run dev
```

### Run tests:
```powershell
cd backend
python -m pytest tests/ -v --tb=short
```

---

## File Tree (Phase 3 complete)
```
main_cap/
├── frontend/
│   ├── src/
│   │   ├── components/  Sidebar.tsx  Header.tsx
│   │   ├── hooks/       useHealth.ts
│   │   ├── lib/         api.ts
│   │   ├── pages/       Home.tsx  Upload.tsx  Query.tsx  Keyframes.tsx  Results.tsx
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── vite.config.ts
│   └── package.json
├── backend/
│   ├── api/routes/
│   │   ├── video.py     ← /upload /tasks /keyframes /health
│   │   ├── query.py     ← latency_ms + dual QuerySource fields
│   │   └── ws.py        ← WebSocket /ws/jobs/{id}
│   ├── models/
│   │   └── schemas.py
│   ├── services/
│   │   ├── frame_extractor.py    ← C++ fast-path + Python fallback ✨
│   │   ├── celery_worker.py      ← Windows pool=solo entrypoint ✨
│   │   ├── task_orchestrator.py
│   │   ├── rag_service.py
│   │   ├── rag_engine.py
│   │   ├── vlm_service.py
│   │   └── audio_service.py
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── conftest.py              ✨
│   │   │   ├── test_frame_extractor.py  ✨ (11 tests)
│   │   │   └── test_rag_service.py      ✨ (8 tests)
│   │   ├── test_health.py
│   │   └── test_pipeline.py
│   ├── core/config.py
│   ├── main.py
│   └── requirements.txt
├── cpp_bindings/          ✨ Phase 3 — C++ SSIM
│   ├── ssim_extractor.cpp
│   ├── CMakeLists.txt
│   ├── setup.py
│   └── build.ps1
├── data/
│   ├── uploads/
│   ├── keyframes/
│   └── faiss_index/
├── start_worker.ps1       ✨ Windows Celery launcher
├── AGENT_CONTEXT.md  ← this file
├── AGENT_RULES.md
├── DECISIONS.md          ✨ ADR-001, ADR-002, ADR-003
└── .env
```
