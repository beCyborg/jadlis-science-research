# Europe PMC Protocol

**Source ID:** europe-pmc
**Prefix:** `[em*]`
**Role:** search

---

## Primary: скрипт (начни отсюда)

```bash
python3 "{PLUGIN_ROOT}/scripts/source-fetch.py" europepmc --query '(TITLE:melatonin OR ABSTRACT:melatonin) AND (TITLE:"delayed sleep phase" OR ABSTRACT:"delayed sleep phase")' --limit {LIMIT} --preprints --out "{WORK_DIR}/_fetch_europepmc.json"
```

Ключей у Europe PMC нет, прелюд `secret.sh` не нужен. **Строку запроса передавай уже с полями**
(`TITLE:` / `ABSTRACT:` — см. ниже, пример в команде именно поэтому развёрнут): расстановку полей
скрипт за тебя не делает, всё остальное делает. `--preprints` — только для `discipline=biomedical`.

Скрипт: проход 1 `sort=CITED desc` на LIMIT, проход 2 за свежими (`FIRST_PDATE:[год−3 TO год]`,
`sort=P_PDATE_D desc`, треть LIMIT), подзапрос препринтов (`AND SRC:PPR`, до 10 штук **сверх**
LIMIT, с флагом `preprint: true` и фоллбэком на запрос без `sort`), `resultType=core` ради
аннотаций, слияние и дедуп. Критерий отказа — отсутствие `hitCount` (retry через 3 с) — зашит
в скрипт: `hitCount: 0` вернётся как `apiStatus=empty` и `exit 0`, а не как отказ.

В stdout — одна строка сводки, в `--out` — JSON:
`{source, apiStatus, total (hitCount), passes[], truncated, remaining, note, papers[]}`;
в `papers[]` — `title, doi` (нормализованный), `pmid, externalId` (вида `MED:20430886`), `year,
pubTypes[], citations, influentialCitations, fwci, isOA, oaUrl, abstract` (≤1500 знаков), `pass`,
у препринтов дополнительно `preprint: true` и `date`. Чего API не отдал — `null`.

**Несколько запросов за один вызов.** Ядро даёт источнику основной запрос плюс короткие запросы по
подтемам. Все они исполняются ОДНИМ вызовом — иначе каждый запрос стоит отдельного хода агента:
заменяй `--query '…'` на `--queries-file "{WORK_DIR}/_queries_europepmc.json"` (JSON-список строк, первая
= основной запрос). Бюджет на запрос — `max(8, LIMIT / число запросов)`; в выводе появляется
`queries[]` с `total` и `kept` по каждому, у статьи — `queryIndex`. Статью из доп. запроса не
выбрасывай за то, что её нет в основном: она и есть добор по подтеме.

**Правило:** `exit 2` / `apiStatus=unavailable` → ручной путь ниже и его фоллбэк (LIMITED Brave);
иначе ручные `curl` НЕ нужны. `apiStatus=empty` фоллбэк НЕ запускает.

**Бюджет ходов: 5–8 на источник** — запустить скрипт → Read JSON → оценить релевантность и
отранжировать до TOP-{LIMIT} (препринты — отдельной секцией) → Write дамп → вернуть ответ по схеме.
Если первый проход явно мимо темы или почти пуст, можно запустить скрипт ещё раз с уточнённой
строкой запроса, но **не более 3 запусков скрипта суммарно**.

---

## Primary: REST API

> Ручной путь — референс и фоллбэк. Нужен, только если скрипт вернул `exit 2`.

**Endpoint:** `https://www.ebi.ac.uk/europepmc/webservices/rest/search`

НЕ `europepmc.org/RestfulWebService` — это страница документации, не query endpoint.

### Search

```bash
curl -s "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={REFINED_QUERY_EN_URLENCODED}&format=json&pageSize={LIMIT}&resultType=core&sort=CITED+desc"
```

> **Каждый концепт запроса — с полем `TITLE:` / `ABSTRACT:`.** Europe PMC без указания поля ищет
> по полному тексту, и `sort=CITED desc` поднимает знаменитые статьи, где термин упомянут мимоходом.
> Замер 21.09.2026 на теме «melatonin + delayed sleep phase» против списков литературы двух
> систематических обзоров (88 работ по теме): запрос без полей + `CITED desc` — **0 попаданий в
> TOP-50**; он же без сортировки — 0; с полями + `CITED desc` — 7/9/12 в TOP-20/30/50
> (а с полями, но без сортировки — 0/0/1: сортировка по цитируемости здесь нужна).
>
> Форма: `(TITLE:melatonin OR ABSTRACT:melatonin) AND (TITLE:"delayed sleep phase" OR ABSTRACT:"delayed sleep phase" OR ABSTRACT:DSWPD)`.
> Строка от query-builder пришла без полей → расставь их сам, логику AND/OR не меняй.
>
> Второй проход ради свежих работ, которые цитируемость топит: тот же запрос с полями +
> `FIRST_PDATE:[{год−3} TO {год}]`, `sort=P_PDATE_D desc`, `pageSize` = треть LIMIT; результаты обоих
> проходов слей и дедуплицируй до TOP-{LIMIT}.

### Критерий отказа: НЕТ поля `hitCount` = API недоступен

HTTP-код отказ **не** сигналит. 21.09.2026 `rest/search` и `rest/searchPOST` на любой запрос
отдавали `HTTP 200` с телом `{"version":"6.9"}` — без `hitCount` и без `resultList`
(позже в тот же день тот же эндпоинт отвечал `HTTP 503`; `rest/article/MED/{pmid}` работал всё время).

