"""Bounded preprocessing for Field Intelligence walk-and-talk video."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_FRAME_BYTES = 3 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024


@dataclass
class VideoFramesResult:
    frames: list[tuple[bytes, str, dict]] = field(default_factory=list)
    status: str = "skipped"
    error: str | None = None


@dataclass
class VideoAudioResult:
    audio: bytes | None = None
    content_type: str | None = None
    status: str = "skipped"
    error: str | None = None


def _ffmpeg_path() -> str:
    return str(getattr(settings, "FIELD_MEDIA_FFMPEG_PATH", "") or os.getenv("FIELD_MEDIA_FFMPEG_PATH") or "ffmpeg")


def _run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=max(2.0, timeout),
    )


def extract_video_audio(video: bytes, *, content_type: str | None = None) -> VideoAudioResult:
    if not video or len(video) > MAX_VIDEO_BYTES:
        return VideoAudioResult(status="failed", error="video_outside_preprocessing_bound")
    suffix = ".mp4" if "mp4" in (content_type or "").lower() else ".webm"
    try:
        with tempfile.TemporaryDirectory(prefix="agroai-fi-video-") as directory:
            source = Path(directory) / f"input{suffix}"
            output = Path(directory) / "audio.mp3"
            source.write_bytes(video)
            completed = _run(
                [
                    _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
                    str(output),
                ],
                timeout=float(getattr(settings, "FIELD_MEDIA_PROBE_TIMEOUT_SECONDS", 20.0) or 20.0) * 2,
            )
            if completed.returncode != 0 or not output.exists():
                return VideoAudioResult(status="failed", error="video_audio_extraction_failed")
            audio = output.read_bytes()
            if not audio or len(audio) > MAX_AUDIO_BYTES:
                return VideoAudioResult(status="failed", error="extracted_audio_outside_bound")
            return VideoAudioResult(audio=audio, content_type="audio/mpeg", status="completed")
    except subprocess.TimeoutExpired:
        return VideoAudioResult(status="failed", error="video_audio_extraction_timeout")
    except Exception as exc:  # noqa: BLE001
        return VideoAudioResult(status="failed", error=exc.__class__.__name__)


def extract_video_frames(
    video: bytes,
    *,
    content_type: str | None = None,
    duration_seconds: float | None = None,
    max_frames: int = 8,
) -> VideoFramesResult:
    if not video or len(video) > MAX_VIDEO_BYTES:
        return VideoFramesResult(status="failed", error="video_outside_preprocessing_bound")
    count = max(1, min(int(max_frames or 1), 8))
    duration = max(float(duration_seconds or 0.0), 1.0)
    interval = max(duration / count, 1.0)
    suffix = ".mp4" if "mp4" in (content_type or "").lower() else ".webm"
    try:
        with tempfile.TemporaryDirectory(prefix="agroai-fi-frames-") as directory:
            source = Path(directory) / f"input{suffix}"
            pattern = Path(directory) / "frame-%03d.jpg"
            source.write_bytes(video)
            completed = _run(
                [
                    _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(source),
                    "-vf", f"fps=1/{interval:.3f},scale=1600:-2:force_original_aspect_ratio=decrease",
                    "-frames:v", str(count), "-q:v", "3", str(pattern),
                ],
                timeout=float(getattr(settings, "FIELD_MEDIA_PROBE_TIMEOUT_SECONDS", 20.0) or 20.0) * 3,
            )
            if completed.returncode != 0:
                return VideoFramesResult(status="failed", error="video_frame_extraction_failed")
            rows: list[tuple[bytes, str, dict]] = []
            for index, path in enumerate(sorted(Path(directory).glob("frame-*.jpg"))[:count]):
                payload = path.read_bytes()
                if not payload or len(payload) > MAX_FRAME_BYTES:
                    continue
                rows.append((
                    payload,
                    "image/jpeg",
                    {
                        "media_kind": "video_frame",
                        "frame_timestamp_seconds": round(min((index + 0.5) * interval, duration), 2),
                    },
                ))
            if not rows:
                return VideoFramesResult(status="failed", error="no_video_frames_extracted")
            return VideoFramesResult(frames=rows, status="completed")
    except subprocess.TimeoutExpired:
        return VideoFramesResult(status="failed", error="video_frame_extraction_timeout")
    except Exception as exc:  # noqa: BLE001
        return VideoFramesResult(status="failed", error=exc.__class__.__name__)
