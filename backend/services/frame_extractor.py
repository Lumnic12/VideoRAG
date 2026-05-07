"""
SSIM-based keyframe extraction.
Drops perceptually identical frames to reduce thousands of frames
to semantic keyframes per lecture video.

ADR-001: Phase 3 — C++ bindings via pybind11 are tried first when the
compiled ssim_cpp extension is present in sys.path / backend/services/.
Falls back gracefully to pure Python (skimage) if not available.

Keyframe budget:
  - Automatically scales with video duration: ~1 keyframe per 15 s
  - Hard ceiling: 120 keyframes (avoids memory blowup on very long videos)
  - Hard floor: 10 keyframes (always get at least 10 even for short clips)
  - Mandatory time-sample fallback: if SSIM doesn't fire, force a keyframe
    every `force_interval_sec` seconds so the whole video is always covered.

Performance:
  - Python (skimage SSIM): baseline
  - C++ (ssim_cpp):        ~5x faster on a 10-min 1080p lecture video
"""
from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass
from pathlib import Path

import structlog
from skimage.metrics import structural_similarity as ssim

logger = structlog.get_logger()

# ── C++ acceleration (Phase 3) ────────────────────────────────────────────────
try:
    import ssim_cpp as _ssim_cpp
    _CPP_AVAILABLE = True
    logger.info("ssim_cpp_loaded", backend="C++/pybind11")
except ImportError:
    _ssim_cpp = None  # type: ignore
    _CPP_AVAILABLE = False
    logger.debug("ssim_cpp_not_found", backend="Python/numpy (Phase 2 fast-path)")


# ── Fast OpenCV SSIM ──────────────────────────────────────────────────────────
_SSIM_C1 = (0.01 * 255) ** 2   # 6.5025
_SSIM_C2 = (0.03 * 255) ** 2   # 58.5225
_SSIM_KSIZE = (11, 11)
_SSIM_SIGMA = 1.5


def _ssim_numpy(img1: np.ndarray, img2: np.ndarray) -> float:
    """
    Fast SSIM using cv2.GaussianBlur — matches skimage defaults.
    Runs ~8-15x faster than skimage.structural_similarity on 640px grayscale input.
    """
    i1 = img1.astype(np.float32)
    i2 = img2.astype(np.float32)

    def blur(x: np.ndarray) -> np.ndarray:
        return cv2.GaussianBlur(x, _SSIM_KSIZE, _SSIM_SIGMA)

    mu1    = blur(i1)
    mu2    = blur(i2)
    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2

    s1_sq = blur(i1 * i1) - mu1_sq
    s2_sq = blur(i2 * i2) - mu2_sq
    s12   = blur(i1 * i2) - mu1_mu2

    num = (2.0 * mu1_mu2 + _SSIM_C1) * (2.0 * s12 + _SSIM_C2)
    den = (mu1_sq + mu2_sq + _SSIM_C1) * (s1_sq + s2_sq + _SSIM_C2)
    return float(cv2.mean(num / den)[0])


def _compute_max_keyframes(duration_sec: float) -> int:
    """
    Automatically calculate a sensible keyframe budget based on video duration.

    Strategy: ~1 keyframe per 5 seconds, clamped between 10 and 200.

    Examples:
      1-minute  video → 12  keyframes
      3-minute  video → 36  keyframes
      7-minute  video → 84  keyframes
      30-minute video → 200 keyframes  (ceiling)
    """
    budget = max(10, min(200, int(duration_sec / 5)))
    return budget


@dataclass
class Keyframe:
    """A single extracted keyframe."""
    index: int
    timestamp_sec: float
    frame: np.ndarray          # BGR numpy array — NOT serialised
    ssim_delta: float          # 1 - SSIM score vs previous keyframe


