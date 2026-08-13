from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from array import array
from pathlib import Path
from typing import Any

import imageio_ffmpeg

from config import AUDIO_EXTS, DEFAULT_TZ, MUSIC_DIR


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def merge_tz(user_tz: dict[str, Any] | None = None) -> dict[str, Any]:
    base = load_json(DEFAULT_TZ)
    if not user_tz:
        return base

    def deep_merge(a: dict, b: dict) -> dict:
        out = dict(a)
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = deep_merge(out[k], v)
            else:
                out[k] = v
        return out

    return deep_merge(base, user_tz)


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_media(path: Path) -> dict[str, Any]:
    """Return duration_sec, fps, width, height via ffmpeg."""
    cmd = [
        ffmpeg_exe(),
        "-i",
        str(path),
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stderr = proc.stderr or ""

    duration = _parse_duration(stderr)
    fps = _parse_fps(stderr)
    width, height = _parse_wh(stderr)
    return {
        "duration_sec": duration,
        "fps": fps or 30.0,
        "width": width,
        "height": height,
        "raw": stderr[-2000:],
    }


def _parse_duration(text: str) -> float:
    # Duration: 00:01:23.45
    import re

    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        return 0.0
    h, mnt, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mnt * 60 + sec


def _parse_fps(text: str) -> float | None:
    import re

    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*tbr", text)
    if m:
        return float(m.group(1))
    return None


def _parse_wh(text: str) -> tuple[int | None, int | None]:
    import re

    m = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})", text)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def sec_to_frames(sec: float, fps: float) -> int:
    return max(0, int(round(sec * fps)))


def resolve_music_path(music_file: str | None) -> Path | None:
    if not music_file:
        return None
    p = Path(music_file)
    if p.is_file():
        return p.resolve()
    candidate = MUSIC_DIR / music_file
    if candidate.is_file():
        return candidate.resolve()
    # fuzzy: first match by stem
    stem = Path(music_file).stem
    for ext in AUDIO_EXTS:
        hit = MUSIC_DIR / f"{stem}{ext}"
        if hit.is_file():
            return hit.resolve()
    return None


def prepare_music(
    src: Path,
    work_dir: Path,
    *,
    volume_db: float = -18.0,
    target_duration_sec: float | None = None,
    fade_in_sec: float = 0.0,
    fade_out_sec: float = 0.0,
    loop: bool = True,
) -> Path:
    """
    Build a WAV ready for Resolve: gain + optional loop/trim + fades.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / "music_prepared.wav"

    # First convert/gain to wav
    gain = 10 ** (volume_db / 20.0)
    tmp = work_dir / "music_gain.wav"
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-i",
        str(src),
        "-ac",
        "2",
        "-ar",
        "48000",
        "-filter:a",
        f"volume={gain}",
        str(tmp),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)

    if target_duration_sec is None or target_duration_sec <= 0:
        shutil.copy2(tmp, out)
        return out

    # Loop or trim to target duration, then fades
    filters = []
    # atrim after aloop is easier via -stream_loop
    loop_count = 0
    if loop:
        src_dur = probe_media(tmp)["duration_sec"] or 1.0
        loop_count = max(0, math.ceil(target_duration_sec / src_dur) - 1)

    fade_parts = []
    if fade_in_sec > 0:
        fade_parts.append(f"afade=t=in:st=0:d={fade_in_sec}")
    if fade_out_sec > 0:
        start = max(0.0, target_duration_sec - fade_out_sec)
        fade_parts.append(f"afade=t=out:st={start}:d={fade_out_sec}")
    fade_filter = ",".join(fade_parts) if fade_parts else "anull"

    cmd2 = [
        ffmpeg_exe(),
        "-y",
        "-stream_loop",
        str(loop_count),
        "-i",
        str(tmp),
        "-t",
        str(target_duration_sec),
        "-af",
        fade_filter,
        str(out),
    ]
    subprocess.run(cmd2, capture_output=True, text=True, check=True)
    return out


def make_placeholder_music(path: Path, duration_sec: float = 60.0) -> None:
    """Soft stereo sine placeholder (no ffmpeg needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 44100
    freq = 220.0
    amp = 0.05
    n = int(rate * duration_sec)
    samples = array("h")
    for i in range(n):
        t = i / rate
        # gentle envelope at edges
        env = 1.0
        if t < 1.0:
            env = t
        elif t > duration_sec - 2.0:
            env = max(0.0, (duration_sec - t) / 2.0)
        val = int(amp * env * 32767.0 * math.sin(2 * math.pi * freq * t))
        samples.append(val)
        samples.append(val)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())
