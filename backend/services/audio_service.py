"""
Audio transcription service.
Extracts audio from video via ffmpeg, transcribes with best available provider.

Provider priority:
  1. Deepgram nova-2 (if DEEPGRAM_API_KEY set) — fastest, cloud-based
  2. Local Whisper via faster-whisper (free, runs on CPU) — ~10-30s for 10-min video
  3. Stub fallback — returns placeholder segments

Graceful stubs:
- ffmpeg missing  → returns empty transcript with warning
- All providers unavailable → returns stub segments
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

from core.config import settings

logger = structlog.get_logger()

# Check for faster-whisper availability
try:
    from faster_whisper import WhisperModel
    _WHISPER_OK = True
except ImportError:
    _WHISPER_OK = False
    logger.debug("faster_whisper_not_installed", hint="pip install faster-whisper for local transcription")


@dataclass
class TranscriptSegment:
    """A single timestamped speech segment."""

    start: float
    end: float
    text: str


def _ffmpeg_available() -> bool:
    """Check if ffmpeg is on PATH."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def extract_audio(video_path: str, output_dir: str) -> str | None:
    """
    Extract 16 kHz mono WAV audio track from a video file using ffmpeg.

    Args:
        video_path:  Path to source video.
        output_dir:  Directory where audio.wav will be written.

    Returns:
        Path to audio.wav, or None if ffmpeg is unavailable.
    """
    if not _ffmpeg_available():
        logger.warning("ffmpeg_missing", msg="Install ffmpeg to enable audio transcription")
        return None

    audio_path = str(Path(output_dir) / "audio.wav")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn",                  # no video
        "-acodec", "pcm_s16le", # PCM WAV
        "-ar", "16000",         # 16 kHz — optimal for speech models
        "-ac", "1",             # mono
        "-y",                   # overwrite
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        # Common cause: video has no audio track (e.g. synthetic test video)
        stderr_snippet = result.stderr[:200]
        if "no audio" in stderr_snippet.lower() or "invalid data" in stderr_snippet.lower() \
                or result.returncode != 0:
            logger.warning("audio_extraction_failed",
                           reason="ffmpeg returned non-zero (no audio track?)",
                           stderr=stderr_snippet[:100])
            return None
        raise RuntimeError(f"ffmpeg failed: {stderr_snippet}")

    logger.info("audio_extracted", path=audio_path)
    return audio_path


# ── Whisper Local Transcription ───────────────────────────────────────────────

_whisper_model = None


def _get_whisper_model():
    """Lazy-load Whisper model (downloads ~150MB on first use)."""
    global _whisper_model
    if _whisper_model is None and _WHISPER_OK:
        logger.info("whisper_loading", model="base", compute="int8")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("whisper_loaded")
    return _whisper_model


# Pre-warm Whisper at import time so first job doesn't stall
if _WHISPER_OK:
    try:
        _get_whisper_model()
    except Exception as _e:
        logger.warning("whisper_prewarm_failed", error=str(_e))


async def _transcribe_via_whisper(audio_path: str) -> list[TranscriptSegment]:
    """
    Transcribe audio using local faster-whisper model.
    Runs in a thread to avoid blocking the event loop.
    """
    model = _get_whisper_model()
    if model is None:
        return []

    def _run():
        segments_out = []
        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            language=None,  # auto-detect
            vad_filter=True,  # skip silence
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )
        logger.info("whisper_transcribing", language=info.language,
                     language_prob=round(info.language_probability, 2))

        for segment in segments:
            segments_out.append(TranscriptSegment(
                start=round(segment.start, 2),
                end=round(segment.end, 2),
                text=segment.text.strip(),
            ))

        return segments_out

    try:
        # 5-minute hard timeout — Whisper on CPU for long videos can be slow
        result = await asyncio.wait_for(
            asyncio.to_thread(_run),
            timeout=300.0,
        )
        logger.info("whisper_transcription_complete", segments=len(result))
        return result
    except asyncio.TimeoutError:
        logger.warning("whisper_timeout", msg="Transcription exceeded 5 min — returning empty")
        return []
    except Exception as e:
        logger.error("whisper_transcription_error", error=str(e)[:200])
        return []


# ── Deepgram Transcription ────────────────────────────────────────────────────

async def _transcribe_via_deepgram(audio_path: str) -> list[TranscriptSegment]:
    """Transcribe using Deepgram nova-2 API."""
    try:
        from deepgram import DeepgramClient, PrerecordedOptions
    except ImportError:
        logger.warning("transcription_skipped", reason="deepgram-sdk not installed")
        return []

    client = DeepgramClient(settings.deepgram_api_key)

    with open(audio_path, "rb") as f:
        audio_data = f.read()

    options = PrerecordedOptions(
        model="nova-2",
        smart_format=True,
        utterances=True,
        punctuate=True,
    )

    try:
        response = await asyncio.to_thread(
            client.listen.prerecorded.v("1").transcribe_file,
            {"buffer": audio_data, "mimetype": "audio/wav"},
            options,
        )
    except Exception as e:
        logger.error("deepgram_error", error=str(e))
        return []

    segments: list[TranscriptSegment] = []
    for utterance in response.results.utterances:
        segments.append(TranscriptSegment(
            start=utterance.start,
            end=utterance.end,
            text=utterance.transcript,
        ))

    logger.info("deepgram_transcription_complete", segments=len(segments))
    return segments


# ── Main Transcription Entrypoint ─────────────────────────────────────────────

async def transcribe_audio(audio_path: str | None) -> list[TranscriptSegment]:
    """
    Transcribe audio file using the best available provider.

    Priority: Deepgram (if key set) → Whisper local → stub

    Args:
        audio_path: Path to WAV file from extract_audio(), or None if skipped.

    Returns:
        List of TranscriptSegment. Empty list if audio_path is None.
    """
    if audio_path is None:
        logger.warning("transcription_skipped", reason="no audio file (ffmpeg unavailable)")
        return []

    # 1. Try Deepgram (fast cloud API)
    if settings.deepgram_api_key:
        logger.info("transcription_provider", using="deepgram")
        result = await _transcribe_via_deepgram(audio_path)
        if result:
            return result
        logger.warning("deepgram_failed_trying_whisper")

    # 2. Try local Whisper (free, runs on CPU)
    if _WHISPER_OK:
        logger.info("transcription_provider", using="whisper-local")
        result = await _transcribe_via_whisper(audio_path)
        if result:
            return result

    # 3. Stub fallback
    logger.warning("transcription_stub", reason="no transcription provider available")
    return [TranscriptSegment(0.0, 5.0, "[Transcription unavailable — install faster-whisper or set DEEPGRAM_API_KEY]")]
