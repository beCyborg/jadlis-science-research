# PubMed Protocol

**Source ID:** pubmed
**Prefix:** `[pm*]`
**Role:** search

---

## Primary: скрипт (начни отсюда)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export PUBMED_API_KEY PUBMED_EMAIL)"
python3 "{PLUGIN_ROOT}/scripts/source-fetch.py" pubmed --query '{REFINED_QUERY_EN}' --limit {LIMIT} --out "{WORK_DIR}/_fetch_pubmed.json"
```

Скрипт делает ровно то, что описано ниже руками: `sort=relevance`, **три прохода** (доказательный
с `[pt]`-фильтром на половину LIMIT + наблюдательный на четверть + общий на четверть), слияние и
дедуп, затем efetch за аннотациями, типами публикаций, годом и DOI. Ключи — из env
(`tool=search-paper`, `email`, `api_key`), 10 RPS соблюдены.

**Несколько запросов за один вызов.** Ядро даёт источнику основной запрос плюс короткие запросы по
подтемам. Все они исполняются ОДНИМ вызовом — иначе каждый запрос стоит отдельного хода агента:

```bash
python3 "{PLUGIN_ROOT}/scripts/source-fetch.py" pubmed --queries-file "{WORK_DIR}/_queries_pubmed.json" --limit {LIMIT} --out "{WORK_DIR}/_fetch_pubmed.json"
```

Файл — JSON-список строк, первая = основной запрос (за ним остаётся ранжирование при дедупе).
Бюджет на запрос — `max(8, LIMIT / число запросов)`; в выводе появляется `queries[]` с `total` и
`kept` по каждому, у статьи — `queryIndex`. Статью, пришедшую доп. запросом, не выбрасывай за то,
что её нет в основном: она и есть добор по подтеме.

В stdout — одна строка сводки, в `--out` — JSON:
`{source, apiStatus, total, passes[], truncated, remaining, note, papers[]}`;
в `papers[]` — `title, doi` (нормализованный, нижний регистр, без `https://doi.org/`), `pmid,
externalId, year, pubTypes[], citations, influentialCitations, fwci, isOA, oaUrl, abstract`
(≤1500 знаков), `pass` (каким проходом пришла статья). Чего API не отдал — `null`;
идентификаторы не выдумываются.

**Правило:** `exit 2` / `apiStatus=unavailable` → ручной путь ниже и его фоллбэк;
иначе ручные `curl` НЕ нужны.

**Бюджет ходов: 5–8 на источник** — запустить скрипт → Read JSON → оценить релевантность и
отранжировать до TOP-{LIMIT} → Write дамп → вернуть ответ по схеме. Если первый проход явно мимо
темы или почти пуст, можно запустить скрипт ещё раз с уточнённой строкой запроса, но **не более
3 запусков скрипта суммарно**.

---

## Primary: REST E-utilities

> Ручной путь — референс и фоллбэк. Нужен, только если скрипт вернул `exit 2`.

### NCBI Registration Preflight

E-utilities требуют `tool` и `email` для восстановления доступа при IP-блокировке:
- Проверить регистрацию: https://www.ncbi.nlm.nih.gov/account/settings/ → "API Key Management"
- `tool=search-paper` + `email=${PUBMED_EMAIL}` (почта из Связки ключей, прелюд `secret.sh --export`) должны совпадать с NCBI-профилем
- Для batch >100 PMIDs: использовать EFetch History workflow (`usehistory=y` → WebEnv + query_key)

### Search (esearch)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export PUBMED_API_KEY PUBMED_EMAIL)"
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={REFINED_QUERY_EN}&retmax={LIMIT}&sort=relevance&api_key=${PUBMED_API_KEY}&tool=search-paper&email=${PUBMED_EMAIL}&retmode=json"
```

Из JSON ответа: `esearchresult.idlist` → массив PMIDs.

