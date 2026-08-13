"""
Quality pipeline without OpenAI:
  1) Local faster-whisper transcript (free, CUDA)
  2) Narrative plan by Cursor agent (this chat / subscription)
  3) FFmpeg assemble (soft transitions + music)
  4) Optional Resolve timeline
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from assemble_ffmpeg import assemble
from config import OUT, PROCESSING, ROOT
from media_utils import load_json, merge_tz, save_json
from plan_narrative import export_agent_pack, finalize_plan
from transcribe import transcribe_video


def find_default_video() -> Path:
    mkvs = list(PROCESSING.rglob("*.mkv")) + list((ROOT / "inbox").glob("*.mkv"))
    mkvs += list(PROCESSING.rglob("*.mp4")) + list((ROOT / "inbox").glob("*.mp4"))
    if not mkvs:
        raise FileNotFoundError("Нет видео в inbox/ или processing/")
    return max(mkvs, key=lambda p: p.stat().st_mtime)


def latest_work_dir() -> Path | None:
    dirs = sorted(PROCESSING.glob("quality_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0] if dirs else None


def stage_transcribe(
    video: Path,
    brief_path: Path,
    *,
    lang: str = "ru",
    model: str = "medium",
    reuse: bool = False,
) -> Path:
    raw_brief = load_json(brief_path) if brief_path.is_file() else {}
    brief = merge_tz(raw_brief)
    brief.update({k: v for k, v in raw_brief.items() if k in ("idea", "thesis", "hero", "prompt", "notes", "target_duration_sec")})

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = PROCESSING / f"quality_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    save_json(work / "brief.json", brief)

    cached = video.with_name(video.stem + ".transcript.json")
    transcript_path = work / "transcript.json"

    if reuse and cached.is_file():
        print("reuse cached transcript:", cached)
        transcript = load_json(cached)
        save_json(transcript_path, transcript)
    elif reuse and (PROCESSING / "last_transcript.json").is_file():
        print("reuse last_transcript.json")
        transcript = load_json(PROCESSING / "last_transcript.json")
        save_json(transcript_path, transcript)
    else:
        print("=== TRANSCRIBE (local faster-whisper, free) ===")
        transcript = transcribe_video(video, transcript_path, language=lang, model_size=model)
        save_json(cached, transcript)
        save_json(PROCESSING / "last_transcript.json", transcript)

    prompt_path = export_agent_pack(transcript, brief, work / "agent_pack")
    save_json(work / "video_path.json", {"video": str(video.resolve())})
    print("\nOK transcript ready.")
    print("WORK:", work)
    print("PROMPT:", prompt_path)
    print("\nДальше в Cursor-чате: попроси агента собрать plan.json из agent_pack/")
    print("Потом: .\\run.ps1 -Quality -Assemble")
    return work


def stage_assemble(
    *,
    work: Path | None = None,
    plan_path: Path | None = None,
    out_name: str | None = None,
    overlap: float = 0.45,
    also_resolve: bool = False,
) -> dict[str, Any]:
    work = work or latest_work_dir()
    if not work or not work.is_dir():
        raise FileNotFoundError("Нет quality_* папки. Сначала --stage transcribe")

    brief = load_json(work / "brief.json") if (work / "brief.json").is_file() else {}
    video_meta = load_json(work / "video_path.json") if (work / "video_path.json").is_file() else {}
    video = Path(video_meta.get("video") or find_default_video())

    plan_file = plan_path or (work / "plan.json")
    if not plan_file.is_file():
        # also accept agent_pack/plan.json
        alt = work / "agent_pack" / "plan.json"
        if alt.is_file():
            plan_file = alt
        else:
            raise FileNotFoundError(
                f"Нет {plan_file}. Пусть Cursor-агент запишет plan.json в эту папку."
            )

    transcript = None
    if (work / "transcript.json").is_file():
        transcript = load_json(work / "transcript.json")

    plan = finalize_plan(load_json(plan_file), transcript)
    if brief.get("music"):
        plan["music"] = brief["music"]
    save_json(work / "plan.json", plan)

    fmt = brief.get("format") or {}
    width = int(fmt.get("width") or 1080)
    height = int(fmt.get("height") or 1920)
    music_cfg = brief.get("music") or plan.get("music") or {}
    music_file = music_cfg.get("file") or "brazilian_phonk_cc0.mp3"
    music_db = float(music_cfg.get("volume_db", -15))

    out_path = OUT / (out_name or f"{brief.get('title') or 'quality_edit'}.mp4")
    if out_path.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
        out_path = out_path.with_suffix(".mp4")
    print("=== ASSEMBLE (xfade + music) ===")
    print("thesis:", plan.get("thesis"))
    print("clips:", len(plan.get("clips") or []), "sec:", plan.get("total_selected_sec"))
    assemble(
        video,
        plan,
        work / "assemble",
        out_path,
        width=width,
        height=height,
        overlap=overlap,
        music_file=music_file,
        music_volume_db=music_db,
    )

    result = {
        "ok": True,
        "output": str(out_path),
        "work": str(work),
        "thesis": plan.get("thesis"),
        "clips": plan.get("clips"),
        "music": music_file,
    }
    save_json(work / "result.json", result)

    if also_resolve:
        try:
            from edit_job import run_job

            tz = {
                "title": brief.get("title") or "quality_resolve",
                "format": {"width": width, "height": height, "fps": fmt.get("fps") or 24, "scale": "fill"},
                "clips": [
                    {
                        "start": c["start"],
                        "end": c["end"],
                        "zoom": c.get("zoom", 1.12),
                        "pan": c.get("pan", 0),
                    }
                    for c in (plan.get("clips") or [])
                ],
                "music": {
                    "file": music_file,
                    "volume_db": music_db,
                    "fade_in_sec": 0.8,
                    "fade_out_sec": 1.5,
                    "loop": True,
                },
                "options": {"mute_source_audio": False, "scale": "fill"},
                "export": {"enabled": False},
            }
            tz_path = work / "resolve.tz.json"
            save_json(tz_path, tz)
            run_job(video, tz_path, OUT)
            result["resolve"] = "timeline created"
        except Exception as e:
            result["resolve_error"] = str(e)
            print("WARN Resolve:", e)

    print(json.dumps({k: v for k, v in result.items() if k != "clips"}, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["transcribe", "assemble", "all"], default="transcribe")
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--brief", type=Path, required=True)
    ap.add_argument("--plan", type=Path, default=None)
    ap.add_argument("--work", type=Path, default=None)
    ap.add_argument("--out-name", default=None)
    ap.add_argument("--overlap", type=float, default=0.45)
    ap.add_argument("--reuse-transcript", action="store_true")
    ap.add_argument("--also-resolve", action="store_true")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--model", default="medium", help="faster-whisper size")
    args = ap.parse_args()

    video = args.video or find_default_video()
    print("video:", video)

    try:
        if args.stage in ("transcribe", "all"):
            work = stage_transcribe(
                video,
                args.brief,
                lang=args.lang,
                model=args.model,
                reuse=args.reuse_transcript,
            )
            if args.stage == "transcribe":
                return 0
            # all requires plan already — won't auto-call GPT
            print("Stage all без внешнего LLM недоступен. После plan.json запусти --stage assemble")
            return 0

        stage_assemble(
            work=args.work,
            plan_path=args.plan,
            out_name=args.out_name,
            overlap=args.overlap,
            also_resolve=args.also_resolve,
        )
        return 0
    except Exception as e:
        print("FAIL:", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
