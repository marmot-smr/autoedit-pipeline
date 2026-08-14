# AutoEdit Pipeline

Универсальный пайплайн коротких вертикальных нарезок (9:16):

1. Локальный транскрипт (`faster-whisper`)
2. Сценарий / `plan.json` — Cursor-агент по правилам в `.cursor/rules/`
3. Сборка FFmpeg (hard cuts + тихая музыка)
4. Опционально — таймлайн в DaVinci Resolve

Медиа и job-специфичное ТЗ **не** живут в этом репо. Клади исходники в `inbox/`, текущие джобы — рядом в рабочей папке проекта (см. `jobs/` только для отчётов).

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1) транскрипт
.\run.ps1 -Quality -Brief "templates\brief.teaser.defaults.json"

# 2) в Cursor: собери plan.json по agent_pack + правилам

# 3) сборка
.\run.ps1 -Assemble -Brief "templates\brief.teaser.defaults.json"
```

## Библиотека приёмов

Гайды с YouTube и стили сессий: `library/`. Оболочка с превью и списком джоб:

```powershell
.\run.ps1 -Library
.\run.ps1 -LibraryIngest -Url "https://www.youtube.com/watch?v=XXXX"
```

В чате достаточно кинуть ссылку и сказать «сохрани в библиотеку» / «монтируй как `<id>`».

## Структура

| Путь | Назначение |
|------|------------|
| `scripts/` | Движок: transcribe / plan helpers / assemble / Resolve |
| `templates/` | Дефолтные brief/tz (без привязки к конкретному сериалу) |
| `.cursor/rules/` | Жёсткие договорённости для агента |
| `AGENTS.md` | Как работать с пайплайном в Cursor |
| `inbox/` `processing/` `out/` | Локальные рабочие папки (в git пустые) |

## Что не коммитить

Видео, транскрипты эпизодов, `plan.json` конкретной джобы, музыку-бинарники, `.venv`.
