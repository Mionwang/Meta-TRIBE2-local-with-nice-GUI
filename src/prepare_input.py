"""Adapt locally supplied media to the inputs supported by TRIBE v2."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import imageio_ffmpeg

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TEXT_EXTENSIONS = {".txt"}
ALL_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS | TEXT_EXTENSIONS


def kind_for_suffix(suffix: str) -> str | None:
    suffix = suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    return None


def _run(command: list[str]) -> None:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=flags)
    if completed.returncode:
        detail = completed.stderr.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "Could not prepare this input.")


def _has_audio(path: Path, ffmpeg: str) -> bool:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    probe = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
                            "-map", "0:a:0", "-frames:a", "1", "-f", "null", "-"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=flags)
    return probe.returncode == 0


def _with_ext(stem: Path, ext: str) -> Path:
    # Path.with_suffix() would treat "clip.v2-video-abc" as stem "clip" + suffix
    # ".v2-video-abc" and silently rename the output. Append instead.
    return stem.parent / f"{stem.name}{ext}"


def prepare_input(source: Path, kind: str, destination_stem: Path) -> tuple[Path, list[str], str]:
    """Return the model input, extra CLI arguments, and an honest UI explanation."""
    suffix = source.suffix.lower()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if kind == "video":
        if suffix == ".mp4":
            has_audio = _has_audio(source, ffmpeg)
            return source, [] if has_audio else ["--no-audio"], (
                "Video and its audio were analyzed together." if has_audio
                else "Silent video was analyzed through the visual path."
            )
        target = _with_ext(destination_stem, ".mp4")
        if not target.exists():
            temporary = target.with_name(target.stem + ".tmp.mp4")
            _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                  "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                  "-movflags", "+faststart", str(temporary)])
            os.replace(temporary, target)
        has_audio = _has_audio(target, ffmpeg)
        return target, [] if has_audio else ["--no-audio"], (
            "This video was converted to MP4 locally for TRIBE v2."
            + ("" if has_audio else " No audio track was present.")
        )
    if kind == "audio":
        if suffix in {".wav", ".mp3", ".flac", ".ogg"}:
            return source, [], "Audio-only response; no visual input was supplied."
        target = _with_ext(destination_stem, ".wav")
        if not target.exists():
            temporary = target.with_name(target.stem + ".tmp.wav")
            _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                  "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary)])
            os.replace(temporary, target)
        return target, [], "Audio-only response; the file was converted to WAV locally."
    if kind == "image":
        target = _with_ext(destination_stem, ".mp4")
        if not target.exists():
            temporary = target.with_name(target.stem + ".tmp.mp4")
            _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1",
                  "-framerate", "4", "-i", str(source), "-t", "6", "-r", "4",
                  "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                         "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=white",
                  "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                  "-pix_fmt", "yuv420p", str(temporary)])
            os.replace(temporary, target)
        return target, ["--no-audio"], (
            "The image was held on screen for 6 seconds and analyzed as a static visual clip. "
            "Timeline changes reflect model context, not changes in the image."
        )
    if kind == "text":
        content = source.read_text(encoding="utf-8-sig").strip()
        if not content:
            raise ValueError("The text is empty.")
        if len(content) > 10000:
            raise ValueError("Text is limited to 10,000 characters per analysis.")
        target = _with_ext(destination_stem, ".wav")
        if not target.exists():
            temporary = target.with_name(target.stem + ".tmp.wav")
            script = Path(__file__).with_name("speak_text.ps1")
            _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                  "-File", str(script), str(source), str(temporary)])
            os.replace(temporary, target)
        return target, [], (
            "Text was read aloud with this PC's English voice, then analyzed as audio. "
            "This does not use TRIBE v2's gated language encoder."
        )
    raise ValueError("Unsupported input type.")
