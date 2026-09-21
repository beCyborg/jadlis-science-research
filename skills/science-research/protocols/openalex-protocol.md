# OpenAlex Protocol

**Source ID:** openalex
**Prefix:** `[oa*]`
**Role:** search

---

## Primary: скрипт (начни отсюда)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export OPENALEX_API_KEY)"
python3 "{PLUGIN_ROOT}/scripts/source-fetch.py" openalex --query '{REFINED_QUERY_EN}' --limit {LIMIT} --out "{WORK_DIR}/_fetch_openalex.json"
```

Скрипт: проход 1 `filter=title_and_abstract.search:<query>` + `sort=cited_by_count:desc` на LIMIT,
проход 2 по релевантности (без `sort`) за последние 3 года на треть LIMIT, слияние и дедуп,
аннотация собирается обратно из `abstract_inverted_index`. Запятые в строке запроса скрипт
заменяет пробелами (в грамматике `filter` запятая разделяет фильтры) и пишет об этом в `note`.

В stdout — одна строка сводки, в `--out` — JSON:
`{source, apiStatus, total, passes[], truncated, remaining, note, papers[]}`;
`remaining` — это `x-ratelimit-remaining-usd` из заголовков, **перенеси его в `## Мета` дампа**
(`< 0.05` → snowball идёт мимо OpenAlex). В `papers[]` — `title, doi` (нормализованный), `pmid,
externalId` (`Wxxxxxxxxx` — нужен для чейсинга), `year, pubTypes[], citations, influentialCitations,
fwci, isOA, oaUrl, abstract` (≤1500 знаков), `pass`. Чего API не отдал — `null`.

**Правило:** `exit 2` / `apiStatus=unavailable` → ручной путь ниже и его обработка ошибок
(у OpenAlex Brave-фоллбэка нет — пишем `## OpenAlex UNAVAILABLE`); иначе ручные `curl` НЕ нужны.

**Бюджет ходов: 5–8 на источник** — запустить скрипт → Read JSON → оценить релевантность и
отранжировать до TOP-{LIMIT} → Write дамп → вернуть ответ по схеме. Если первый проход явно мимо
темы или почти пуст, можно запустить скрипт ещё раз с уточнённой строкой запроса, но **не более
3 запусков скрипта суммарно**.

---

## Primary: REST API

> Ручной путь — референс и фоллбэк. Нужен, только если скрипт вернул `exit 2`.

**Endpoint:** `https://api.openalex.org/works`

### Authentication (ОБЯЗАТЕЛЬНО с 2026)

OpenAlex перешёл на freemium модель с cost-based дневным бюджетом:
- `OPENALEX_API_KEY` — обязателен; передаётся как `&api_key=` (проверено живым запросом 21.09.2026).
  Тот же ключ принимается и заголовком `Authorization: Bearer` — счётчик общий, разницы нет.
- `mailto=` — **больше НЕ рычаг лимитов.** Polite pool по почте заменён на ключ: с ключом
  `x-ratelimit-limit-usd: 1` (10 000 кредитов/день), без ключа — `0.1` (1 000 кредитов,
  ~100 search-запросов, snowball на этом не живёт). Параметр можно слать как контакт,
  но на лимит он не влияет и отсутствие `OPENALEX_MAILTO` ничего не ломает.
- Hard cap: 100 RPS
- Source: live-rate-limits.md, «Снимок 2026-09-21»

