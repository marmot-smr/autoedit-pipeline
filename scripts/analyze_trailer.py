from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import INBOX, ROOT
from media_utils import ffmpeg_exe, probe_media

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".webm", ".m4v"}


def find_video() -> Path:
    vids = [p for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not vids:
        raise SystemExit("No video in inbox")
    return max(vids, key=lambda p: p.stat().st_size)


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_exe(), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def scene_cuts(video: Path, threshold: float = 0.35) -> list[float]:
    # showinfo on selected scene frames
    args = [
        "-hide_banner",
        "-i",
        str(video),
        "-filter:v",
        f"select='gt(scene,{threshold})',showinfo",
        "-vsync",
        "vfr",
        "-f",
        "null",
        "-",
    ]
    proc = run_ffmpeg(args)
    text = (proc.stderr or "") + (proc.stdout or "")
    times = []
    for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", text):
        times.append(float(m.group(1)))
    return sorted(set(round(t, 3) for t in times))


def audio_energy_peaks(video: Path, window_sec: float = 2.0) -> list[tuple[float, float]]:
    """Return list of (time_sec, rms_db) sampled via astats on chunks via silencedetect inverse approach.

    Uses ffmpeg volumedetect on segmented times by extracting mean volume via atrim loop —
    too slow for full ep. Instead: use ebur128 summary over time with lavfi.
    """
    # Extract mono low-rate audio wav first (fast-ish)
    wav = ROOT / "processing" / "_analyze_audio.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    proc = run_ffmpeg(
        [
            "-y",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])

    import wave
    import array
    import math

    with wave.open(str(wav), "rb") as wf:
        rate = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
        samples = array.array("h")
        samples.frombytes(raw)

    win = max(1, int(rate * window_sec))
    peaks: list[tuple[float, float]] = []
    for i in range(0, len(samples) - win, win):
        chunk = samples[i : i + win]
        # RMS
        acc = 0.0
        for s in chunk:
            acc += s * s
        rms = math.sqrt(acc / len(chunk)) / 32768.0
        db = 20 * math.log10(rms + 1e-9)
        t = i / rate
        peaks.append((t, db))
    return peaks


def pick_trailer_clips(
    duration: float,
    scenes: list[float],
    energy: list[tuple[float, float]],
    target_clips: int = 10,
    clip_len: float = 2.8,
) -> list[dict]:
    # Prefer high-energy windows, avoid open/credits: skip first 90s and last 60s
    lo, hi = 90.0, max(90.0, duration - 60.0)
    ranked = [(t, db) for t, db in energy if lo <= t <= hi]
    ranked.sort(key=lambda x: x[1], reverse=True)

    chosen: list[float] = []
    min_gap = 12.0
    for t, _db in ranked:
        if all(abs(t - c) >= min_gap for c in chosen):
            # snap near a scene cut if close
            snap = t
            nearby = [s for s in scenes if abs(s - t) < 4.0 and lo <= s <= hi]
            if nearby:
                snap = min(nearby, key=lambda s: abs(s - t))
            chosen.append(snap)
        if len(chosen) >= target_clips:
            break

    # If not enough energy peaks, fill from scenes
    if len(chosen) < target_clips:
        for s in scenes:
            if not (lo <= s <= hi):
                continue
            if all(abs(s - c) >= min_gap for c in chosen):
                chosen.append(s)
            if len(chosen) >= target_clips:
                break

    chosen.sort()
    clips = []
    zooms = [1.0, 1.08, 1.12, 1.05, 1.15, 1.0, 1.1, 1.06, 1.12, 1.08]
    for i, start in enumerate(chosen):
        end = min(duration - 0.5, start + clip_len)
        if end - start < 1.2:
            continue
        clips.append(
            {
                "start": round(start, 2),
                "end": round(end, 2),
                "zoom": zooms[i % len(zooms)],
            }
        )
    return clips


def main() -> int:
    video = find_video()
    print("video:", video.name)
    probe = probe_media(video)
    duration = float(probe.get("duration_sec") or 0)
    print("duration_sec:", duration, "fps:", probe.get("fps"), "wh:", probe.get("width"), probe.get("height"))

    print("extracting audio + energy...")
    energy = audio_energy_peaks(video, window_sec=2.0)
    print("energy windows:", len(energy), "max_db:", max(e[1] for e in energy) if energy else None)

    print("detecting scenes (may take a bit)...")
    scenes = scene_cuts(video, threshold=0.32)
    print("scene cuts:", len(scenes))

    clips = pick_trailer_clips(duration, scenes, energy)
    out = {
        "video": str(video),
        "duration_sec": duration,
        "clips": clips,
        "scenes_sample": scenes[:40],
        "top_energy": sorted(energy, key=lambda x: x[1], reverse=True)[:15],
    }
    out_path = ROOT / "processing" / "young_sherlock_analysis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out_path)
    print("clips:")
    for c in clips:
        print(" ", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