> **`sort=relevance` обязателен.** Без параметра esearch отдаёт самые свежие записи, а не самые
> подходящие. Замер 21.09.2026 (тема «melatonin + delayed sleep phase», эталон — списки литературы
> двух систематических обзоров, 88 работ): тот же `[tiab]`-запрос по дате — 0 попаданий в TOP-50,
> по релевантности — 5.
>
> **Три прохода, результаты слить и дедуплицировать до TOP-{LIMIT}:**
> 1. **Доказательный** — строка запроса + `AND (randomized controlled trial[pt] OR meta-analysis[pt]
>    OR systematic review[pt] OR clinical trial[pt] OR guideline[pt] OR practice guideline[pt])`,
>    `retmax` = **половина** LIMIT. В том же замере: 7/11/13 попаданий в TOP-20/30/50 против 2/4/5
>    у запроса без фильтра типов; на второй теме (формы железа) — 3 против 2.
> 2. **Наблюдательный** — строка запроса + `AND (observational study[pt] OR cohort studies[mh] OR
>    case-control studies[mh] OR cross-sectional studies[mh] OR prospective studies[mh] OR
>    longitudinal studies[mh] OR follow-up studies[mh])`, `retmax` = **четверть** LIMIT.
>    Добавлен 21.09.2026: раньше доказательный проход забирал две трети мест, и когорты бились за
>    оставшуюся треть — Kimblad 2022 (сперма) оказался 19-м при 10 слотах, Carlsson 2017 (диабет)
>    79-м, хотя обе работы были в выдаче. `observational study[pt]` проставляют только с 2014 года,
>    поэтому рядом идут MeSH-заголовки дизайна.
> 3. **Общий** — строка запроса как есть, `retmax` = **четверть** LIMIT: механистика и свежие
>    работы, которым тип публикации ещё не проставлен.
>
> Термины концептов — с `[tiab]` (плюс `[mh]` для MeSH): широкая ветка `OR "…"[mh]` без `[tiab]`
> на основном концепте размывает выдачу (762 записи и 0 попаданий в TOP-50 против 262 и 5).

### Fetch Abstracts (efetch)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export PUBMED_API_KEY)"
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmids_comma_separated}&rettype=abstract&retmode=xml&api_key=${PUBMED_API_KEY}"
```

Из XML: `<PubmedArticle>` → title, authors, abstract, journal, year, DOI, MeSH terms.

### Фильтры PubMed

| Фильтр | PubMed syntax |
|--------|--------------|
| Year range | `{QUERY} AND {start_year}:{end_year}[dp]` |
| Study type | `{QUERY} AND {pubmed_pt}[pt]` (см. source-registry type mapping) |
| Human only | `{QUERY} AND humans[mh]` |
| Free full text | `{QUERY} AND free full text[sb]` |

### Rate Limits

- Без API key: 3 RPS
- С API key (PUBMED_API_KEY): 10 RPS
- Source: live-rate-limits.md

---

## Fallback: LIMITED Brave (max 1 call)

При недоступности E-utilities (network error, rate limit exceeded):

1. **Retry 1x** через 5 сек
2. Если повторный fail → **LIMITED Brave fallback** (max 1 call):

```
mcp__plugin_jadlis-search_brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN}",
  count: 10,
  goggles: "$discard\n$site=pubmed.ncbi.nlm.nih.gov"
})
```

3. Если Brave тоже fails → записать `{WORK_DIR}/pubmed.md` с `## PubMed UNAVAILABLE`

### Парсинг Brave результатов

Из URL извлечь PMID: `pubmed.ncbi.nlm.nih.gov/{PMID}/`
Из text извлечь: title, authors, abstract, year, journal.
Label: **"LIMITED FALLBACK"** в ## Мета секции.

---

## Output format

**SIZE CAP: ≤ 20KB (~300 строк)**
Per paper: metadata + 1 sentence Contrib. No full abstracts.
>LIMIT papers → composite TOP-LIMIT (citations + recency), rest compressed. LIMIT задаёт ядро в промпте агента (дефолт 30); число 20 в примерах ниже и выше — только иллюстрация.

```markdown
# PubMed — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов]

## Статьи
### [pm1] {Title}
**DOI:** ...
**PMID:** ...
**Authors:** ...
**Year:** ...
**Journal:** ...
**Study type:** ...
**N:** ... (если в abstract)
**Citations:** ... (из Phase 5 dedup, если доступно)
**Contrib:** {главный result}
**Quality signals:** ...

## Мета
- Найдено: N
- Query EN: "..."
- Качество: HIGH/MEDIUM/LOW
```
