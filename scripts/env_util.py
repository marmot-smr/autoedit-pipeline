from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def cursor_api_key() -> str | None:
    key = (os.getenv("CURSOR_API_KEY") or "").strip()
    return key or None
