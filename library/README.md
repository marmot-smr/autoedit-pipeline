# Effects & styles library

Сюда складываются монтажные приёмы: гайды с YouTube и стили, которые уже вывели из сессий.

Агент читает этот каталог, когда ты кидаешь ссылку или говоришь «сделай как в `shot-stable-framing`».

## Как добавить гайд

В чате: «сохрани в библиотеку» + URL YouTube.

Или вручную:

```powershell
.\run.ps1 -LibraryIngest -Url "https://www.youtube.com/watch?v=XXXX"
```

Появится `library/items/<id>.json` со статусом `stub`. После просмотра агент заполняет `learned_rules` и ставит `ready`.

## Как открыть оболочку

```powershell
.\run.ps1 -Library
```

Браузер: http://127.0.0.1:8765 — карточки, превью YouTube, ссылка, проекты где уже применяли.

## Файлы

| Путь | Что |
|------|-----|
| `catalog.json` | Индекс id (пересобирается скриптом) |
| `items/*.json` | Одна карточка = один приём |
| `_item.template.json` | Шаблон новой карточки |
| `ui/` | HTML-оболочка |

Поле `applied_in` — список job-slug (например `young_sherlock_s01e01`), не сырые видео.