def extract_keyframes(
    video_path: str,
    threshold: float = 0.95,
    min_interval_sec: float = 2.0,
    max_keyframes: int = 0,          # 0 = auto-compute from duration
    resize_width: int = 640,
    force_interval_sec: float = 30.0,  # force a keyframe every N seconds even without scene change
) -> list[Keyframe]:
    """
    Core SSIM loop — extracts semantically distinct keyframes across the
    ENTIRE video duration.

    Uses C++ ssim_cpp extension when compiled (Phase 3), falls back to
    pure Python/numpy automatically.

    Args:
        video_path:          Path to .mp4 / .mov / .avi / .mkv
        threshold:           SSIM score ABOVE which frames are considered identical.
                             0.95 = 5% structural difference triggers capture.
        min_interval_sec:    Minimum gap between keyframes (dedup guard).
        max_keyframes:       Hard cap. 0 = auto-compute from duration
                             (~1 per 15 s, capped at 120).
        resize_width:        Downscale width for SSIM speed.
        force_interval_sec:  If no scene change detected for this many seconds,
                             force-capture a frame anyway. Ensures full coverage
                             of talking-head or low-motion videos.

    Returns:
        List of Keyframe objects, sorted by timestamp, covering the full video.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    # Auto-compute max_keyframes from duration if not provided
    effective_max = max_keyframes if max_keyframes > 0 else _compute_max_keyframes(duration_sec)

    logger.info(
        "extraction_started",
        path=video_path,
        fps=round(fps, 2),
        total_frames=total_frames,
        duration_sec=round(duration_sec, 1),
        threshold=threshold,
        max_keyframes=effective_max,
        force_interval_sec=force_interval_sec,
        backend="C++/pybind11" if _CPP_AVAILABLE else "Python/numpy-fast",
    )

    # ── Auto-scale min_interval so frames cover the FULL video ────────────────
    # Target: budget frames spread across duration_sec with ~60% density
    # e.g. 17 min (1024s) / 68 frames * 0.6 ≈ 9s min gap → full coverage
    auto_min_interval = max(min_interval_sec, (duration_sec / effective_max) * 0.6)
    if auto_min_interval > min_interval_sec:
        logger.info(
            "min_interval_scaled",
            original=min_interval_sec,
            scaled=round(auto_min_interval, 1),
            reason=f"{duration_sec:.0f}s / {effective_max} frames",
        )
    min_interval_sec = auto_min_interval

    # ── Auto-scale force_interval for longer videos ───────────────────────────
    # For 17 min: force every 60s. For 1 min: force every 20s.
    effective_force_interval = max(force_interval_sec, duration_sec / effective_max * 1.2)


    # ── C++ fast-path (Phase 3) ───────────────────────────────────────────────
    if _CPP_AVAILABLE and _ssim_cpp is not None:
        try:
            cpp_results = _ssim_cpp.extract_keyframes(
                video_path,
                threshold=threshold,
                min_interval=min_interval_sec,
                max_keyframes=effective_max,
                resize_width=resize_width,
            )
            keyframes: list[Keyframe] = []
            
            # Use sequential grabbing instead of unstable cap.set()
            current_idx = 0
            for r in cpp_results:
                seek_idx = int(r.timestamp_sec * fps)
                
                # Safely skip to the target index
                while current_idx < seek_idx:
                    if not cap.grab():
                        break
                    current_idx += 1
                    
                if current_idx != seek_idx:
                    continue  # Video ended or grab failed
                    
                ret, frame = cap.read()
                current_idx += 1
                if not ret:
                    continue
                    
                keyframes.append(Keyframe(
                    index=r.index,
                    timestamp_sec=round(r.timestamp_sec, 2),
                    frame=frame.copy(),
                    ssim_delta=round(r.ssim_delta, 4),
                ))
            cap.release()
            logger.info("extraction_complete", keyframes_found=len(keyframes), backend="C++")
            return keyframes
        except Exception as exc:
            logger.warning("cpp_path_failed", error=str(exc), fallback="Python/numpy")
            cap.release()
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise ValueError(f"Cannot reopen video: {video_path}")

    # ── Python / numpy fast-path ──────────────────────────────────────────────
    # Sample every 0.5 s — 30fps → read every ~15th frame
    sample_interval = max(1, int(fps // 2))
    keyframes = []
    prev_gray: np.ndarray | None = None
    frame_idx = 0
    last_forced_ts: float = -effective_force_interval  # so first frame is always captured

    try:
        current_idx = 0
        while True:
            # Safely skip frames without using cap.set (which breaks on long MP4s)
            while current_idx < frame_idx:
                ret = cap.grab()
                if not ret:
                    break
                current_idx += 1
                
            ret, frame = cap.read()
            current_idx += 1
            if not ret:
                break

            timestamp = round(frame_idx / fps, 2)
            h, w = frame.shape[:2]
            scale = resize_width / w
            small = cv2.resize(frame, (resize_width, int(h * scale)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            # Always capture the very first frame
            if prev_gray is None:
                keyframes.append(Keyframe(
                    index=0,
                    timestamp_sec=0.0,
                    frame=frame.copy(),
                    ssim_delta=0.0,
                ))
                prev_gray = gray
                last_forced_ts = 0.0
                frame_idx += sample_interval
                continue

            score = _ssim_numpy(prev_gray, gray)
            time_since_last = timestamp - keyframes[-1].timestamp_sec
            time_since_forced = timestamp - last_forced_ts

            # Capture if: scene change detected  OR  forced interval elapsed
            scene_change = (score < threshold) and (time_since_last >= min_interval_sec)
            forced = (time_since_forced >= effective_force_interval) and (time_since_last >= min_interval_sec)

            if scene_change or forced:
                kf = Keyframe(
                    index=len(keyframes),
                    timestamp_sec=timestamp,
                    frame=frame.copy(),
                    ssim_delta=round(1.0 - score, 4),
                )
                keyframes.append(kf)
                prev_gray = gray
                if forced and not scene_change:
                    last_forced_ts = timestamp
                logger.debug(
                    "keyframe_captured",
                    index=kf.index,
                    timestamp=timestamp,
                    ssim=round(score, 4),
                    reason="force" if (forced and not scene_change) else "scene_change",
                )

                # Stop only when we've hit the absolute cap
                if len(keyframes) >= effective_max:
                    logger.warning(
                        "max_keyframes_reached",
                        cap=effective_max,
                        at_timestamp=timestamp,
                        total_duration=round(duration_sec, 1),
                    )
                    break

            frame_idx += sample_interval
    finally:
        cap.release()

    logger.info(
        "extraction_complete",
        keyframes_found=len(keyframes),
        coverage_pct=round(100 * (keyframes[-1].timestamp_sec if keyframes else 0) / max(duration_sec, 1), 1),
        backend="Python/numpy-fast",
    )
    return keyframes


def save_keyframes(keyframes: list[Keyframe], output_dir: str) -> list[str]:
    """
    Persist keyframe images to disk as JPEG.

    Args:
        keyframes:   Extracted keyframes (must have .frame set).
        output_dir:  Directory to write images into (created if missing).

    Returns:
        List of absolute file paths.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for kf in keyframes:
        filename = f"kf_{kf.index:03d}_{kf.timestamp_sec:.1f}s.jpg"
        path = str(out / filename)
        cv2.imwrite(path, kf.frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        paths.append(path)
    return paths
