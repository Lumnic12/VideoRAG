# Architecture Decision Records

## ADR-001: Python SSIM Before C++
**Date**: 2026-04-01  
**Status**: Accepted — C++ bindings added in Phase 3  
**Deciders**: Human + Agent

### Context
The SSIM keyframe comparison is the CPU-bound performance bottleneck in the pipeline. C++ via pybind11 would offer ~5x speedup. However, C++ bindings add significant build complexity:
- Requires MSVC / GCC + OpenCV development headers
- Adds a compile step to setup that CI and new developers must replicate
- Delays feature validation on real videos

### Decision
Build and **fully validate** the pipeline in pure Python first (Phases 0–2). Add C++ bindings in Phase 3 after the Python MVP is confirmed working end-to-end.

**Phase 3 implementation**: `ssim_cpp` pybind11 module built via `cpp_bindings/setup.py` (no cmake required on Windows with MSYS2/MinGW or MSVC). The Python fallback is always retained via graceful `try: import ssim_cpp` block in `frame_extractor.py`.

### Consequences
- ✅ Initial demo pipeline works without any C++ toolchain
- ✅ C++ upgrade is transparent — same `extract_keyframes()` API
- ⚠️  SSIM computation on a 10-min video takes ~8–15s in Python vs ~2–3s in C++
- The fallback means the system **never breaks** due to a missing compiled extension

### Build instructions (Windows with MSYS2)
```bash
# In MSYS2 MinGW64 shell:
pacman -S mingw-w64-x86_64-gcc mingw-w64-x86_64-opencv mingw-w64-x86_64-python-pybind11

cd cpp_bindings
python setup.py build_ext --inplace
copy ssim_cpp*.pyd ..\backend\services\
```

---

## ADR-002: FAISS Over Pinecone for MVP
**Date**: 2026-04-01  
**Status**: Accepted  
**Deciders**: Human + Agent

### Context
The RAG retrieval layer needs a vector store. Two viable options:

| Criterion | FAISS (local) | Pinecone (managed) |
|-----------|---------------|--------------------|
| Setup time | 0 (pip install) | 30 min (account + API key) |
| Network dependency during demo | None | Yes |
| Data privacy | Local | Uploaded to cloud |
| Scale | Up to ~1M vectors locally | Unlimited |
| Cost | Free | Free tier: 1 index, 1M vectors |

### Decision
Use **FAISS locally** (`faiss-cpu`) for the MVP. Swap to Pinecone only if production load exceeds local capacity (>500k vectors) or multi-machine access is needed.

### Consequences
- ✅ Zero network dependency during capstone demo
- ✅ No account setup required for graders running locally
- ✅ Index persists to `data/faiss_index/` between runs
- ⚠️  Index is not backed up — losing `data/` loses all embedded content
- ⚠️  No managed replication — single machine only

---

## ADR-003: Celery Pool=Solo on Windows
**Date**: 2026-04-02  
**Status**: Accepted  
**Deciders**: Agent (Windows compatibility constraint)

### Context
Celery's default `prefork` multiprocessing pool is not supported on Windows because Python's `multiprocessing` module uses `spawn` (not `fork`), which causes Celery worker bootstrap failures:

```
[ERROR/MainProcess] Task handler raised error: ValueError: not enough values to unpack
```

### Decision
Use `--pool=solo` for Windows development. This runs tasks synchronously in the worker process — suitable for a demo processing one video at a time.

**Implementation**: `start_worker.ps1` sets `--pool=solo` automatically. `services/celery_worker.py` applies it programmatically when `sys.platform == "win32"`.

For **production** (Linux/Docker), the default `prefork` pool is used — no change needed in `docker-compose.yml`.

### Consequences
- ✅ Worker starts reliably on any Windows machine
- ✅ Zero code changes needed for production Linux/Docker deployment  
- ⚠️  `solo` pool processes one task at a time (fine for single-user demo)
- For concurrent processing on Windows: `pip install gevent` and use `--pool=gevent --concurrency=4`
