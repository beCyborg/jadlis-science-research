# Obsidian Write Contract

Общий контракт для всех skills, записывающих файлы в Obsidian vault (`Знания/Ресерчи/`, `Периоды/`).

---

## 1. Pre-write: проверка дубликатов и связей

Перед записью нового файла в vault выполни через Bash:

Порядок: (1) MCP `qmd` `query` payload'ом (lex+vec, `collections:["znaniya"]`, см. `Jadlis/CLAUDE.md` «Поиск по смыслу») → (2) детерминированный grep → (3) `obsidian search` только как fallback (флаки, 2–3×).

```bash
# 1. Проверка дубликатов по ключевым словам темы (детерминированно; grep в обход обёртки)
DUPES=$(command grep -rIl "{КЛЮЧЕВЫЕ_СЛОВА}" "{TARGET_PATH}" 2>/dev/null)

# 2. Поиск связанных заметок для wikilinks (fallback — obsidian search, гонять 2–3×)
RELATED=$(obsidian search query="{КЛЮЧЕВОЕ_СЛОВО}" limit=10 format=json 2>/dev/null) || RELATED="CLI_UNAVAILABLE"
```

### Решение по дубликатам

- **CLI_UNAVAILABLE** → пропусти, запиши через Write напрямую (без wikilinks на vault)
- **Точный match по теме** (>70% совпадение) → в frontmatter добавь `supersedes: "[[Старый файл]]"`, в body добавь `> [!info] Обновляет [[Старый файл]]`
- **Частичный match** → собери список имён файлов для wikilinks в секции "Связанные заметки"
- **Нет совпадений** → пиши новый файл без wikilinks на vault (кроме тех, что явно упомянуты в контенте)

### Правила wikilinks

- Wikilinks `[[Название]]` — ТОЛЬКО для заметок, найденных через qmd/grep/`obsidian search` (реально существующих в vault; точная проверка — `test -e` / `obsidian read path=...`)
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
# 1. Прокинуть в дневную заметку (если Obsidian запущен); путь — из core Daily notes
DAILY=$(obsidian daily:path 2>/dev/null) || DAILY="Периоды/День/$(date +%F).md"
obsidian append path="$DAILY" content="- [[{NOTE_NAME}]] — {DRAFT_TYPE}, ожидает ревью" 2>/dev/null || true
# в начало тела (после frontmatter) — obsidian prepend path="$DAILY" content="..." 

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

## 6. Ловушки CLI (проверено 2026-07, дополнено 2026-08-25)

- **`daily:path/read/append/prepend` доступны только при включённом core Daily notes** (включён 25.08; выключен → «Daily notes plugin is not enabled»). `daily:path` отдаёт путь до создания файла. У `append` параметры `file/path/content/inline`. **`daily:append` при отсутствующей дневной заметке создаёт её из шаблона** core Daily notes и пишет строку (ответ «Added to: Периоды/День/YYYY-MM-DD.md»; проверено 2026-08-27 в прогоне daily-news-swot: заметки 27.08 не было, после `daily:append` файл появился со ссылкой, grep = 1) — предварительный `obsidian daily` для создания не нужен. Это относится только к `daily:append`; про `append path=…` — пункт ниже.
- **`obsidian create --help` не печатает справку, а создаёт заметку `Untitled.md`** — справку смотреть в скилле `obsidian-cli`.
- **`append` не создаёт файл** и возвращает **exit 0** при «File not found» → `|| true` глотает провал молча. Если запись важна — сначала проверить наличие файла, скелет дневной заметки создавать `Write`.
- **exit 0 у `append` не гарантирует запись даже в СУЩЕСТВУЮЩИЙ файл.** 2026-08-01, full-research Phase C: дневная заметка была на месте, `obsidian append` вернул exit 0 без единой ошибки в stdout/stderr — но строка в файл не попала (Read после append её не показал). Поэтому после ЛЮБОГО `obsidian append` не доверять exit-коду вообще, а проверять фактический результат: `command grep` добавленной строки в целевом файле (не `ls`). Строки нет → **не повторять append**, а дописать через `Edit` (найти якорный заголовок вроде `## Заметки` и вставить после него). Файла нет вовсе → создать минимальный скелет через `Write` (frontmatter `type: day` + навигация + `### Хронология`) по образцу последней дневной заметки.
- **`obsidian search` флаки** (читает живую панель поиска асинхронно): один и тот же запрос даёт `0 / 148 / 0`. Гонять 2–3 раза, брать непустой результат. Для точной проверки существования — `obsidian read path="..."`.
- **Дневная заметка структурирована** (раздел «Хронология» в середине) → `append` пишет только в конец файла; записи в хронологию вносить через `Edit`.
- **Внешняя правка `.md` при открытом Obsidian может быть молча откачена.** Наблюдалось 2026-07-07 на `2026-Q2 — Хроника.md`: Edit в 02:08 → на диске старая версия в 02:09 → правленая вернулась в 02:10; итог недетерминирован (редактор держит файл в памяти + Obsidian Sync гоняет версии). После Edit'а vault-заметки при запущенном Obsidian перепроверять результат на диске (`command grep` по вставленному фрагменту) спустя ~30–60 с, а не сразу; при откате повторить правку. Если заметка почти наверняка открыта у пользователя — править через `obsidian` CLI (идёт через API приложения, консистентно с памятью редактора). Вложения класть в vault ДО вставки embed'ов: «cannot be found» часто значит, что файла ещё нет.
- **При живом workflow `obsidian files`/`search` виснут >120 с** (CLI читает живую панель Obsidian, которую держат занятой параллельные агенты). Зафиксировано 2026-08-24 в Phase C full-research при ещё идущем парном прогоне: `obsidian files | head -1` и `obsidian search` упёрлись в 120-секундный таймаут Bash-тула, а `obsidian append` отработал за секунды и запись подтвердилась grep'ом (панель он не трогает). Поэтому при живом workflow дедуп и подбор wikilinks — `mcp__qmd__query` (lex+vec, `collections:["znaniya"]`, `rerank:false`) + `test -e` на точное имя; `obsidian append` — в `run_in_background` с grep-проверкой. Заметку, записанную минуту назад, qmd уже находит (индекс обновляется ~15–60 с).
- **Существование заметки ПО ИМЕНИ файла проверять Python-сканом с `unicodedata.normalize('NFC', …)`, не `find -name` и не `ls | grep`.** Две независимые причины ложных «не найдено» (обе подтверждены 2026-08-03): (1) **NFD-нормализация macOS** — имя `Суточный протокол приёма БАДов.md` лежит на диске в разложенной форме (`ё` = `е` + U+0308), и `find -name "…приёма…"` с NFC-строкой не матчит; (2) **BSD `grep -i` не делает case-folding кириллицы** — `ls | grep -i "суточный"` не находит `Суточный`, регистронезависимость работает только для ASCII. Ложное «не найдено» → дубликат заметки или unresolved-ссылка в графе. Рабочая проверка (и заодно детектор unresolved wikilinks):
  ```python
  import os, unicodedata
  allnotes = set()
  for dp, dn, fn in os.walk(root):
      dn[:] = [d for d in dn if not d.startswith('.')]
      allnotes |= {unicodedata.normalize('NFC', f)[:-3] for f in fn if f.endswith('.md')}
  ```
  Верификация записи по фразе из заголовка тоже ненадёжна: имя файла и `# Заголовок` внутри отчёта часто не совпадают — проверять существование файла, а не grep по тексту.
