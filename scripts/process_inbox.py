from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DEFAULT_TZ, INBOX, OUT, PROCESSING, VIDEO_EXTS
from edit_job import run_job
from media_utils import load_json, save_json


def find_tz_for_video(video: Path) -> Path | None:
    """video.tz.json → same-stem.json → tz.json in same folder → None (defaults)."""
    candidates = [
        video.with_suffix(".tz.json"),
        video.with_name(video.stem + ".json"),
        video.parent / "tz.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def list_inbox_videos(inbox: Path) -> list[Path]:
    if not inbox.is_dir():
        return []
    videos = []
    for p in sorted(inbox.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            # skip incomplete downloads
            if p.name.endswith(".part") or p.name.startswith("~$"):
                continue
            videos.append(p)
    return videos


def process_one(video: Path) -> dict:
    tz_src = find_tz_for_video(video)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = PROCESSING / f"{video.stem}_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)

    video_dst = job_dir / video.name
    shutil.move(str(video), str(video_dst))

    tz_dst = None
    if tz_src and tz_src.is_file():
        # if tz is shared inbox/tz.json — copy, don't steal from other jobs
        if tz_src.name == "tz.json" and tz_src.parent == INBOX:
            tz_dst = job_dir / f"{video.stem}.tz.json"
            shutil.copy2(tz_src, tz_dst)
        else:
            tz_dst = job_dir / tz_src.name
            shutil.move(str(tz_src), str(tz_dst))
    else:
        # materialize default so user can see what was used
        tz_dst = job_dir / f"{video.stem}.tz.json"
        shutil.copy2(DEFAULT_TZ, tz_dst)

    print(f"\n>>> JOB {video.name}")
    print(f"    work: {job_dir}")
    print(f"    tz:   {tz_dst.name}")

    try:
        result = run_job(video_dst, tz_dst, OUT)
        save_json(job_dir / "result.json", result)
        return result
    except Exception as e:
        err = {"ok": False, "error": str(e), "video": str(video_dst)}
        save_json(job_dir / "result.json", err)
        print("FAIL:", e)
        return err


def process_inbox(once: bool = True, poll_sec: float = 3.0) -> int:
    print("Inbox:", INBOX)
    print("Out:  ", OUT)
    print("Resolve должен быть ЗАПУЩЕН. External scripting = Local.")
    failures = 0

    def tick() -> int:
        nonlocal failures
        videos = list_inbox_videos(INBOX)
        if not videos:
            return 0
        for v in videos:
            # wait until file size stable (copy finished)
            prev = -1
            for _ in range(20):
                size = v.stat().st_size
                if size == prev and size > 0:
                    break
                prev = size
                time.sleep(0.5)
            res = process_one(v)
            if not res.get("ok"):
                failures += 1
        return len(videos)

    if once:
        n = tick()
        if n == 0:
            print("Inbox пуст. Положи видео (+ опционально video.tz.json) и запусти снова.")
        return 1 if failures else 0

    print(f"Watch mode: каждые {poll_sec}s")
    while True:
        tick()
        time.sleep(poll_sec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обработать inbox → DaVinci Resolve")
    parser.add_argument("--watch", action="store_true", help="Следить за inbox постоянно")
    parser.add_argument("--poll", type=float, default=3.0, help="Интервал опроса в --watch")
    args = parser.parse_args(argv)
    return process_inbox(once=not args.watch, poll_sec=args.poll)


if __name__ == "__main__":
    sys.exit(main())
