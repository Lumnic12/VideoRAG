"""
celery_worker.py — Celery worker entrypoint with Windows --pool=solo default.

Usage:
    cd backend
    python -m celery -A services.celery_worker worker --loglevel=info

This module re-exports the celery_app from task_orchestrator and sets
pool=solo automatically when running on Windows so you don't need to
pass --pool=solo manually every time.
"""
from __future__ import annotations

import os
import sys

# On Windows, force solo pool to avoid multiprocessing bootstrap errors.
# This must be set before Celery initialises its worker machinery.
if sys.platform == "win32":
    os.environ.setdefault("FORKED_BY_MULTIPROCESSING", "1")

from services.task_orchestrator import celery_app  # noqa: F401  re-export

# Apply Windows-specific worker defaults programmatically.
# These can still be overridden by CLI flags.
if sys.platform == "win32":
    celery_app.conf.update(
        worker_pool="solo",
        worker_concurrency=1,
    )

__all__ = ["celery_app"]
