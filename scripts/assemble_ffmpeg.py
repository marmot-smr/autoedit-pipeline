"""Assemble narrative clips with soft A/V transitions + background music via ffmpeg."""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from media_utils import ffmpeg_exe, probe_media, resolve_music_path, save_json


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed\nCMD: "
            + " ".join(cmd[:12])
            + "...\n"
            + (proc.stderr or "")[-3000:]
        )


def _crop_filter(
    width: int,
    height: int,
    *,
    pan: float = 0.0,
    zoom: float = 1.0,
    focus: float | None = None,
    vfocus: float = 0.28,
) -> str:
    """
    Vertical reframing for ultrawide sources.
    focus: 0.0=left … 1.0=right (face / subject X).
    vfocus: 0.0=top … 1.0=bottom after zoom (faces need ~0.2–0.35, not 0.5).
    pan: legacy pixel offset after center crop (used if focus is None).
    """
    z = max(1.0, float(zoom))
    vf = min(1.0, max(0.0, float(vfocus)))
    if focus is not None:
        f = min(1.0, max(0.0, float(focus)))
        x_expr = f"(in_w-{width})*{f}"
        y_expr = f"(in_h-{height})/2"
    else:
        pan_i = int(pan)
        x_expr = f"(in_w-{width})/2+{pan_i}"
        y_expr = f"(in_h-{height})/2"
    # After zoom, bias crop toward faces (upper third), not geometric center
    zx = f"(in_w-{width})/2"
    zy = f"(in_h-{height})*{vf}"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:{x_expr}:{y_expr},"
        f"scale=iw*{z}:ih*{z},"
        f"crop={width}:{height}:{zx}:{zy},"
        f"setsar=1,fps=30,format=yuv420p"
    )


def export_segment(
    video: Path,
    out: Path,
    start: float,
    end: float,
    *,
    width: int,
    height: int,
    pan: float = 0.0,
    zoom: float = 1.0,
    focus: float | None = None,
    vfocus: float = 0.28,
    edge_fade: float = 0.0,
) -> float:
    """Export one segment. Returns duration seconds."""
    dur = max(0.2, end - start)
    vf = _crop_filter(
        width, height, pan=pan, zoom=zoom, focus=focus, vfocus=vfocus
    )
    af_parts = []
    if edge_fade > 0:
        fade_d = min(edge_fade, dur / 3)
        af_parts.append(f"afade=t=in:st=0:d={fade_d}")
        af_parts.append(f"afade=t=out:st={max(0.0, dur - fade_d)}:d={fade_d}")
    af = ",".join(af_parts) if af_parts else "anull"

    # Hybrid seek: coarse -ss before -i (fast), fine -ss after (accurate).
    # Pure pre-seek on MKV jumps to prior keyframe and can shift shots by seconds.
    pad = min(8.0, max(0.0, start))
    coarse = max(0.0, start - pad)
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-ss",
        str(coarse),
        "-i",
        str(video),
        "-ss",
        str(pad),
        "-t",
        str(dur),
        "-vf",
        vf,
        "-af",
        af,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(out),
    ]
    _run(cmd)
    return float(probe_media(out)["duration_sec"] or dur)


