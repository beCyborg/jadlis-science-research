# OpenAlex Protocol

**Source ID:** openalex
**Prefix:** `[oa*]`
**Role:** search

---

## Primary: REST API

**Endpoint:** `https://api.openalex.org/works`

### Authentication (ОБЯЗАТЕЛЬНО с 2026)

OpenAlex перешёл на freemium модель с cost-based дневным бюджетом:
- `OPENALEX_API_KEY` — обязателен для стабильной работы
- `OPENALEX_MAILTO` — рекомендуется (polite pool)
- Hard cap: 100 RPS
- Source: live-rate-limits.md

### Search

```bash
curl -s "https://api.openalex.org/works?search={REFINED_QUERY_EN_URLENCODED}&per_page={LIMIT}&sort=cited_by_count:desc&api_key=${OPENALEX_API_KEY}&mailto=${OPENALEX_MAILTO}"
```

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
>20 papers → composite TOP-20 (citations + recency), rest compressed.

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
- Качество: HIGH/MEDIUM/LOW
```
