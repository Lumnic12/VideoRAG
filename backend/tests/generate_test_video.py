"""
Generate a synthetic slide-like test video for pipeline verification.
Creates ~10 visually distinct slides with text overlays so SSIM extracts
multiple keyframes — simulating a real lecture recording.

Run from: backend/
  python tests/generate_test_video.py
"""
import cv2
import numpy as np
from pathlib import Path

OUTPUT = Path("tests/test_lecture.mp4")
FPS = 24
DURATION_PER_SLIDE = 3   # seconds each slide is shown
TRANSITION_FRAMES = 8     # short blank transition

SLIDES = [
    {"title": "SSIM Keyframe Extraction", "bg": (30, 26, 10), "accent": (96, 69, 233), "bullets": ["Structural Similarity Index", "Detects scene changes", "Reduces 1800 frames to ~10"]},
    {"title": "Why SSIM?", "bg": (22, 52, 15), "accent": (30, 33, 238), "bullets": ["Perceptual quality metric", "Compares luminance & contrast", "SSIM > 0.95 = same slide"]},
    {"title": "FAISS Vector Store", "bg": (44, 38, 27), "accent": (117, 76, 15), "bullets": ["Facebook AI Similarity Search", "Inner-product flat index", "Sub-ms retrieval at scale"]},
    {"title": "OpenAI Embeddings", "bg": (45, 19, 45), "accent": (68, 119, 238), "bullets": ["text-embedding-3-small", "1536 dimensions per chunk", "Semantic similarity search"]},
    {"title": "Jina VLM Analysis", "bg": (13, 115, 13), "accent": (133, 160, 20), "bullets": ["Visual Language Model", "Extracts text from slides", "Key concept detection"]},
    {"title": "Deepgram Transcription", "bg": (50, 46, 49), "accent": (51, 163, 163), "bullets": ["Nova-2 speech model", "Word-level timestamps", "Smart punctuation"]},
    {"title": "Pipeline Architecture", "bg": (30, 26, 10), "accent": (237, 58, 124), "bullets": ["Upload → SSIM → VLM", "Audio → Deepgram nova-2", "FAISS RAG indexing"]},
    {"title": "Celery + Redis", "bg": (39, 32, 15), "accent": (100, 208, 196), "bullets": ["Async task queue", "Job state in Redis", "Thread fallback on Windows"]},
    {"title": "RAG Query Engine", "bg": (27, 27, 47), "accent": (96, 69, 233), "bullets": ["Retrieve top-k chunks", "GPT-4o-mini synthesis", "Cited timestamped answers"]},
    {"title": "Demo Complete!", "bg": (10, 10, 10), "accent": (57, 211, 52), "bullets": ["Phase 1 Pipeline Done", "All services connected", "Ready for queries"]},
]

W, H = 1280, 720


def draw_slide(slide: dict, slide_num: int, total: int) -> np.ndarray:
    """Render a slide as a BGR numpy array."""
    frame = np.zeros((H, W, 3), dtype=np.uint8)

    bg = slide["bg"]         # already BGR tuple
    ac = slide["accent"]     # already BGR tuple
    title = slide["title"]
    bullets = slide["bullets"]

    frame[:] = bg

    # Accent bar at top
    cv2.rectangle(frame, (0, 0), (W, 8), ac, -1)

    # Title text
    cv2.putText(frame, title, (80, 120),
                cv2.FONT_HERSHEY_DUPLEX, 1.5, (240, 240, 255), 2, cv2.LINE_AA)

    # Divider line
    cv2.line(frame, (80, 155), (W - 80, 155), ac, 3)

    # Bullet points
    for i, b in enumerate(bullets):
        y = 230 + i * 80
        cv2.circle(frame, (90, y - 8), 6, ac, -1)
        cv2.putText(frame, b, (120, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 220), 2, cv2.LINE_AA)

    # Slide counter
    cv2.putText(frame, f"{slide_num}/{total}",
                (W - 110, H - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 120), 1)

    return frame


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(OUTPUT),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FPS,
        (W, H),
    )

    blank = np.zeros((H, W, 3), dtype=np.uint8)

    for i, slide in enumerate(SLIDES):
        frame = draw_slide(slide, i + 1, len(SLIDES))

        # Hold the slide for DURATION_PER_SLIDE seconds
        for _ in range(FPS * DURATION_PER_SLIDE):
            writer.write(frame)

        # Brief dark transition
        for _ in range(TRANSITION_FRAMES):
            writer.write(blank)

    writer.release()

    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    total_secs = len(SLIDES) * DURATION_PER_SLIDE + len(SLIDES) * TRANSITION_FRAMES / FPS
    print(f"✅ Test video written: {OUTPUT}  ({size_mb:.1f} MB)")
    print(f"   Duration : {total_secs:.1f}s  |  Slides: {len(SLIDES)}")
    print(f"   Expected keyframes: ~ {len(SLIDES)}")
    print(f"\nRun the pipeline test:")
    print(f"  python tests/test_pipeline.py")


if __name__ == "__main__":
    main()
