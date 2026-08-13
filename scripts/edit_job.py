from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import JOBS, MUSIC_DIR, OUT, PROCESSING
from media_utils import (
    merge_tz,
    prepare_music,
    probe_media,
    resolve_music_path,
    save_json,
    sec_to_frames,
)
from resolve_api import get_resolve


def _unique_project_name(base: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in base)[:40]
    return f"AutoEdit_{safe}_{stamp}"


def _set_project_format(project, fmt: dict[str, Any]) -> None:
    w = str(int(fmt.get("width", 1920)))
    h = str(int(fmt.get("height", 1080)))
    fps = fmt.get("fps", 30)
    # Resolve wants string settings
    project.SetSetting("timelineResolutionWidth", w)
    project.SetSetting("timelineResolutionHeight", h)
    project.SetSetting("timelineFrameRate", str(fps))


def _get_clip_fps(media_item) -> float:
    props = media_item.GetClipProperty() or {}
    fps_raw = props.get("FPS") or props.get("Frame Rate") or "30"
    try:
        return float(str(fps_raw).replace(",", "."))
    except ValueError:
        return 30.0


def _get_clip_duration_frames(media_item) -> int:
    props = media_item.GetClipProperty() or {}
    frames = props.get("Frames")
    if frames not in (None, ""):
        try:
            return int(float(frames))
        except ValueError:
            pass
    # fallback via duration string "HH:MM:SS:FF" is messy; use GetClipProperty Duration
    return 0


