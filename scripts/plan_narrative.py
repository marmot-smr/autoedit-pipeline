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


def enforce_shot_framing(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Same `shot` id => identical focus/vfocus/zoom (first clip wins).
    Abutting clips without shot change and nearly-identical framing intent:
    if shot missing but end==next.start and framing differs a lot, warn via note field.
    """
    by_shot: dict[str, dict[str, float]] = {}
    out: list[dict[str, Any]] = []
    for c in clips:
        c = dict(c)
        shot = c.get("shot")
        if shot is not None and str(shot) != "":
            key = str(shot)
            if key not in by_shot:
                by_shot[key] = {
                    "focus": float(c.get("focus") if c.get("focus") is not None else 0.5),
                    "vfocus": float(c.get("vfocus") if c.get("vfocus") is not None else 0.28),
                    "zoom": float(c.get("zoom") if c.get("zoom") is not None else 1.1),
                }
            c["focus"] = by_shot[key]["focus"]
            c["vfocus"] = by_shot[key]["vfocus"]
            c["zoom"] = by_shot[key]["zoom"]
        out.append(c)

    # Detect abutting framing jerks when shot ids differ but shouldn't visually
    for i in range(1, len(out)):
        prev, cur = out[i - 1], out[i]
        abut = abs(float(cur["start"]) - float(prev["end"])) <= 0.08
        if not abut:
            continue
        same_shot = prev.get("shot") is not None and prev.get("shot") == cur.get("shot")
        if same_shot:
            continue
        # If both lack shot and framing jumps on abut — flag
        if prev.get("shot") is None and cur.get("shot") is None:
            pf = float(prev.get("focus") if prev.get("focus") is not None else 0.5)
            cf = float(cur.get("focus") if cur.get("focus") is not None else 0.5)
            pz = float(prev.get("zoom") if prev.get("zoom") is not None else 1.1)
            cz = float(cur.get("zoom") if cur.get("zoom") is not None else 1.1)
            if abs(pf - cf) > 0.04 or abs(pz - cz) > 0.03:
                cur["framing_warning"] = (
                    "abutting cut with framing change but no shot id — "
                    "set shot=same or only change framing on a real reverse"
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
    cleaned = enforce_shot_framing(cleaned)
    plan = dict(plan)
    plan["clips"] = cleaned
    plan["total_selected_sec"] = round(sum(float(c["end"]) - float(c["start"]) for c in cleaned), 2)
    warnings = [c.get("framing_warning") for c in cleaned if c.get("framing_warning")]
    if warnings:
        plan["framing_warnings"] = warnings
        for w in warnings:
            print("WARN framing:", w)
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
- Связный arc: hook → build → payoff (нужен итог, не только cliff)
- Hard cut картинки; audio fade ≤6 кадров только на гэпах
- Каждому клипу поле shot; focus/vfocus/zoom менять ТОЛЬКО при смене shot
- Одинаковый shot → одинаковое кадрирование (иначе дёрганье камеры)
- target_duration_sec ≈ {brief.get('target_duration_sec', 45)}
- Верни/запиши plan.json:

{{
  "thesis": "...",
  "narrative_arc": "...",
  "snap_to_transcript": false,
  "audio_fade_frames": 4,
  "review_subtitles": ["..."],
  "clips": [
    {{"start": 0.0, "end": 0.0, "shot": "A", "role": "hook|build|turn|payoff",
      "why": "...", "focus": 0.5, "vfocus": 0.22, "zoom": 1.1, "text": "..."}}
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
