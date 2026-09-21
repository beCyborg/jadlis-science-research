# CORE Protocol

**Source ID:** core
**Prefix:** `[cr*]`
**Role:** search (серая литература и репозиторные OA-копии)

---

## Ниша: чего нет в PubMed/S2/OpenAlex

CORE агрегирует **репозитории**, а не журналы: препринты и постпринты университетских архивов,
диссертации и магистерские работы, технические отчёты, рабочие бумаги институтов, отчёты НКО и
агентств — то есть grey literature. Ради свежих рецензируемых RCT сюда ходить незачем (их лучше
отдадут PubMed и Europe PMC); ценность CORE — в трёх вещах:

1. **Серая литература** — то, что не публиковалось в журнале и потому не попадает в остальные базы
   (важно для оценки publication bias: отрицательные результаты часто живут только в диссертациях).
2. **Диссертации и тезисы** — полные методики там, где в статье осталась пара абзацев.
3. **OA-копия закрытой статьи** — репозиторный PDF для работы, у которой Unpaywall ничего не нашёл
   (этим же рычагом пользуется fulltext-фаза: поиск по DOI → `downloadUrl`).

`studyType` для диссертации/отчёта — `other`, в `qualitySignals` добавляй `grey-literature`
(и `preprint`, если это препринт); в `contrib` честно помечай, что работа не рецензировалась.

---

## Primary: скрипт (начни отсюда)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export CORE_API_KEY)"
python3 "{PLUGIN_ROOT}/scripts/source-fetch.py" core --query 'melatonin AND "delayed sleep phase"' --limit {LIMIT} --out "{WORK_DIR}/_fetch_core.json"
```

Строка запроса — простые ключевые слова EN, из операторов только `AND`/`OR` и кавычки для точной
фразы (пример в команде развёрнут именно поэтому: `AND` между концептами обязателен, см. ниже).

Скрипт: `/v3/search/works/` со слэшем на конце, `Authorization: Bearer` из env, и — главное —
**`fullText` не попадает в вывод вообще**: от него остаётся только булево `hasFullText`.
Ни `Read` сырого ответа, ни `jq`-вырезание больше не нужны.

В stdout — одна строка сводки, в `--out` — JSON:
`{source, apiStatus, total (totalHits), passes[], truncated, remaining, note, papers[]}`;
`remaining` — это `x-ratelimit-remaining` из заголовков, **перенеси его в `## Мета` дампа**.
В `papers[]` — `title, doi` (нормализованный; у репозиторных работ часто `null` — это норма),
`externalId` (CORE id), `year, pubTypes[]` (`documentType`), `isOA, oaUrl` (= `downloadUrl`,
прямой PDF для `pdf-fetch.sh`), `abstract` (≤1500 знаков), `hasFullText`, `repository`, `pass`.
`citations`/`influentialCitations`/`fwci` — `null`, CORE их не даёт.

**Правило:** `exit 2` / `apiStatus=unavailable` → ручной путь ниже и его обработка ошибок
(Brave-фоллбэка у CORE нет — пишем `## CORE UNAVAILABLE`, `sourceQuality="LOW"`, `papers=[]`);
иначе ручные `curl` НЕ нужны.

`--year-from` для CORE скрипт применяет **после** выдачи (синтаксис года у CORE ненадёжен, и молчаливо
пустой ответ хуже честного отсева) — на маленьком LIMIT отсев может срезать всё. Увидел
`apiStatus=empty` и в `note` «year filter applied client-side (N → 0)» — это не отказ: повтори без
`--year-from` и отфильтруй по году сам при ранжировании.

**Бюджет ходов: 5–8 на источник** — запустить скрипт → Read JSON → оценить релевантность и
отранжировать до TOP-{LIMIT} → Write дамп → вернуть ответ по схеме. Если первый проход явно мимо
темы или почти пуст, можно запустить скрипт ещё раз с уточнённой строкой запроса, но **не более
3 запусков скрипта суммарно**.

---

## Primary: REST API v3

> Ручной путь — референс и фоллбэк. Нужен, только если скрипт вернул `exit 2`.
> Поиск по DOI (его использует fulltext-фаза) скриптом не покрыт — он ниже, отдельным блоком.

**Endpoint:** `https://api.core.ac.uk/v3/search/works/`

> **СЛЭШ НА КОНЦЕ ОБЯЗАТЕЛЕН.** Без него сервер отдаёт `301` и HTML-страницу редиректа вместо JSON
> (`curl` без `-L` за редиректом не идёт, и агент видит «пустой ответ» вместо данных).
> Всегда `curl -sL` и всегда `/works/?q=…`.

### Search

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export CORE_API_KEY)"
curl -sL -D /tmp/core_headers.txt \
  "https://api.core.ac.uk/v3/search/works/?q={REFINED_QUERY_EN_URLENCODED}&limit={LIMIT}" \
  -H "Authorization: Bearer ${CORE_API_KEY}" \
  | jq 'del(.results[].fullText)' > /tmp/core_results.json