### Search

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export OPENALEX_API_KEY)"
curl -s -D /tmp/openalex_headers.txt "https://api.openalex.org/works?filter=title_and_abstract.search:{REFINED_QUERY_EN_URLENCODED}&per_page={LIMIT}&sort=cited_by_count:desc&api_key=${OPENALEX_API_KEY}"
grep -i 'x-ratelimit-.*-usd' /tmp/openalex_headers.txt
```

> **Сортировка по цитируемости — только поверх `title_and_abstract.search`.** Параметр `search=`
> ищет по полному тексту; в связке с `sort=cited_by_count:desc` наверх всплывают знаменитые статьи,
> где термин упомянут мимоходом. Замер 21.09.2026 на теме «melatonin + delayed sleep phase» против
> списков литературы двух систематических обзоров (88 работ по теме): `search=` + цитируемость —
> **0 попаданий в TOP-50** (первая строка — «Heavy Metal Toxicity and the Environment»), тот же
> запрос через `filter=title_and_abstract.search:` + цитируемость — 7/9/11 в TOP-20/30/50,
> `search=` без `sort` (релевантность) — 9/10/12.
>
> Второй проход ради свежих работ, которые цитируемость топит: тот же фильтр без `sort`
> (релевантность) + `from_publication_date` за последние 3 года, `per_page` = треть LIMIT;
> результаты обоих проходов слей и дедуплицируй до TOP-{LIMIT}.

### Остаток дневного бюджета — читать, а не ждать 429

Каждый ответ несёт заголовки `x-ratelimit-limit-usd` и `x-ratelimit-remaining-usd`
(search-запрос = 10 кредитов = $0.001).

- Забирай `x-ratelimit-remaining-usd` из заголовков (`curl -D`) и пиши его в секцию `## Мета`
  дампа — по нему видно, хватит ли бюджета следующим фазам.
- **`x-ratelimit-remaining-usd < 0.05` → OpenAlex для snowball считается исчерпанным:**
  citation-chasing идёт сразу на Semantic Scholar, а при его отказе — на OpenCitations
  (см. промпт chase-агента), не тратя попытку на заведомый 429.

### Фильтры OpenAlex

| Фильтр | OpenAlex syntax |
|--------|----------------|
| Year range | `&filter=from_publication_date:{start_year}-01-01,to_publication_date:{end_year}-12-31` |
| Open access | `&filter=is_oa:true` |
| Type | `&filter=type:{oa_type}` (article, review, book-chapter) |
| Concept | `&filter=concepts.id:C{concept_id}` |

### Response parsing

Ключевые поля:
```
results[].title
results[].authorships[].author.display_name
results[].doi                          // "https://doi.org/10.xxxx/..."
results[].publication_year
results[].primary_location.source.display_name  // journal
results[].cited_by_count
results[].fwci                         // Field-weighted Citation Impact (уникально!)
results[].type                         // article, review, etc.
results[].open_access.is_oa
results[].open_access.oa_url
results[].concepts[].display_name
results[].ids.pmid                     // PMID если есть
results[].ids.openalex
```

### FWCI — уникальное преимущество OpenAlex

Field-Weighted Citation Impact (FWCI) — нормализован по полю и году. FWCI > 1.0 = выше среднего для данного поля. Предпочтительнее raw citation count для cross-discipline сравнений.

---

## Error Handling (NO Brave fallback)

Brave не даёт FWCI, concepts, structured metadata — fallback бесполезен.

При ошибке OpenAlex REST API:
1. Retry 1x через 3 сек
2. Если повторный fail → записать `{WORK_DIR}/openalex.md` с `## OpenAlex UNAVAILABLE`
3. Pipeline продолжит без OpenAlex (минимум 2 других source)

---

## Output format

**SIZE CAP: ≤ 20KB (~300 строк)**
Per paper: metadata + 1 sentence Contrib. No full abstracts.
>LIMIT papers → composite TOP-LIMIT (citations + recency), rest compressed. LIMIT задаёт ядро в промпте агента (дефолт 30); число 20 в примерах ниже и выше — только иллюстрация.

```markdown
# OpenAlex — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов]

## Статьи
### [oa1] {Title}
**DOI:** ...
**OpenAlex ID:** ...
**Authors:** ...
**Year:** ...
**Journal:** ...
**Study type:** ... (из type + title/abstract heuristic)
**N:** ... (если в abstract)
**Citations:** {cited_by_count} (FWCI: {fwci})
**OA:** yes/no ({oa_url})
**Concepts:** {top-3 concepts}
**Contrib:** {главный result}

## Мета
- Найдено: N
- Query EN: "..."
- x-ratelimit-remaining-usd: {из заголовков ответа}  // < 0.05 → snowball идёт мимо OpenAlex
- Качество: HIGH/MEDIUM/LOW
```
