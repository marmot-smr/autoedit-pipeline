from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DEFAULT_TZ, EXAMPLE_TZ, MUSIC_DIR
from media_utils import load_json, merge_tz, resolve_music_path


REQUIRED_HINTS = """
Кратко как писать ТЗ (файл video.tz.json рядом с видео):

{
  "title": "имя_проекта",
  "format": { "width": 1080, "height": 1920, "fps": 30 },
  "clips": [
    { "start": 0, "end": 8.5, "zoom": 1.0 },
    { "start": 20, "end": 30, "zoom": 1.1 }
  ],
  "music": {
    "file": "bg_soft.wav",
    "volume_db": -18,
    "fade_in_sec": 1,
    "fade_out_sec": 2,
    "loop": true
  },
  "options": {
    "mute_source_audio": false,
    "detect_scene_cuts": false,
    "create_subtitles": false
  },
  "export": { "enabled": true, "format": "mp4", "codec": "H264" }
}

Правила:
- clips пустой [] = всё видео целиком
- start/end в секундах исходника
- music.file — имя из templates/music/
- volume_db: обычно -22..-14 под речь
- без ТЗ берётся templates/tz.default.json
"""


def validate(path: Path) -> int:
    raw = load_json(path)
    tz = merge_tz(raw)
    errors: list[str] = []
    warnings: list[str] = []

    fmt = tz.get("format") or {}
    for key in ("width", "height", "fps"):
        if key not in fmt:
            errors.append(f"format.{key} отсутствует")

    clips = tz.get("clips") or []
    for i, c in enumerate(clips):
        if "start" not in c or "end" not in c:
            errors.append(f"clips[{i}]: нужны start и end")
            continue
        if float(c["end"]) <= float(c["start"]):
            errors.append(f"clips[{i}]: end должен быть > start")

    music = tz.get("music") or {}
    if music.get("file"):
        p = resolve_music_path(music["file"])
        if not p:
            errors.append(f"music.file не найден: {music['file']} (папка {MUSIC_DIR})")
        vol = music.get("volume_db")
        if vol is not None and not (-60 <= float(vol) <= 6):
            warnings.append("volume_db обычно в диапазоне -60..0")

    print("TZ:", path)
    print("Resolved title:", tz.get("title"))
    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(" -", w)
    if not errors:
        print("OK")
        print(json.dumps(tz, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def main() -> int:
    if len(sys.argv) < 2:
        print(REQUIRED_HINTS)
        print("Примеры:", DEFAULT_TZ, EXAMPLE_TZ)
        print("Usage: python validate_tz.py path/to/file.tz.json")
        return 0
    return validate(Path(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