```

### ⚠️ `fullText` вырезать ДО чтения ответа

Поиск CORE возвращает **полный текст работы прямо в выдаче** — 80–180 тыс. символов на запись.
`limit=20` — это мегабайты, которые затопят контекст агента и обнулят пользу от прогона.

- Никогда не читай сырой ответ поиска через Read/stdout.
- Всегда прогоняй через `jq`: либо `del(.results[].fullText)`, либо явная выборка полей:
  ```bash
  jq '{totalHits, results: [.results[] | {id, title, doi, yearPublished, authors, publisher, downloadUrl, documentType, language}]}'
  ```
- Полный текст нужен точечно (одна работа) → бери `downloadUrl` (прямая ссылка на PDF) и
  `bash {PLUGIN_ROOT}/scripts/pdf-fetch.sh "<downloadUrl>"`, а не `fullText` из выдачи.

### Синтаксис запроса

Строку запроса даёт query-builder ядра: **простые ключевые слова, из операторов только `AND`/`OR`**
(и кавычки для точной фразы). Без скобочных MeSH-конструкций и полевых префиксов PubMed.

`AND` между концептами обязателен: пробел CORE трактует широко — `omega-3 triglycerides`
даёт 18,3 млн попаданий, `omega-3 AND triglycerides` — 1 312 (замер 21.09.2026).

| Что нужно | Как писать |
|-----------|-----------|
| Два концепта | `omega-3 AND triglycerides` |
| Синонимы | `(omega-3 OR "fish oil") AND triglycerides` |
| Точная фраза | `"randomized controlled trial"` |
| Поиск по DOI | `doi:"10.3390/nu2030375"` |

### Rate limits (заголовки ответа)

```
x-ratelimit-limit: 150
x-ratelimit-remaining: <сколько осталось в окне>
x-ratelimit-retry-after: <ISO-время, когда окно обновится>
```

- Читай заголовки каждого ответа (`curl -D`), не жди 429.
- `x-ratelimit-remaining < 5` → остановись и подожди до `x-ratelimit-retry-after` (окно ~1 минута)
  либо заверши работу с тем, что уже собрано. Параллельных запросов к CORE не делай.

### Response parsing

Ключевые поля (после `del(.results[].fullText)`):
```
totalHits                       // всего найдено
results[].id                    // CORE work id
results[].title
results[].authors[].name
results[].doi                   // БЫВАЕТ null — у репозиторных работ DOI часто нет
results[].yearPublished
results[].publisher
results[].documentType          // research / thesis / presentation / …
results[].downloadUrl           // ПРЯМАЯ ссылка на PDF (core.ac.uk/download/….pdf)
results[].dataProviders[].name  // репозиторий-источник
results[].language.name
results[].fullText              // ВЫРЕЗАТЬ (80–180k символов)
```

- `doi: null` — норма, не повод выкидывать работу: пиши `doi=null`, `externalId` = CORE id.
  Без DOI работа не попадёт в Crossref/Unpaywall-обогащение — это ожидаемо.
- `citations`/`influentialCitations`/`fwci` CORE не даёт → `null`.

### Поиск по DOI (используется fulltext-фазой)

```bash
curl -sL "https://api.core.ac.uk/v3/search/works/?q=doi%3A%22{DOI}%22&limit=1" \
  -H "Authorization: Bearer ${CORE_API_KEY}" \
  | jq -r '.results[0].downloadUrl // empty'
```

Пустой вывод = в CORE такой работы нет. Иначе `downloadUrl` — прямой PDF-локус для `pdf-fetch.sh`.

---

## Error Handling (NO Brave fallback)

Brave не отличит репозиторную копию от пересказа и не даст `downloadUrl` — фоллбэк бесполезен.

1. Retry 1x через 3 сек (в т.ч. на 429 — сперва посмотри `x-ratelimit-retry-after`).
2. Повторный fail, нет `CORE_API_KEY`, 401/403 → записать `{WORK_DIR}/core.md` с `## CORE UNAVAILABLE`,
   вернуть `sourceQuality="LOW"`, `papers=[]`.
3. Pipeline продолжит без CORE (минимум 2 других source).

---

## Output format

**SIZE CAP: ≤ 20KB (~300 строк)**
Per paper: metadata + 1 sentence Contrib. No full abstracts, **и никогда — `fullText`**.
>LIMIT papers → composite TOP-LIMIT (citations + recency), rest compressed. LIMIT задаёт ядро в промпте агента (дефолт 30); число 20 в примерах ниже — только иллюстрация.

```markdown
# CORE — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов; отдельно отметь, что нашлось только здесь и нет в журнальных базах]

## Статьи
### [cr1] {Title}
**DOI:** ... (или «нет — репозиторная работа»)
**CORE ID:** ...
**Authors:** ...
**Year:** ...
**Repository:** {dataProviders[].name}
**Document type:** {documentType}
**Study type:** ... (enum; диссертация/отчёт → other)
**N:** ... (если в аннотации)
**Citations:** — (CORE не отдаёт)
**OA:** yes ({downloadUrl})
**Quality signals:** grey-literature / preprint / ...
**Contrib:** {главный result}

## Мета
- Найдено: N (totalHits: {totalHits})
- Query EN: "..."
- x-ratelimit-remaining на выходе: N
- Качество: HIGH/MEDIUM/LOW
```
