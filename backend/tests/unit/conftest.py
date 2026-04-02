"""
conftest.py — shared pytest fixtures for unit tests.

Provides:
  - sample_video_path: absolute path to the test MP4 in backend/tests/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── sys.path: make `services.*` importable from tests/unit/ ──────────────────
# backend/ is the working directory when pytest is invoked as:
#   cd backend && python -m pytest tests/unit/ -v
# So `services` is already findable. But add backend/ explicitly just in case.
_BACKEND_DIR = Path(__file__).parent.parent.parent  # main_cap/backend/
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_TEST_VIDEO = _BACKEND_DIR / "tests" / "test_lecture.mp4"


@pytest.fixture(scope="session")
def sample_video_path() -> str:
    """
    Return the absolute path to the bundled test video.

    Session-scoped so the path is resolved once per test run.
    Skips all tests in the session if the video is missing —
    useful in CI environments that don't have large binary fixtures.
    """
    if not _TEST_VIDEO.exists():
        pytest.skip(
            f"Test video not found: {_TEST_VIDEO}. "
            "Run tests/generate_test_video.py to create it, "
            "or copy any .mp4 file there."
        )
    return str(_TEST_VIDEO)
