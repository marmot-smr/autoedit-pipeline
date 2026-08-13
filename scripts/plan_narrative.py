"""Helpers for narrative plans. Planning itself is done by Cursor agent (chat/subscription)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from media_utils import load_json, save_json


def snap_to_segments(clips: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return clips
    out = []
    for c in clips:
        start = float(c["start"])
        end = float(c["end"])
        covered = [s for s in segments if s["end"] > start and s["start"] < end]
        if not covered:
            nearest = min(
                segments,
                key=lambda s: abs(((s["start"] + s["end"]) / 2) - (start + end) / 2),
            )
            covered = [nearest]
        s0 = max(0.0, covered[0]["start"] - 0.05)
        s1 = covered[-1]["end"] + 0.08
        if s1 - s0 < 1.5:
            try:
                idx = segments.index(covered[-1])
            except ValueError:
                idx = 0
            if idx + 1 < len(segments):
                s1 = segments[idx + 1]["end"] + 0.08
        out.append(
            {
                **c,
                "start": round(s0, 2),
                "end": round(s1, 2),
                "text": " ".join(s["text"] for s in covered),
            }
        )
    return out


def finalize_plan(
    plan: dict[str, Any],
    transcript: dict[str, Any] | None = None,
    *,
    snap: bool | None = None,
) -> dict[str, Any]:
    clips = plan.get("clips") or []
    do_snap = plan.get("snap_to_transcript", True) if snap is None else snap
    if do_snap and transcript and transcript.get("segments"):
        clips = snap_to_segments(clips, transcript["segments"])
    cleaned = []
    for c in clips:
        if float(c["end"]) - float(c["start"]) >= 1.2:
            cleaned.append(c)
    plan = dict(plan)
    plan["clips"] = cleaned
    plan["total_selected_sec"] = round(sum(float(c["end"]) - float(c["start"]) for c in cleaned), 2)
    return plan


def export_agent_pack(transcript: dict[str, Any], brief: dict[str, Any], out_dir: Path) -> Path:
    """Compact files for Cursor agent to write plan.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    segs = transcript.get("segments") or []
    # Keep readable size for chat context
    lines = []
    for s in segs:
        lines.append(f"{s['start']:.2f}\t{s['end']:.2f}\t{s['text']}")
    (out_dir / "transcript_segments.tsv").write_text("\n".join(lines), encoding="utf-8")
    save_json(out_dir / "brief.json", brief)
    prompt = f"""Собери план вертикальной нарезки 9:16.

BRIEF:
{json.dumps(brief, ensure_ascii=False, indent=2)}

ПРАВИЛА:
- Одна общая мысль (thesis) на всю нарезку
- Не резать посередине фразы — таймкоды по границам сегментов из TSV
- Связный arc: hook → build → payoff
- target_duration_sec ≈ {brief.get('target_duration_sec', 45)}
- Верни/запиши plan.json:

{{
  "thesis": "...",
  "narrative_arc": "...",
  "clips": [
    {{"start": 0.0, "end": 0.0, "role": "hook|build|turn|payoff", "why": "...", "zoom": 1.15, "pan": 0}}
  ]
}}

Сегменты: transcript_segments.tsv (start end text)
"""
    (out_dir / "PROMPT_FOR_CURSOR.md").write_text(prompt, encoding="utf-8")
    return out_dir / "PROMPT_FOR_CURSOR.md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--finalize", type=Path, help="plan.json to snap to transcript")
    ap.add_argument("--transcript", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.finalize:
        plan = load_json(args.finalize)
        tr = load_json(args.transcript) if args.transcript else None
        plan = finalize_plan(plan, tr)
        out = args.out or args.finalize
        save_json(out, plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    print("Planning is done by Cursor agent. Use run_quality_edit.py --stage transcribe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
