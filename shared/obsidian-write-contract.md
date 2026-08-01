# Obsidian Write Contract

Общий контракт для всех skills, записывающих файлы в Obsidian vault (`Знания/Ресерчи/`, `Периоды/`).

---

## 1. Pre-write: проверка дубликатов и связей

Перед записью нового файла в vault выполни через Bash:

```bash
# 1. Проверка дубликатов по ключевым словам темы
DUPES=$(obsidian search query="{КЛЮЧЕВЫЕ_СЛОВА}" path="{TARGET_PATH}" limit=5 format=json 2>/dev/null) || DUPES="CLI_UNAVAILABLE"

# 2. Поиск связанных заметок для wikilinks
RELATED=$(obsidian search query="{КЛЮЧЕВОЕ_СЛОВО}" limit=10 format=json 2>/dev/null) || RELATED="CLI_UNAVAILABLE"
```

### Решение по дубликатам

- **CLI_UNAVAILABLE** → пропусти, запиши через Write напрямую (без wikilinks на vault)
- **Точный match по теме** (>70% совпадение) → в frontmatter добавь `supersedes: "[[Старый файл]]"`, в body добавь `> [!info] Обновляет [[Старый файл]]`
- **Частичный match** → собери список имён файлов для wikilinks в секции "Связанные заметки"
- **Нет совпадений** → пиши новый файл без wikilinks на vault (кроме тех, что явно упомянуты в контенте)

### Правила wikilinks

- Wikilinks `[[Название]]` — ТОЛЬКО для заметок, найденных через `obsidian search` (реально существующих в vault)
- НЕ создавай wikilinks на несуществующие заметки (создают "unresolved" в графе)
- НЕ используй wikilinks в frontmatter tags
- Wikilinks допустимы в body: секции "Связанные заметки", inline-ссылки на найденные заметки

---

## 2. Callout Mapping (Obsidian Flavored Markdown)

| Элемент отчёта | Callout | Когда использовать |
|---|---|---|
| TL;DR / главный вывод | `> [!abstract]` | Всегда в начале отчёта |
| Рекомендация HIGH evidence | `> [!tip]` | GRADE HIGH/STRONG + Evidence STRONG |
| Рекомендация WEAK evidence | `> [!question]` | GRADE LOW/WEAK + Evidence WEAK |
| Red flags | `> [!warning]` | Industry COI, small N, single-center |
| Критические риски (safety) | `> [!danger]` | Побочные эффекты, противопоказания |
| Чего НЕ делать | `> [!failure]` | Анти-паттерны, ошибки |
| Adversarial review findings | `> [!bug]` | Оспоренные claims, GRADE downgrade |
| Gaps / пробелы | `> [!todo]` | Недостаточно данных, нужно доисследовать |
| Methodology notes | `> [!info]` | Circular reporting, bias, context |
| Цитаты из community | `> [!quote]` | Дословные цитаты из Reddit/HN/Twitter |

### Правила применения callouts

- Callout — для ключевых элементов, НЕ для каждого абзаца
- Внутри callout допустим markdown (bold, links, lists)
- Nested callouts (callout внутри callout) — НЕ использовать
- Foldable callouts (`> [!tip]-`) — только для длинных секций (>5 строк)

---

## 3. Embeds для перекрёстных ссылок

Если найдены связанные заметки на шаге Pre-write:

```markdown
## Связанные заметки
- [[Название связанной заметки]] — краткое пояснение связи
```

Embed конкретной секции (`![[Файл#Секция]]`) — только если связь критична и секция короткая.

---

## 4. Post-write: обновление связей

После записи файла в vault:

```bash
# 1. Прокинуть в дневную заметку (если Obsidian запущен)
obsidian append path="Периоды/День/$(date +%F).md" content="- [[{NOTE_NAME}]] — {DRAFT_TYPE}, ожидает ревью" 2>/dev/null || true

# 2. Проверить orphan status (информационно)
BACKLINKS=$(obsidian backlinks file="{NOTE_NAME}" counts 2>/dev/null) || BACKLINKS="CLI_UNAVAILABLE"
```

- Если `BACKLINKS` = 0 и CLI доступен → сообщить пользователю: "Заметка-orphan, нет входящих ссылок"
- Если CLI_UNAVAILABLE → пропустить, ничего не ломается

### Draft types для записи в дневную заметку

| Skill | DRAFT_TYPE |
|---|---|
| search-paper | научный ресерч |
| full-research | полное исследование |
| full-research (social only) | community ресерч |

---

## 5. Fallback при закрытом Obsidian

Все CLI-вызовы обёрнуты в `2>/dev/null || ...` → при недоступности CLI шаги pre-write и post-write пропускаются, файл пишется через Write. Callouts — чистый markdown, применяются всегда.

---

## 6. Ловушки CLI (проверено 2026-07)

- **`obsidian daily:append` не существует** — только `obsidian append path="Периоды/День/$(date +%F).md"`; у `append` есть только параметры `file/path/content/inline`.
- **`append` не создаёт файл** и возвращает **exit 0** при «File not found» → `|| true` глотает провал молча. Если запись важна — сначала проверить наличие файла, скелет дневной заметки создавать `Write`.
- **`obsidian search` флаки** (читает живую панель поиска асинхронно): один и тот же запрос даёт `0 / 148 / 0`. Гонять 2–3 раза, брать непустой результат. Для точной проверки существования — `obsidian read path="..."`.
- **Дневная заметка структурирована** (раздел «Хронология» в середине) → `append` пишет только в конец файла; записи в хронологию вносить через `Edit`.
