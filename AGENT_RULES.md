# AGENT_RULES.md — VideoRAG Agent Operating Rules

## Core Principles

1. **Phase-gated development**: Never skip to Phase N+2. Complete Phase N, verify, then advance.
2. **ADRs are law**: Follow DECISIONS.md. If you want to deviate, add a new ADR first.
3. **Always verify before advancing**: Each Phase must pass its verification criteria before CURRENT PHASE is incremented in AGENT_CONTEXT.md.
4. **Prefer working over perfect**: Ship a tested stub before a partially-implemented real feature.
5. **Keep AGENT_CONTEXT.md up-to-date**: After every task, update what was built and what Phase 1.X should be.

---

## Workflow Loop

```
Read AGENT_CONTEXT.md
  → Identify CURRENT PHASE + current task
  → Implement task
  → Run verification
  → Update AGENT_CONTEXT.md (file tree, bugs, next task)
  → Advance phase if warranted
```

---

## Quality Gates per Phase

| Phase | Gate |
|-------|------|
| 0 | `/health` returns 200; frontend renders; Redis PING ok |
| 1 | Real MP4 upload succeeds; Celery extracts keyframes; task status returns `done` |
| 2 | `/api/v1/query` returns grounded answer with real FAISS scores > 0.5 |
| 3 | SSIM delta threshold is tunable via env var; C++ stub in place |

---

## Code Standards

- **Python**: type hints on all public functions; docstrings on services.
- **TypeScript**: strict mode; no `any` on API layer types.
- **Tests**: every new endpoint gets at least one happy-path test and one error test.
- **CORS**: never open to `*` in production; use env-based allow list.
- **Secrets**: never hardcode. Use `.env` / environment variables.

---

## Escalation

If a task requires changes not covered by existing ADRs (e.g., switching to Pinecone, adding auth), write a new ADR in DECISIONS.md and pause for human review.