def build_timeline(
    resolve,
    project,
    media_pool,
    video_path: Path,
    tz: dict[str, Any],
    work_dir: Path,
) -> tuple[Any, dict[str, Any]]:
    resolve.OpenPage("media")
    imported = media_pool.ImportMedia([str(video_path)])
    if not imported:
        raise RuntimeError(f"Не удалось импортировать видео: {video_path}")

    video_clip = imported[0]
    src_fps = _get_clip_fps(video_clip)
    fmt = tz.get("format") or {}
    timeline_fps = float(fmt.get("fps") or src_fps or 30)

    # Prefer source fps for accurate cut points unless TZ overrides
    if "fps" not in fmt:
        fmt = {**fmt, "fps": timeline_fps}
        tz["format"] = fmt

    _set_project_format(project, fmt)

    timeline_name = tz.get("title") or video_path.stem
    timeline = media_pool.CreateEmptyTimeline(str(timeline_name)[:60])
    if not timeline:
        raise RuntimeError("Не удалось создать таймлайн")
    project.SetCurrentTimeline(timeline)

    # Ensure at least one video + stereo audio tracks for music
    while timeline.GetTrackCount("audio") < 2:
        timeline.AddTrack("audio", "stereo")

    options = tz.get("options") or {}
    mute_source = bool(options.get("mute_source_audio", False))
    media_type_video = 1 if mute_source else None  # 1 = video only

    clips_spec = tz.get("clips") or []
    append_infos = []
    zoom_plan: list[float | None] = []

    total_src_frames = _get_clip_duration_frames(video_clip)
    if not clips_spec:
        info: dict[str, Any] = {"mediaPoolItem": video_clip}
        if media_type_video is not None:
            info["mediaType"] = media_type_video
        append_infos.append(info)
        zoom_plan.append(None)
    else:
        for c in clips_spec:
            start = float(c.get("start", 0))
            end = float(c.get("end", start + 1))
            if end <= start:
                continue
            start_f = sec_to_frames(start, src_fps)
            end_f = sec_to_frames(end, src_fps)
            if total_src_frames > 0:
                end_f = min(end_f, total_src_frames - 1)
            info = {
                "mediaPoolItem": video_clip,
                "startFrame": start_f,
                "endFrame": end_f,
            }
            if media_type_video is not None:
                info["mediaType"] = media_type_video
            append_infos.append(info)
            zoom_plan.append(c.get("zoom"))

    items = media_pool.AppendToTimeline(append_infos)
    if not items:
        raise RuntimeError("Не удалось положить клипы на таймлайн")

    # Scaling constants from Resolve scripting docs
    scale_map = {
        "project": 0,
        "crop": 1,
        "fit": 2,
        "fill": 3,
        "stretch": 4,
    }
    default_scale = (options.get("scale") or fmt.get("scale") or "fill")
    scale_value = scale_map.get(str(default_scale).lower(), 3)

    for idx, item in enumerate(items):
        item.SetProperty("Scaling", scale_value)
        zoom = zoom_plan[idx] if idx < len(zoom_plan) else None
        clip_meta = clips_spec[idx] if idx < len(clips_spec) else {}
        if zoom and float(zoom) != 1.0:
            z = float(zoom)
            item.SetProperty("ZoomGang", True)
            item.SetProperty("ZoomX", z)
            item.SetProperty("ZoomY", z)
        if clip_meta.get("pan") is not None:
            item.SetProperty("Pan", float(clip_meta["pan"]))
        if clip_meta.get("tilt") is not None:
            item.SetProperty("Tilt", float(clip_meta["tilt"]))

    if options.get("detect_scene_cuts"):
        try:
            timeline.DetectSceneCuts()
        except Exception:
            pass

    if options.get("create_subtitles"):
        try:
            timeline.CreateSubtitlesFromAudio()
        except Exception:
            pass

    # Music
    music_cfg = tz.get("music") or {}
    music_file = music_cfg.get("file")
    music_src = resolve_music_path(music_file) if music_file else None
    music_note = None

    timeline_start = timeline.GetStartFrame()
    timeline_end = timeline.GetEndFrame()
    timeline_frames = max(1, timeline_end - timeline_start)
    timeline_sec = timeline_frames / timeline_fps

    if music_src and music_src.is_file():
        prepared = prepare_music(
            music_src,
            work_dir,
            volume_db=float(music_cfg.get("volume_db", -18)),
            target_duration_sec=timeline_sec,
            fade_in_sec=float(music_cfg.get("fade_in_sec", 0)),
            fade_out_sec=float(music_cfg.get("fade_out_sec", 0)),
            loop=bool(music_cfg.get("loop", True)),
        )
        music_imported = media_pool.ImportMedia([str(prepared)])
        if not music_imported:
            raise RuntimeError(f"Не удалось импортировать музыку: {prepared}")
        music_clip = music_imported[0]
        music_fps = _get_clip_fps(music_clip) or timeline_fps
        music_frames = _get_clip_duration_frames(music_clip)
        if music_frames <= 0:
            music_frames = sec_to_frames(timeline_sec, music_fps)

        music_info = {
            "mediaPoolItem": music_clip,
            "startFrame": 0,
            "endFrame": max(0, min(music_frames, timeline_frames) - 1),
            "mediaType": 2,  # audio only
            "trackIndex": 2,
            "recordFrame": timeline_start,
        }
        music_items = media_pool.AppendToTimeline([music_info])
        if not music_items:
            music_note = "Музыка импортирована, но не легла на A2 — проверь треки вручную"
        else:
            music_note = f"Музыка: {music_src.name} @ {music_cfg.get('volume_db', -18)} dB"
    elif music_file:
        music_note = f"Файл музыки не найден: {music_file} (искали в {MUSIC_DIR})"

    meta = {
        "timeline_name": timeline.GetName(),
        "timeline_fps": timeline_fps,
        "timeline_sec": timeline_sec,
        "clips_count": len(items),
        "music": music_note,
        "project_name": project.GetName(),
    }
    return timeline, meta


