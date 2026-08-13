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

- **Универсальное** (этот репо): скрипты, дефолтные brief, правила агента.
- **Job-specific**: `brief.json`, `plan.json`, заметки по эпизоду — в папке джобы / соседнем media-workspace. Не смешивать с ядром.

## Не делать

См. `.cursor/rules/pipeline-core.mdc` и `teaser-assembly.mdc`.
