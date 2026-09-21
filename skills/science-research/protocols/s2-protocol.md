# Semantic Scholar Protocol

**Source ID:** s2
**Prefix:** `[s2*]`
**Role:** search

---

## Primary: скрипт (начни отсюда)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
python3 "{PLUGIN_ROOT}/scripts/source-fetch.py" s2 --query '{REFINED_QUERY_EN}' --limit {LIMIT} --out "{WORK_DIR}/_fetch_s2.json"
```

Скрипт: `/graph/v1/paper/search` по релевантности с полным набором `fields` (abstract, externalIds,
publicationTypes, citationCount, influentialCitationCount, openAccessPdf, year), заголовок
`x-api-key` из env, лимит 1 RPS соблюдён паузой, на 429 — backoff и повтор (из-за этого запуск
может занять до ~20 с — это нормально, а не зависание).

В stdout — одна строка сводки, в `--out` — JSON:
`{source, apiStatus, total, passes[], truncated, remaining, note, papers[]}`;
в `papers[]` — `title, doi` (нормализованный), `pmid, externalId` (S2 paperId — нужен для
чейсинга), `year, pubTypes[]` (из `publicationTypes` — по ним определяй `studyType`), `citations,
influentialCitations` (уникальный сигнал S2), `fwci` (null — S2 его не даёт), `isOA, oaUrl,
abstract` (≤1500 знаков), `pass`, плюс `fieldsOfStudy`. Чего API не отдал — `null`.

**Правило:** `exit 2` / `apiStatus=unavailable` → ручной путь ниже и его фоллбэк (Brave DEGRADED);
иначе ручные `curl` НЕ нужны.

**Бюджет ходов: 5–8 на источник** — запустить скрипт → Read JSON → оценить релевантность и
отранжировать до TOP-{LIMIT} → Write дамп → вернуть ответ по схеме. Если первый проход явно мимо
темы или почти пуст, можно запустить скрипт ещё раз с уточнённой строкой запроса, но **не более
3 запусков скрипта суммарно** (1 RPS — каждый лишний запуск стоит секунд).

---

## Primary: REST API

> Ручной путь — референс и фоллбэк. Нужен, только если скрипт вернул `exit 2`.
> Эндпоинты `/citations`, `/references`, `/batch` и `search/match` скриптом не покрыты —
> ими пользуются фазы snowball и enrich, здесь они остаются справочником.

**Base URL:** `https://api.semanticscholar.org/graph/v1`

### Authentication (ОБЯЗАТЕЛЕН)

```bash
-H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

### Paper ID formats

S2 принимает несколько форматов paper ID в endpoints `/paper/{paper_id}`:

| Format | Example |
|--------|---------|
| S2 Paper ID | `649def34f8be52c8b66281af98ae884c09aef38b` |
| DOI | `DOI:10.1038/nrn3241` |
| ArXiv | `ARXIV:2106.15928` |
| PMID | `PMID:19872477` |
| PubMedCentral | `PMCID:PMC2323236` |
| CorpusId | `CorpusId:215416146` |
| ACL | `ACL:W12-3903` |
| MAG | `MAG:112218234` |
| URL | `URL:https://arxiv.org/abs/2106.15928v1` |

### Standard fields parameter

Comma-separated string, используется во всех endpoints:

```
FIELDS="title,authors,year,abstract,citationCount,influentialCitationCount,publicationTypes,journal,externalIds,isOpenAccess,openAccessPdf,fieldsOfStudy"
```

### Search (relevance)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=${REFINED_QUERY_EN_URLENCODED}&limit=${LIMIT}&fields=${FIELDS}&fieldsOfStudy=${S2_FIELDS_CSV}&year=${START_YEAR}-${END_YEAR}" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

Параметры:
- `query` — поисковый запрос (URL-encoded)
- `limit` — max 100, default 20
- `fields` — comma-separated (см. выше)
- `fieldsOfStudy` — comma-separated (например `Medicine,Biology`)
- `year` — формат `{start}-{end}` (опционально)
- `offset` — для пагинации (default 0)

Response parsing:
```bash
python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Total: {data.get(\"total\", 0)}')
for p in data.get('data', []):
    eid = p.get('externalIds', {})
    doi = eid.get('DOI', 'N/A')
    pdf = (p.get('openAccessPdf') or {}).get('url', '')
    authors = ', '.join(a.get('name', '') for a in (p.get('authors') or [])[:5])
    print(f'---')
    print(f'Title: {p[\"title\"]}')
    print(f'DOI: {doi}')
    print(f'S2 ID: {p.get(\"paperId\", \"\")}')
    print(f'Authors: {authors}')
    print(f'Year: {p.get(\"year\", \"\")}')
    print(f'Journal: {(p.get(\"journal\") or {}).get(\"name\", \"\")}')
    print(f'Type: {\", \".join(p.get(\"publicationTypes\") or [])}')
    print(f'Citations: {p.get(\"citationCount\", 0)} (influential: {p.get(\"influentialCitationCount\", 0)})')
    print(f'OA: {p.get(\"isOpenAccess\", False)} {pdf}')
    print(f'Fields: {\", \".join(p.get(\"fieldsOfStudy\") or [])}')
    print(f'Abstract: {(p.get(\"abstract\") or \"\")[:200]}')
"
```