def render_timeline(resolve, project, timeline, out_dir: Path, tz: dict[str, Any]) -> Path | None:
    export = tz.get("export") or {}
    if not export.get("enabled", True):
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    resolve.OpenPage("deliver")
    project.SetCurrentTimeline(timeline)
    project.SetCurrentRenderMode(1)  # single clip

    fmt = (export.get("format") or "mp4").lower()
    codec = export.get("codec") or "H264"
    # Resolve format keys are usually lowercase like "mp4"
    if not project.SetCurrentRenderFormatAndCodec(fmt, codec):
        # try common fallbacks
        fallbacks = [("mp4", "H264"), ("mp4", "H.264"), ("mov", "H264")]
        ok = False
        for f, c in fallbacks:
            if project.SetCurrentRenderFormatAndCodec(f, c):
                fmt, codec = f, c
                ok = True
                break
        if not ok:
            raise RuntimeError(
                "Не удалось выбрать формат/кодек рендера. "
                "Открой Deliver и выставь H.264 вручную, либо укажи export.format/codec в ТЗ."
            )

    custom_name = export.get("custom_name") or tz.get("title") or "auto_edit"
    settings = {
        "SelectAllFrames": True,
        "TargetDir": str(out_dir),
        "CustomName": str(custom_name),
        "ExportVideo": True,
        "ExportAudio": True,
    }
    # Match timeline/project resolution if present
    fmt_res = tz.get("format") or {}
    if fmt_res.get("width") and fmt_res.get("height"):
        settings["FormatWidth"] = int(fmt_res["width"])
        settings["FormatHeight"] = int(fmt_res["height"])
    if fmt_res.get("fps"):
        settings["FrameRate"] = float(fmt_res["fps"])

    if not project.SetRenderSettings(settings):
        raise RuntimeError("SetRenderSettings вернул False")

    job_id = project.AddRenderJob()
    if not job_id:
        raise RuntimeError(
            "AddRenderJob не создал задачу. Часто бывает на Free-версии — "
            "таймлайн уже собран, экспортируй вручную из Deliver."
        )

    if not project.StartRendering(job_id):
        raise RuntimeError("StartRendering не запустился")

    while project.IsRenderingInProgress():
        status = project.GetRenderJobStatus(job_id) or {}
        pct = status.get("CompletionPercentage") or status.get("completionPercentage")
        if pct is not None:
            print(f"  render: {pct}%")
        time.sleep(1.5)

    status = project.GetRenderJobStatus(job_id) or {}
    print(f"  render status: {status}")

    # Find output file
    expected = out_dir / f"{custom_name}.{fmt}"
    if expected.is_file():
        return expected
    # Resolve sometimes adds suffixes
    matches = sorted(out_dir.glob(f"{custom_name}*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def run_job(video_path: Path, tz_path: Path | None, out_dir: Path | None = None) -> dict[str, Any]:
    video_path = video_path.resolve()
    if not video_path.is_file():
        raise FileNotFoundError(video_path)

    user_tz = None
    if tz_path and tz_path.is_file():
        with tz_path.open("r", encoding="utf-8") as f:
            user_tz = json.load(f)
    tz = merge_tz(user_tz)
    if not tz.get("title"):
        tz["title"] = video_path.stem

    out_dir = (out_dir or OUT).resolve()
    work_dir = PROCESSING / f"work_{video_path.stem}_{datetime.now().strftime('%H%M%S')}"
    work_dir.mkdir(parents=True, exist_ok=True)
    save_json(work_dir / "tz.resolved.json", tz)

    probe = probe_media(video_path)
    save_json(work_dir / "probe.json", {k: v for k, v in probe.items() if k != "raw"})

    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project_name = _unique_project_name(tz["title"])
    project = pm.CreateProject(project_name)
    if not project:
        # name collision — try again
        project_name = _unique_project_name(tz["title"] + "_x")
        project = pm.CreateProject(project_name)
    if not project:
        raise RuntimeError("Не удалось создать проект Resolve")

    media_pool = project.GetMediaPool()
    result: dict[str, Any] = {
        "video": str(video_path),
        "tz": str(tz_path) if tz_path else None,
        "project": project_name,
        "ok": False,
    }

    try:
        timeline, meta = build_timeline(resolve, project, media_pool, video_path, tz, work_dir)
        result.update(meta)
        pm.SaveProject()

        rendered = None
        render_error = None
        try:
            rendered = render_timeline(resolve, project, timeline, out_dir, tz)
        except Exception as e:
            render_error = str(e)
            print(f"WARN render: {e}")

        result["output"] = str(rendered) if rendered else None
        result["render_error"] = render_error
        result["ok"] = True
        result["note"] = (
            "Готово"
            if rendered
            else "Таймлайн собран в Resolve. Если export не прошёл — открой Deliver и отрендерь вручную."
        )
        pm.SaveProject()
    except Exception:
        result["ok"] = False
        result["error"] = traceback.format_exc()
        raise
    finally:
        save_json(JOBS / f"{project_name}.json", result)
        save_json(work_dir / "result.json", result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Собрать монтаж в DaVinci Resolve по ТЗ")
    parser.add_argument("video", type=Path, help="Путь к видео")
    parser.add_argument("--tz", type=Path, default=None, help="Путь к tz.json")
    parser.add_argument("--out", type=Path, default=None, help="Папка экспорта")
    args = parser.parse_args(argv)

    print("=== AutoEdit -> DaVinci Resolve ===")
    print(f"video: {args.video}")
    print(f"tz:    {args.tz or '(default)'}")
    try:
        result = run_job(args.video, args.tz, args.out)
    except Exception as e:
        print("FAIL:", e)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
