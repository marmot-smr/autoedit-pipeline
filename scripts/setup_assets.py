from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import MUSIC_DIR
from media_utils import make_placeholder_music


def main() -> int:
    target = MUSIC_DIR / "bg_soft.wav"
    if target.is_file():
        print("exists:", target)
    else:
        make_placeholder_music(target, duration_sec=90.0)
        print("created:", target)
    print("OK assets ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