### Title search (exact match)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
curl -s "https://api.semanticscholar.org/graph/v1/paper/search/match?query=${TITLE_URLENCODED}&fields=${FIELDS}" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

### Paper details

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
curl -s "https://api.semanticscholar.org/graph/v1/paper/${PAPER_ID}?fields=${FIELDS}" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

### Batch paper details (POST, max 500 IDs)

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
curl -s -X POST "https://api.semanticscholar.org/graph/v1/paper/batch?fields=${FIELDS}" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"ids": ["DOI:10.1234/example1", "PMID:12345678"]}'
```

### Citations

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
curl -s "https://api.semanticscholar.org/graph/v1/paper/${PAPER_ID}/citations?fields=title,authors,year,citationCount&limit=${LIMIT}&offset=${OFFSET}" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

Response: `data[].citingPaper` содержит поля запрошенной citing paper.

### References

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
curl -s "https://api.semanticscholar.org/graph/v1/paper/${PAPER_ID}/references?fields=title,authors,year,citationCount&limit=${LIMIT}&offset=${OFFSET}" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

Response: `data[].citedPaper` содержит поля запрошенной referenced paper.

### Bulk search (boolean queries)

Для сложных запросов с boolean syntax (AND, OR, NOT):

```bash
eval "$(bash "{PLUGIN_ROOT}/scripts/secret.sh" --export SEMANTIC_SCHOLAR_API_KEY)"
curl -s "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=${BOOLEAN_QUERY_URLENCODED}&fields=${FIELDS}&fieldsOfStudy=${S2_FIELDS_CSV}&year=${START_YEAR}-${END_YEAR}" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

Отличия от relevance search:
- Поддерживает boolean operators: `+` (AND), `|` (OR), `-` (NOT)
- НЕ ранжирует по relevance (sort by recency)
- Возвращает `token` для пагинации (не offset)
- Лимит до 1000 papers per request
- Используй только когда нужна boolean logic, иначе relevance search лучше

---

## S2 `fields_of_study` по discipline

| Discipline | fields_of_study |
|-----------|-----------------|
| biomedical | `Medicine,Biology` |
| cs | `Computer Science` |
| physics | `Physics` |
| social_science | `Psychology,Economics,Sociology` |
| general | — (не передавать параметр) |

## Influential citations

S2 уникально предоставляет `influentialCitationCount` — цитирования, где данная работа играет ключевую роль (не просто упоминание). `influential_ratio = influential / total` — сильный signal качества.

## Rate Limits (КРИТИЧНО)

- **API Key ОБЯЗАТЕЛЕН** (SEMANTIC_SCHOLAR_API_KEY)
- Authenticated: 1 RPS per key (повышение по запросу)
- Unauthenticated: shared 1000 RPS pool (нестабильный, throttled)
- Source: live-rate-limits.md

## S2 Serial Bottleneck Warning

S2 search-агент (Fan-out) и citation-chasing (Snowball, `/citations` + `/references`) оба идут через S2 API при 1 RPS — serial bottleneck. Поэтому в Snowball нагрузка смещена на **OpenAlex (100 RPS)**: S2 используется только для hub-ов без OpenAlex ID и через batch-endpoint. Citation graph — теперь штатная фаза Snowball ядра `search-paper-core` (не post-MVP).

---

## Error Handling

При ошибке S2 API (HTTP != 200):
1. Retry 1x через 3 сек
2. Если повторный fail → **Brave fallback** (secondary, degraded quality):
   - Записать `{WORK_DIR}/s2.md` с `## S2 DEGRADED FALLBACK` заголовком
   - Выполнить:
   ```
   mcp__plugin_jadlis-search_brave-search__brave_web_search({
     query: "{REFINED_QUERY_EN} research paper peer-reviewed",
     count: 10,
     extra_snippets: true
   })
   ```
   - Пометить все результаты как `source: brave-fallback` (не S2 metadata quality)
3. Если Brave fallback тоже fails → записать `{WORK_DIR}/s2.md` с `## S2 UNAVAILABLE` и причиной
4. Pipeline продолжит без S2 (минимум 2 других source)

---

## Output format

**SIZE CAP: ≤ 20KB (~300 строк)**
Per paper: metadata + 1 sentence Contrib. No full abstracts.
>LIMIT papers → composite TOP-LIMIT (citations + recency), rest compressed. LIMIT задаёт ядро в промпте агента (дефолт 30); число 20 в примерах ниже и выше — только иллюстрация.

```markdown
# Semantic Scholar — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов]

## Статьи
### [s21] {Title}
**DOI:** ...
**S2 ID:** ...
**Authors:** ...
**Year:** ...
**Journal:** ...
**Study type:** ... (из publicationTypes)
**N:** ... (если в abstract)
**Citations:** {citationCount} (influential: {influentialCitationCount})
**OA:** yes/no ({openAccessPdf.url})
**Fields:** {fieldsOfStudy}
**Contrib:** {главный result}

## Мета
- Найдено: N
- Query EN: "..."
- fieldsOfStudy filter: {S2_FIELDS}
- Качество: HIGH/MEDIUM/LOW
```
