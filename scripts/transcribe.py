"""Local free transcription via faster-whisper (CUDA if available)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from media_utils import ffmpeg_exe, probe_media, save_json


def extract_wav(video: Path, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])


def pick_device() -> str:
    # faster-whisper uses CTranslate2
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _ensure_nvidia_dll_path() -> None:
    """Windows pip wheels ship cuBLAS/cuDNN under site-packages/nvidia/*/bin."""
    import glob
    import os
    import site
    from pathlib import Path

    bins: list[str] = []
    for root in site.getsitepackages():
        for pattern in (
            "nvidia/cublas/bin",
            "nvidia/cudnn/bin",
            "nvidia/cuda_runtime/bin",
        ):
            p = Path(root) / pattern
            if p.is_dir():
                bins.append(str(p))
    if not bins:
        return
    # Python 3.8+ Windows DLL resolution
    for b in bins:
        try:
            os.add_dll_directory(b)
        except Exception:
            pass
    os.environ["PATH"] = os.pathsep.join(bins + [os.environ.get("PATH", "")])


def transcribe_video(
    video: Path,
    out_json: Path,
    *,
    language: str | None = "ru",
    model_size: str = "medium",
) -> dict[str, Any]:
    from faster_whisper import WhisperModel

    _ensure_nvidia_dll_path()
    device = pick_device()
    compute = "float16" if device == "cuda" else "int8"
    print(f"faster-whisper model={model_size} device={device} compute={compute}")

    work = out_json.parent / "_audio"
    wav = work / "audio_16k.wav"
    print("extracting audio...")
    extract_wav(video, wav)

    try:
        model = WhisperModel(model_size, device=device, compute_type=compute)
    except Exception as e:
        if device == "cuda":
            print(f"WARN CUDA failed ({e}); fallback to CPU int8")
            device, compute = "cpu", "int8"
            model = WhisperModel(model_size, device=device, compute_type=compute)
        else:
            raise

    segments_iter, info = model.transcribe(
        str(wav),
        language=language,
        beam_size=5,
        vad_filter=True,
        word_timestamps=False,
    )

    segments: list[dict[str, Any]] = []
    texts: list[str] = []
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        item = {"start": float(seg.start), "end": float(seg.end), "text": text}
        segments.append(item)
        texts.append(text)
        # progress
        if len(segments) % 40 == 0:
            print(f"  ... {len(segments)} segments, t={seg.end:.0f}s")

    dur = float(probe_media(video)["duration_sec"] or info.duration or 0)
    merged = {
        "text": " ".join(texts),
        "segments": segments,
        "duration_sec": dur,
        "language": language or getattr(info, "language", None),
        "source": str(video),
        "engine": f"faster-whisper:{model_size}:{device}",
    }
    save_json(out_json, merged)
    txt = out_json.with_suffix(".txt")
    txt.write_text(
        "\n".join(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in segments),
        encoding="utf-8",
    )
    print("wrote", out_json)
    print("wrote", txt)
    print(f"segments={len(segments)} duration={dur:.1f}s")
    return merged


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lang", default="ru")
    p.add_argument("--model", default="medium", help="tiny/base/small/medium/large-v3")
    args = p.parse_args()
    transcribe_video(args.video, args.out, language=args.lang or None, model_size=args.model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
