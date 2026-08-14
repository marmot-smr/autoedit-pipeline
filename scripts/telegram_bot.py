"""Telegram → local Cursor agent on this PC.

Phone text/files go to the AutoEdit workspace; the agent runs locally and replies in Telegram.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import INBOX, OUT, PROCESSING, ROOT
from env_util import cursor_api_key

TG_API = "https://api.telegram.org"
SESSION_PATH = PROCESSING / "telegram_session.json"
MAX_TG = 3900
SEND_FILE_MAX = 45 * 1024 * 1024

SYSTEM = """Ты AutoEdit-агент на ПК пользователя. Рабочая папка:
{root}

Правила: AGENTS.md, .cursor/rules/ (hard cut, shot-стабильное кадрирование, review субтитров, библиотека library/).
Исходники: inbox/. Джобы: jobs/. Выход: out/.

Сообщение ниже — с телефона через Telegram. Сделай работу (план, assemble, ingest гайда, правки).
Ответь по-русски коротко: что сделал, пути файлов, что нужно от пользователя.
Не коммить секреты. Не пушь без явной просьбы.
"""


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def bot_token() -> str:
    t = _env("TELEGRAM_BOT_TOKEN")
    if not t:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в .env")
    return t


def allowed_ids() -> set[int]:
    raw = _env("TELEGRAM_ALLOWED_USER_IDS")
    if not raw:
        raise SystemExit("Нет TELEGRAM_ALLOWED_USER_IDS в .env (свой числовой id)")
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    if not out:
        raise SystemExit("TELEGRAM_ALLOWED_USER_IDS пустой")
    return out


def tg(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{TG_API}/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram {method} HTTP {e.code}: {err[:500]}") from e
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body}")
    return body


def send_text(token: str, chat_id: int, text: str) -> None:
    text = text.strip() or "(пустой ответ агента)"
    for i in range(0, len(text), MAX_TG):
        chunk = text[i : i + MAX_TG]
        tg(token, "sendMessage", {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True})


def send_action(token: str, chat_id: int, action: str = "typing") -> None:
    try:
        tg(token, "sendChatAction", {"chat_id": chat_id, "action": action})
    except Exception:
        pass


def download_tg_file(token: str, file_id: str, dest: Path) -> Path:
    meta = tg(token, "getFile", {"file_id": file_id})["result"]
    file_path = meta["file_path"]
    url = f"{TG_API}/file/bot{token}/{file_path}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as resp:
        dest.write_bytes(resp.read())
    return dest


def extract_incoming(msg: dict[str, Any], token: str) -> tuple[str, list[Path]]:
    parts: list[str] = []
    files: list[Path] = []
    if msg.get("text"):
        parts.append(str(msg["text"]))
    if msg.get("caption"):
        parts.append(str(msg["caption"]))
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if msg.get("document"):
        doc = msg["document"]
        name = doc.get("file_name") or f"doc_{stamp}"
        dest = INBOX / name
        download_tg_file(token, doc["file_id"], dest)
        files.append(dest)
        parts.append(f"[файл сохранён: {dest}]")
    if msg.get("video"):
        dest = INBOX / f"tg_video_{stamp}.mp4"
        download_tg_file(token, msg["video"]["file_id"], dest)
        files.append(dest)
        parts.append(f"[видео сохранено: {dest}]")
    if msg.get("photo"):
        photo = max(msg["photo"], key=lambda p: int(p.get("file_size") or 0))
        dest = INBOX / f"tg_photo_{stamp}.jpg"
        download_tg_file(token, photo["file_id"], dest)
        files.append(dest)
        parts.append(f"[фото сохранено: {dest}]")
    if msg.get("audio") or msg.get("voice"):
        media = msg.get("audio") or msg["voice"]
        ext = ".mp3" if msg.get("audio") else ".ogg"
        dest = INBOX / f"tg_audio_{stamp}{ext}"
        download_tg_file(token, media["file_id"], dest)
        files.append(dest)
        parts.append(f"[аудио сохранено: {dest}]")
    return "\n".join(parts).strip(), files


def load_session() -> dict[str, Any]:
    if SESSION_PATH.is_file():
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    return {}


def save_session(data: dict[str, Any]) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def maybe_send_outputs(token: str, chat_id: int, before: set[str]) -> None:
    after = {p.resolve() for p in OUT.glob("*.mp4")}
    new = [Path(p) for p in sorted(after - before, key=lambda s: Path(s).stat().st_mtime)]
    for path in new[-2:]:
        if path.stat().st_size > SEND_FILE_MAX:
            send_text(token, chat_id, f"Файл слишком большой для Telegram ({path.stat().st_size} байт): {path}")
            continue
        try:
            boundary = "----autoedit"
            with path.open("rb") as fh:
                file_bytes = fh.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="video"; filename="{path.name}"\r\n'
                f"Content-Type: video/mp4\r\n\r\n"
            ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(
                f"{TG_API}/bot{token}/sendVideo",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            send_text(token, chat_id, f"Не смог отправить mp4 в Telegram, лежит локально: {path}\n{e}")


def run_agent(client: Any, prompt: str, *, reset: bool) -> str:
    from cursor_sdk import AgentOptions, LocalAgentOptions

    api_key = cursor_api_key()
    if not api_key:
        raise SystemExit("Нет CURSOR_API_KEY в .env — https://cursor.com/dashboard/integrations")

    model = _env("CURSOR_MODEL") or "composer-2.5"
    opts = AgentOptions(
        model=model,
        api_key=api_key,
        local=LocalAgentOptions(cwd=str(ROOT), setting_sources=["project", "user"]),
    )
    sess = load_session()
    agent_id = None if reset else sess.get("agent_id")
    agent = None
    if agent_id:
        try:
            agent = client.agents.resume(agent_id, opts)
        except Exception as e:
            print("resume failed, new agent:", e)
            agent = None
    if agent is None:
        agent = client.agents.create(opts)
    try:
        save_session({"agent_id": agent.agent_id})
        full = SYSTEM.format(root=ROOT) + "\n\n---\n\n" + prompt
        run = agent.send(full)
        result = run.wait()
        text = ""
        try:
            text = run.text() or ""
        except Exception:
            text = str(getattr(result, "result", "") or "")
        status = getattr(result, "status", None)
        if status and str(status) not in {"finished", "RunStatus.finished", "FINISHED"}:
            text = f"[{status}]\n{text}"
        return text or "(агент ничего не вернул текстом)"
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def handle_command(token: str, chat_id: int, text: str) -> bool:
    cmd = text.strip().split()[0].lower() if text.strip() else ""
    if cmd in {"/start", "/help"}:
        send_text(
            token,
            chat_id,
            "Пиши обычным текстом — агент на ПК сделает работу в папке «видео нарезки».\n"
            "Можно кидать видео/фото в inbox.\n\n"
            "/new — новая сессия агента\n"
            "/status — жив ли бот",
        )
        return True
    if cmd == "/status":
        sess = load_session()
        send_text(token, chat_id, f"Бот на ПК жив.\nworkspace: {ROOT}\nagent_id: {sess.get('agent_id') or 'нет'}")
        return True
    if cmd == "/new":
        save_session({})
        send_text(token, chat_id, "Сессия сброшена. Следующее сообщение откроет нового агента.")
        return True
    return False


def main() -> int:
    os.chdir(ROOT)
    token = bot_token()
    allow = allowed_ids()
    PROCESSING.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)

    from cursor_sdk import CursorClient

    print("Telegram bot polling… workspace:", ROOT)
    offset = 0
    busy = False
    with CursorClient.launch_bridge(workspace=str(ROOT)) as client:
        while True:
            try:
                body = tg(token, "getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message"]})
            except Exception as e:
                print("getUpdates error:", e)
                time.sleep(3)
                continue
            for upd in body.get("result") or []:
                offset = int(upd["update_id"]) + 1
                msg = upd.get("message") or {}
                user = (msg.get("from") or {})
                uid = int(user.get("id") or 0)
                chat_id = int((msg.get("chat") or {}).get("id") or 0)
                if not uid or uid not in allow:
                    if chat_id:
                        send_text(token, chat_id, "Этот бот только для владельца ПК.")
                    continue
                text, _files = extract_incoming(msg, token)
                if not text:
                    continue
                if handle_command(token, chat_id, text):
                    continue
                if busy:
                    send_text(token, chat_id, "Предыдущая задача ещё идёт. Напиши следом, когда отвечу.")
                    continue
                busy = True
                before = {p.resolve() for p in OUT.glob("*.mp4")}
                send_text(token, chat_id, "Принял, запускаю на ПК…")
                send_action(token, chat_id)
                try:
                    reply = run_agent(client, text, reset=False)
                    send_text(token, chat_id, reply)
                    maybe_send_outputs(token, chat_id, before)
                except Exception as e:
                    send_text(token, chat_id, f"Ошибка на ПК: {e}")
                    print("agent error:", e)
                finally:
                    busy = False
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
