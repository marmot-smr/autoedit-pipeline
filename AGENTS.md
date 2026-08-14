# Agent guide — AutoEdit Pipeline

## Workflow (каждый новый ролик)

1. Положи исходник в `inbox/` (или укажи путь).
2. Скопируй `templates/brief.teaser.defaults.json` → `jobs/<slug>/brief.json` и заполни только job-поля (hero, idea, title).
3. `.\run.ps1 -Quality -Brief "jobs\<slug>\brief.json"` → транскрипт + `agent_pack/`.
4. По `agent_pack/` и правилам в `.cursor/rules/` собери `jobs/<slug>/plan.json`.
5. **Перед монтажом** перечитай итоговые субтитры целиком. Если продукт не «бомба» — перепиши план, не собирай.
6. `.\run.ps1 -Assemble -Brief "jobs\<slug>\brief.json" -Plan "jobs\<slug>\plan.json"`.
7. Проверь `out/*.mp4` (диалоги целые, лица в кадре, музыка не глушит речь).

## Где что лежит

- **Универсальное** (этот репо): скрипты, дефолтные brief, правила агента, **библиотека приёмов**.
- **Job-specific**: `brief.json`, `plan.json`, заметки по эпизоду — в папке джобы / соседнем media-workspace. Не смешивать с ядром.

## Библиотека гайдов / стилей

- Карточки: `library/items/*.json`. Ссылайся по `id` («монтируй как `shot-stable-framing`»).
- Новая ссылка YouTube → ingest в каталог, затем агент заполняет `learned_rules`.
- Оболочка: `.\run.ps1 -Library` (http://127.0.0.1:8765).
- После применения приёма в джобе — `applied_in` на карточке.

## Telegram

Локальный мост: телефон → этот ПК → Cursor agent в cwd.

`.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, `CURSOR_API_KEY`.  
`.\run.ps1 -Telegram` (процесс должен жить). Автостарт: `.\run.ps1 -TelegramAutostart`.

## Не делать

См. `.cursor/rules/pipeline-core.mdc` и `teaser-assembly.mdc`.
