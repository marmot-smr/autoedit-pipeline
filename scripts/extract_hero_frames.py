from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT
from media_utils import ffmpeg_exe

VIDEO = next(ROOT.joinpath("processing").rglob("*.mkv"))
OUT_DIR = ROOT / "processing" / "_hero_frames"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Candidate times: prior peaks + spread through episode (avoid credits)
CANDIDATES = [
    120, 180, 240, 320, 400, 480, 560, 600, 650, 700, 750, 820, 900,
    1000, 1100, 1200, 1350, 1500, 1650, 1800, 1950, 2100, 2200, 2350,
    2450, 2550, 2650, 2750, 2850, 2950, 3050,
]


def grab(t: float) -> Path:
    out = OUT_DIR / f"t_{int(t):04d}.jpg"
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-ss",
        str(t),
        "-i",
        str(VIDEO),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(out),
    ]
    subprocess.run(cmd, capture_output=True, check=False)
    return out


def main() -> int:
    print("video", VIDEO)
    paths = []
    for t in CANDIDATES:
        p = grab(t)
        ok = p.is_file() and p.stat().st_size > 1000
        print(("OK" if ok else "FAIL"), t, p.name, p.stat().st_size if p.exists() else 0)
        if ok:
            paths.append({"t": t, "path": str(p)})
    (OUT_DIR / "index.json").write_text(json.dumps(paths, indent=2), encoding="utf-8")
    print("frames", len(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
