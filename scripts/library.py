"""Effects/styles library: ingest YouTube guides, rebuild catalog, serve UI."""
from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "library"
ITEMS = LIB / "items"
UI = LIB / "ui"
CATALOG = LIB / "catalog.json"

YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_youtube_id(url: str) -> str | None:
    raw = url.strip()
    if YT_ID_RE.match(raw):
        return raw
    u = urlparse(raw)
    host = (u.netloc or "").lower().replace("www.", "")
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
        return vid if YT_ID_RE.match(vid) else None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        qs = parse_qs(u.query)
        if qs.get("v"):
            vid = qs["v"][0]
            return vid if YT_ID_RE.match(vid) else None
        parts = [p for p in u.path.split("/") if p]
        if parts and parts[0] in {"embed", "shorts", "live", "v"} and len(parts) > 1:
            vid = parts[1]
            return vid if YT_ID_RE.match(vid) else None
    return None


def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:48] or "guide"


def load_items() -> list[dict[str, Any]]:
    ITEMS.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(ITEMS.glob("*.json")):
        if p.name.startswith("_"):
            continue
        items.append(_load(p))
    return items


def rebuild() -> list[dict[str, Any]]:
    items = load_items()
    _save(CATALOG, {"version": 1, "count": len(items), "ids": [i["id"] for i in items]})
    UI.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(items, ensure_ascii=False)
    (UI / "data.js").write_text(
        f"window.AUTOEDIT_LIBRARY = {payload};\n",
        encoding="utf-8",
    )
    print(f"catalog: {len(items)} items")
    return items


def ingest(url: str, *, item_id: str | None = None, title: str | None = None) -> Path:
    yt = parse_youtube_id(url)
    if not yt:
        raise SystemExit(f"Не распознал YouTube id в: {url}")
    iid = item_id or f"yt-{yt}"
    dest = ITEMS / f"{iid}.json"
    if dest.is_file():
        print("already exists:", dest)
        rebuild()
        return dest
    item = {
        "id": iid,
        "kind": "guide",
        "title": title or f"YouTube {yt}",
        "youtube_url": f"https://www.youtube.com/watch?v={yt}",
        "youtube_id": yt,
        "source": "youtube",
        "status": "stub",
        "imported_at": date.today().isoformat(),
        "summary": "",
        "learned_rules": [],
        "tags": [],
        "applied_in": [],
    }
    _save(dest, item)
    rebuild()
    print("created", dest)
    print("Дальше в чате: агент смотрит гайд и заполняет learned_rules / status=ready.")
    return dest


def mark_applied(item_id: str, job: str, *, title: str = "", note: str = "") -> None:
    dest = ITEMS / f"{item_id}.json"
    if not dest.is_file():
        raise SystemExit(f"Нет карточки {item_id}")
    item = _load(dest)
    apps = item.setdefault("applied_in", [])
    entry = {
        "job": job,
        "title": title or job,
        "when": date.today().isoformat(),
        "note": note,
    }
    apps = [a for a in apps if a.get("job") != job]
    apps.append(entry)
    item["applied_in"] = apps
    _save(dest, item)
    rebuild()
    print("applied", item_id, "→", job)


def serve(port: int = 8765, *, open_browser: bool = True) -> None:
    rebuild()
    if not (UI / "index.html").is_file():
        raise SystemExit("Нет library/ui/index.html")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(UI), **kwargs)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(fmt % args)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print("library UI:", url)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstop")


def main() -> int:
    ap = argparse.ArgumentParser(description="AutoEdit effects library")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("rebuild", help="Пересобрать catalog.json и ui/data.js")

    p_in = sub.add_parser("ingest", help="Добавить YouTube-гайд (stub)")
    p_in.add_argument("--url", required=True)
    p_in.add_argument("--id", dest="item_id", default=None)
    p_in.add_argument("--title", default=None)

    p_ap = sub.add_parser("apply", help="Пометить, что приём использован в джобе")
    p_ap.add_argument("--item", required=True)
    p_ap.add_argument("--job", required=True)
    p_ap.add_argument("--title", default="")
    p_ap.add_argument("--note", default="")

    p_srv = sub.add_parser("serve", help="Открыть HTML-библиотеку")
    p_srv.add_argument("--port", type=int, default=8765)
    p_srv.add_argument("--no-browser", action="store_true")

    args = ap.parse_args()
    if args.cmd == "rebuild":
        rebuild()
    elif args.cmd == "ingest":
        ingest(args.url, item_id=args.item_id, title=args.title)
    elif args.cmd == "apply":
        mark_applied(args.item, args.job, title=args.title, note=args.note)
    elif args.cmd == "serve":
        serve(args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
