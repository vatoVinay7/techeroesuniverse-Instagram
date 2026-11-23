"""Prepare media for Instagram with ffmpeg (run locally / in the Claude session).

Reels:   1080x1920, H.264 + AAC, 30 fps, faststart, < max_bytes (GitHub Pages limit)
Stories: images -> 1080x1920 JPEG (blurred background if not 9:16)
Posts:   images -> 1080x1350 JPEG (4:5 Feed-Format, blurred background if needed)
         videos -> like reels, max. 60 s
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

W, H = 1080, 1920
STORY_MAX_SECONDS = 60
REEL_MIN_SECONDS, REEL_MAX_SECONDS = 3, 15 * 60
AUDIO_KBPS = 128


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int
    height: int
    has_audio: bool
    size: int


def probe(path: Path) -> Probe:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"{path.name}: keine Videospur/Bilddaten gefunden")
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    duration = float(data["format"].get("duration") or video.get("duration") or 0)
    return Probe(duration=duration, width=int(video["width"]), height=int(video["height"]),
                 has_audio=has_audio, size=path.stat().st_size)


_FIT = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def _encode_video(src: Path, dst: Path, info: Probe, *, video_args: list[str]) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if not info.has_audio:
        # Instagram verarbeitet Videos ohne Tonspur unzuverlässig -> stille Spur ergänzen
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-shortest"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if info.has_audio else "1:a:0",
            "-vf", f"{_FIT},fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", *video_args,
            "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)


def prepare_video(src: Path, dst: Path, *, max_bytes: int, max_seconds: float) -> Probe:
    info = probe(src)
    if info.duration < REEL_MIN_SECONDS:
        raise MediaError(f"{src.name}: zu kurz ({info.duration:.1f} s)")
    if info.duration > max_seconds:
        raise MediaError(f"{src.name}: zu lang ({info.duration:.0f} s, max. {max_seconds:.0f} s)")
    dst.parent.mkdir(parents=True, exist_ok=True)

    # 1. Versuch: gute Qualität mit Obergrenze für die Bitrate
    _encode_video(src, dst, info, video_args=["-crf", "21", "-maxrate", "6M", "-bufsize", "12M"])
    if dst.stat().st_size <= max_bytes:
        return probe(dst)

    # 2. Versuch: feste Bitrate passend zur Größenobergrenze (8 % Reserve)
    kbps = int(max_bytes * 8 * 0.92 / info.duration / 1000) - AUDIO_KBPS
    if kbps < 800:
        raise MediaError(f"{src.name}: passt selbst mit niedriger Qualität nicht unter {max_bytes} Bytes")
    _encode_video(src, dst, info, video_args=["-b:v", f"{kbps}k", "-maxrate", f"{kbps}k",
                                               "-bufsize", f"{2 * kbps}k"])
    if dst.stat().st_size > max_bytes:
        raise MediaError(f"{dst.name}: immer noch zu groß ({dst.stat().st_size} Bytes)")
    return probe(dst)


def prepare_reel(src: Path, dst: Path, *, max_bytes: int) -> Probe:
    return prepare_video(src, dst, max_bytes=max_bytes, max_seconds=REEL_MAX_SECONDS)


def prepare_story(src: Path, dst: Path, *, max_bytes: int) -> Probe | None:
    """Images become JPEG (dst gets .jpg), videos become MP4 (dst gets .mp4)."""
    info = probe(src)
    is_image = info.duration == 0 or src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".heic"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not is_image:
        return prepare_video(src, dst.with_suffix(".mp4"), max_bytes=max_bytes, max_seconds=STORY_MAX_SECONDS)
    _image_to_jpeg(src, dst.with_suffix(".jpg"), W, H)
    return None


POST_W, POST_H = 1080, 1350


def prepare_post(src: Path, dst: Path) -> Path:
    """Feed-Bild: 1080x1350 JPEG (4:5). Andere Seitenverhältnisse bekommen einen unscharfen Rand."""
    info = probe(src)
    if info.duration > 0 and src.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".heic"}:
        raise MediaError(f"{src.name}: ein Bild-Beitrag braucht ein Bild – Videos als Reel posten")
    dst.parent.mkdir(parents=True, exist_ok=True)
    target = dst.with_suffix(".jpg")
    _image_to_jpeg(src, target, POST_W, POST_H)
    return target


def _image_to_jpeg(src: Path, target: Path, w: int, h: int) -> None:
    graph = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:5[bg];"
             f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuvj420p[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", graph,
                    "-map", "[out]", "-frames:v", "1", "-q:v", "2", str(target)], check=True)
