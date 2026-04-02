"""
Unit tests — frame extractor (Phase 3 extended).
Run: cd backend && python -m pytest tests/unit/ -v --tb=short

Covers:
  - oppa.txt Phase 1 spec (3 required tests)
  - Extra contract checks per AGENT_RULES (every function gets >= 1 test)
"""
from __future__ import annotations

import os
import re

import numpy as np
import pytest

from services.frame_extractor import Keyframe, extract_keyframes, save_keyframes


# ── oppa.txt required tests ───────────────────────────────────────────────────

def test_extract_keyframes_returns_at_least_one(sample_video_path: str):
    """A valid video must produce at least 1 keyframe (the first frame)."""
    keyframes = extract_keyframes(sample_video_path, threshold=0.95)
    assert len(keyframes) >= 1
    assert keyframes[0].timestamp_sec == 0.0


def test_extract_keyframes_respects_max_cap(sample_video_path: str):
    """Hard cap must never be exceeded regardless of video content."""
    keyframes = extract_keyframes(sample_video_path, max_keyframes=5)
    assert len(keyframes) <= 5


def test_extract_keyframes_invalid_path():
    """Non-existent file must raise ValueError with helpful message."""
    with pytest.raises(ValueError, match="Cannot open video"):
        extract_keyframes("/nonexistent/file.mp4")


# ── Keyframe dataclass ────────────────────────────────────────────────────────

def test_keyframe_dataclass_fields():
    """Keyframe dataclass has all expected fields with correct types."""
    kf = Keyframe(
        index=0,
        timestamp_sec=0.0,
        frame=np.zeros((480, 640, 3), dtype="uint8"),
        ssim_delta=0.0,
    )
    assert kf.index == 0
    assert kf.timestamp_sec == 0.0
    assert kf.ssim_delta == 0.0
    assert kf.frame.shape == (480, 640, 3)


# ── Contract checks ───────────────────────────────────────────────────────────

def test_keyframes_sorted_by_timestamp(sample_video_path: str):
    """Keyframes must be in chronological order."""
    kfs = extract_keyframes(sample_video_path, threshold=0.80)
    ts = [kf.timestamp_sec for kf in kfs]
    assert ts == sorted(ts)


def test_keyframe_indices_sequential(sample_video_path: str):
    """Indices must form [0, 1, 2, ...] exactly."""
    kfs = extract_keyframes(sample_video_path, threshold=0.95)
    assert [kf.index for kf in kfs] == list(range(len(kfs)))


def test_first_frame_ssim_delta_is_zero(sample_video_path: str):
    """First keyframe has no previous frame, so delta must be 0.0."""
    kfs = extract_keyframes(sample_video_path, threshold=0.95)
    assert kfs[0].ssim_delta == 0.0


def test_frame_array_is_bgr_image(sample_video_path: str):
    """Each keyframe carries a 3-channel BGR numpy array."""
    kfs = extract_keyframes(sample_video_path, threshold=0.95)
    for kf in kfs:
        assert isinstance(kf.frame, np.ndarray)
        assert kf.frame.ndim == 3
        assert kf.frame.shape[2] == 3


# ── save_keyframes ────────────────────────────────────────────────────────────

def test_save_keyframes_creates_jpeg_files(sample_video_path: str, tmp_path):
    """save_keyframes writes exactly len(keyframes) JPEG files."""
    kfs = extract_keyframes(sample_video_path, max_keyframes=3)
    paths = save_keyframes(kfs, str(tmp_path / "out"))
    assert len(paths) == len(kfs)
    for p in paths:
        assert os.path.exists(p)
        assert os.path.getsize(p) > 0


def test_save_keyframes_naming_convention(sample_video_path: str, tmp_path):
    """Saved files must follow kf_NNN_T.Xs.jpg pattern."""
    kfs = extract_keyframes(sample_video_path, max_keyframes=2)
    paths = save_keyframes(kfs, str(tmp_path / "out"))
    pattern = re.compile(r"kf_\d{3}_[\d.]+s\.jpg$")
    for p in paths:
        assert pattern.search(p), f"Bad filename: {p}"


def test_save_keyframes_creates_nested_directory(sample_video_path: str, tmp_path):
    """save_keyframes must mkdir -p the output directory if it doesn't exist."""
    out_dir = str(tmp_path / "deep" / "nested")
    kfs = extract_keyframes(sample_video_path, max_keyframes=1)
    paths = save_keyframes(kfs, out_dir)
    assert len(paths) >= 1
    assert os.path.exists(paths[0])