Правило:

- **Нет поля `hitCount` в ответе → источник недоступен**, независимо от статуса (200, 503, что угодно).
  → retry 1× через 3 сек → всё ещё нет `hitCount` → LIMITED Brave fallback (ниже).
- **`hitCount: 0` — законный пустой результат, НЕ отказ.** Запрос отработал, статей нет:
  `sourceQuality` MEDIUM, `papers=[]`, в findings — «запрос отработал, 0 попаданий», Brave НЕ звать.
- Проверка одной строкой: `jq -e 'has("hitCount")' response.json` (rc 0 = живой, rc≠0 = отказ).

### Фильтры

| Фильтр | Europe PMC syntax |
|--------|------------------|
| Year range | `&query={QUERY}+FIRST_PDATE:[{start_year}+TO+{end_year}]` |
| Open access | `&query={QUERY}+OPEN_ACCESS:y` |
| Has DOI | `&query={QUERY}+HAS_DOI:y` |
| Source (PubMed) | `&query={QUERY}+SRC:MED` |
| Source (препринты) | `&query={QUERY}+SRC:PPR` |

### Препринты — второй запрос (только discipline=biomedical)

У bioRxiv/medRxiv нет поиска по ключевым словам: их API (`api.biorxiv.org/details/{server}/{from}/{to}/{cursor}`)
отдаёт только выгрузку по диапазону дат. Поэтому канал препринтов в биомедицине — Europe PMC
с фильтром `SRC:PPR`, отдельного протокола под bioRxiv/medRxiv нет.

```bash
curl -s "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=%28{REFINED_QUERY_EN_URLENCODED}%29%20AND%20SRC%3APPR&format=json&pageSize=10&resultType=core&sort=P_PDATE_D%20desc"
```

> `sort=P_PDATE_D desc` (сортировка по дате публикации, свежие сверху) проверен живым запросом 21.09.2026
> вечером, когда поиск поднялся: `melatonin AND SRC:PPR` → `hitCount: 1049`, сортировка принята. Если API
> вернёт ошибку или пустой `resultList` именно на `sort`, повтори тот же запрос **без** параметра `sort`
> и отсортируй TOP-10 сам по `firstPublicationDate` (свежие сверху).

Правила:

- Запрос — тот же, что в основном поиске, плюс `AND SRC:PPR`. `pageSize=10`.
- **Препринты НЕ входят в бюджет LIMIT** — это до 10 статей **сверх** основного TOP-{LIMIT}.
- `studyType` — из общего enum по дизайну исследования (`rct`, `cohort`, `meta-analysis`, …),
  НЕ подменять его на `preprint`. Сам факт препринта идёт сигналом качества:
  в `qualitySignals` добавь `preprint` (не прошёл рецензирование).
- В дампе препринты идут **отдельной секцией** `## Препринты (SRC:PPR)`, не вперемешку со статьями.
- Основной поиск отказал (нет `hitCount`) → подзапрос препринтов не делаем.

### Response parsing

Ключевые поля из JSON response:
```
resultList.result[].title
resultList.result[].authorString
resultList.result[].doi
resultList.result[].pmid
resultList.result[].pubYear
resultList.result[].journalTitle
resultList.result[].citedByCount
resultList.result[].isOpenAccess  // "Y" или "N"
resultList.result[].abstractText
```

### Rate Limits

- Без API key: нет жёстких лимитов, но reasonable use policy
- Рекомендуется: не более 10 RPS
- Source: europepmc.org/RestfulWebService

---

## Fallback: LIMITED Brave (max 1 call)

При недоступности Europe PMC REST API (критерий — **нет поля `hitCount`**, см. выше; `hitCount: 0` фоллбэк НЕ запускает):

1. **Retry 1x** через 3 сек
2. Если повторный fail → **LIMITED Brave fallback** (max 1 call):

```
mcp__plugin_jadlis-search_brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN}",
  count: 10,
  goggles: "$discard\n$site=europepmc.org"
})
```

3. Если Brave тоже fails → записать `{WORK_DIR}/europe-pmc.md` с `## Europe PMC UNAVAILABLE`
Label: **"LIMITED FALLBACK"** в ## Мета секции.

---

## Output format

**SIZE CAP: ≤ 20KB (~300 строк)**
Per paper: metadata + 1 sentence Contrib. No full abstracts.
>LIMIT papers → composite TOP-LIMIT (citations + recency), rest compressed. LIMIT задаёт ядро в промпте агента (дефолт 30); число 20 в примерах ниже и выше — только иллюстрация.

```markdown
# Europe PMC — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов]

## Статьи
### [em1] {Title}
**DOI:** ...
**PMID:** ...
**Authors:** ...
**Year:** ...
**Journal:** ...
**Study type:** ... (определить из title/abstract)
**N:** ... (если в abstract)
**Citations:** {citedByCount}
**OA:** yes/no
**Contrib:** {главный result}

## Препринты (SRC:PPR)
[только discipline=biomedical; до 10 записей СВЕРХ TOP-LIMIT; пусто — напиши «нет»]
### [em{N}] {Title}
**DOI:** ...
**Preprint server:** bioRxiv / medRxiv / Research Square / ...
**Date:** {firstPublicationDate}
**Study type:** ... (обычный enum: rct/cohort/…)
**Quality signals:** preprint (не прошёл рецензирование), ...
**Contrib:** {главный result}

## Мета
- Найдено: N (hitCount: {hitCount})
- Препринтов (SRC:PPR): N / «подзапрос не делался»
- Query EN: "..."
- Качество: HIGH/MEDIUM/LOW
```
