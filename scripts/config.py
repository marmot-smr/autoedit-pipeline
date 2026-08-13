from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
PROCESSING = ROOT / "processing"
OUT = ROOT / "out"
JOBS = ROOT / "jobs"
TEMPLATES = ROOT / "templates"
MUSIC_DIR = TEMPLATES / "music"
DEFAULT_TZ = TEMPLATES / "tz.default.json"
EXAMPLE_TZ = TEMPLATES / "tz.example.json"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".webm", ".m4v"}
AUDIO_EXTS = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".aiff", ".aif"}

RESOLVE_SCRIPT_API = Path(
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
)
RESOLVE_SCRIPT_LIB = Path(
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
)