def join_pair(
    a: Path,
    b: Path,
    out: Path,
    *,
    audio_fade_frames: int = 6,
    fps: float = 30.0,
    abut_eps: float = 0.08,
    a_src_end: float | None = None,
    b_src_start: float | None = None,
) -> float:
    """Hard video cut. Audio: hard if clips abut in source; else ≤N-frame edge fades."""
    da = float(probe_media(a)["duration_sec"] or 0)
    db = float(probe_media(b)["duration_sec"] or 0)
    fade = min(max(0, int(audio_fade_frames)), 6) / max(fps, 1.0)
    abut = (
        a_src_end is not None
        and b_src_start is not None
        and abs(float(b_src_start) - float(a_src_end)) <= abut_eps
    )

    if abut or fade < 1e-4:
        # Seamless abut or pure hard cut — no phrase eating
        fc = (
            f"[0:v][1:v]concat=n=2:v=1:a=0[v];"
            f"[0:a][1:a]concat=n=2:v=0:a=1[a]"
        )
    else:
        # Softens click only; fade ≤6 frames, does not overlap both dialogue tracks
        d = min(fade, da * 0.15, db * 0.15)
        fc = (
            f"[0:v][1:v]concat=n=2:v=1:a=0[v];"
            f"[0:a]afade=t=out:st={max(0.0, da - d):.4f}:d={d:.4f}[a0];"
            f"[1:a]afade=t=in:st=0:d={d:.4f}[a1];"
            f"[a0][a1]concat=n=2:v=0:a=1[a]"
        )

    _run(
        [
            ffmpeg_exe(),
            "-y",
            "-i",
            str(a),
            "-i",
            str(b),
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return float(probe_media(out)["duration_sec"] or (da + db))


def xfade_pair(a: Path, b: Path, out: Path, overlap: float = 0.4) -> float:
    """Deprecated: picture xfade eats dialogue. Kept as alias to hard join."""
    return join_pair(a, b, out, audio_fade_frames=6)



def mix_music(
    video: Path,
    music: Path,
    out: Path,
    music_volume_db: float = -24.0,
    *,
    duck: bool = True,
) -> None:
    # Keep dialogue dominant; music as quiet bed with optional sidechain ducking
    gain = 10 ** (music_volume_db / 20.0)
    dur = float(probe_media(video)["duration_sec"] or 0)
    fade_out = min(1.5, max(0.4, dur * 0.1))
    fade_in = min(0.8, fade_out)
    music_dur = float(probe_media(music)["duration_sec"] or 1)
    loops = max(0, int(math.ceil(dur / max(music_dur, 0.1)) - 1))

    if duck:
        # Dialogue triggers compressor on music so speech stays clear
        fc = (
            f"[0:a]asplit=2[a_dlg][a_sc];"
            f"[1:a]volume={gain},afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={max(0.0, dur - fade_out)}:d={fade_out}[m_raw];"
            f"[m_raw][a_sc]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=350:makeup=1[m];"
            f"[a_dlg][m]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.7:normalize=0[a]"
        )
    else:
        fc = (
            f"[1:a]volume={gain},afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={max(0.0, dur - fade_out)}:d={fade_out}[m];"
            f"[0:a]volume=1.0[d];"
            f"[d][m]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.55:normalize=0[a]"
        )

    cmd = [
        ffmpeg_exe(),
        "-y",
        "-i",
        str(video),
        "-stream_loop",
        str(loops),
        "-i",
        str(music),
        "-filter_complex",
        fc,
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    _run(cmd)


def assemble(
    video: Path,
    plan: dict[str, Any],
    work_dir: Path,
    out_path: Path,
    *,
    width: int = 1080,
    height: int = 1920,
    overlap: float = 0.0,
    music_file: str | None = None,
    music_volume_db: float = -16.0,
    audio_fade_frames: int = 6,
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    clips = plan.get("clips") or []
    if not clips:
        raise RuntimeError("В плане нет clips")

    # Self-check: print final subtitle order before render
    print("=== FINAL SUBTITLES (review) ===")
    for i, c in enumerate(clips):
        print(f"  [{i+1}] {c.get('start'):.2f}-{c.get('end'):.2f}  {c.get('text') or ''}")
    print("=== /SUBTITLES ===")

    segs_dir = work_dir / "segments"
    segs_dir.mkdir(exist_ok=True)
    segment_paths: list[Path] = []

    for i, c in enumerate(clips):
        start = float(c["start"])
        end = float(c["end"])
        pan = float(c.get("pan") or 0)
        zoom = float(c.get("zoom") or 1.12)
        focus = c.get("focus")
        focus_f = float(focus) if focus is not None else None
        vfocus = float(c.get("vfocus") if c.get("vfocus") is not None else 0.28)
        out = segs_dir / f"seg_{i:02d}.mp4"
        print(
            f"  segment {i+1}/{len(clips)}: {start:.2f}-{end:.2f} "
            f"focus={focus_f} vfocus={vfocus} zoom={zoom}"
        )
        export_segment(
            video,
            out,
            start,
            end,
            width=width,
            height=height,
            pan=pan,
            zoom=zoom,
            focus=focus_f,
            vfocus=vfocus,
            edge_fade=0.0,
        )
        segment_paths.append(out)

    # Hard picture cuts; audio ≤6 frames only across source gaps
    fade_frames = int(plan.get("audio_fade_frames", audio_fade_frames))
    current = segment_paths[0]
    for i, nxt in enumerate(segment_paths[1:], start=1):
        merged = work_dir / f"merge_{i:02d}.mp4"
        prev_c = clips[i - 1]
        cur_c = clips[i]
        print(
            f"  hard cut {i}/{len(segment_paths)-1} "
            f"(audio_fade_frames={fade_frames}, "
            f"src {prev_c['end']}→{cur_c['start']})"
        )
        join_pair(
            current,
            nxt,
            merged,
            audio_fade_frames=fade_frames,
            a_src_end=float(prev_c["end"]),
            b_src_start=float(cur_c["start"]),
        )
        current = merged

    # Music
    music_src = resolve_music_path(music_file) if music_file else None
    if music_src and music_src.is_file():
        print(f"  music mix: {music_src.name} @ {music_volume_db} dB")
        final = out_path
        final.parent.mkdir(parents=True, exist_ok=True)
        mix_music(current, music_src, final, music_volume_db=music_volume_db)
    else:
        print("  WARN: music file missing, exporting without bed")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(current.read_bytes())

    save_json(
        work_dir / "assemble_meta.json",
        {
            "output": str(out_path),
            "clips": len(clips),
            "overlap": 0.0,
            "audio_fade_frames": fade_frames,
            "music": str(music_src) if music_src else None,
            "thesis": plan.get("thesis"),
            "subtitles": [c.get("text") for c in clips],
        },
    )
    print("wrote", out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--overlap", type=float, default=0.45)
    ap.add_argument("--music", default=None)
    ap.add_argument("--music-db", type=float, default=-16.0)
    args = ap.parse_args()
    plan = json_load(args.plan)
    assemble(
        args.video,
        plan,
        args.work,
        args.out,
        width=args.width,
        height=args.height,
        overlap=args.overlap,
        music_file=args.music or (plan.get("music") or {}).get("file"),
        music_volume_db=args.music_db,
    )
    return 0


def json_load(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
