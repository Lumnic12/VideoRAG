"""
Audio transcription service.
Extracts audio from video via ffmpeg, sends to Deepgram nova-2,
returns timestamped transcript segments.

Graceful stubs:
- ffmpeg missing  → returns empty transcript with warning
- DEEPGRAM_API_KEY missing → returns stub segments
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

from core.config import settings

logger = structlog.get_logger()


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


async def transcribe_audio(audio_path: str | None) -> list[TranscriptSegment]:
    """
    Send audio file to Deepgram nova-2 and return timestamped utterances.

    Args:
        audio_path: Path to WAV file from extract_audio(), or None if skipped.

    Returns:
        List of TranscriptSegment. Empty list if audio_path is None or key missing.
    """
    if audio_path is None:
        logger.warning("transcription_skipped", reason="no audio file (ffmpeg unavailable)")
        return []

    if not settings.deepgram_api_key:
        logger.warning("transcription_skipped", reason="no DEEPGRAM_API_KEY")
        return [TranscriptSegment(0.0, 5.0, "[Transcription stub — add DEEPGRAM_API_KEY]")]

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

    logger.info("transcription_complete", segments=len(segments))
    return segments
