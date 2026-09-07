# arXiv Protocol

**Source ID:** arxiv
**Prefix:** `[ax*]`
**Role:** search

---

## Skip Condition

Skip если `discipline = biomedical` И запрос НЕ содержит слова "preprint", "pre-print", "bioRxiv", "medRxiv".

---

## Primary: REST API

**Endpoint:** `http://export.arxiv.org/api/query`

### Search

```bash
curl -s "http://export.arxiv.org/api/query?search_query=all:{REFINED_QUERY_EN_URLENCODED}&start=0&max_results={LIMIT}&sortBy=relevance&sortOrder=descending"
```

### Response parsing (Atom XML)

```
entry/title
entry/author/name
entry/id              // "http://arxiv.org/abs/2401.12345v1" → arXiv ID
entry/published       // ISO date
entry/summary         // abstract
entry/arxiv:primary_category/@term  // cs.AI, q-bio.NC, etc.
entry/link[@title="pdf"]/@href      // PDF URL
entry/arxiv:doi       // DOI если есть
```

### Фильтры arXiv

| Фильтр | arXiv syntax |
|--------|-------------|
| Category | `&search_query=cat:{category}+AND+all:{query}` |
| Date range | Нет прямого фильтра — post-hoc filtering по `published` |

### Rate Limits

- 1 запрос каждые 3 секунды (нет API key)
- Source: arXiv API user manual

---

## Error Handling (NO Brave fallback)

arXiv имеет rate limit 1 req / 3 сек. При ошибке:
1. Wait 3 сек (rate limit), retry 1x
2. Если повторный fail → записать `{WORK_DIR}/arxiv.md` с `## arXiv UNAVAILABLE`
3. Pipeline продолжит без arXiv (минимум 2 других source)

---

## DOI для arXiv

Многие arXiv papers не имеют DOI. Для дедупликации использовать:
1. arXiv ID → check S2 для DOI enrichment
2. Fuzzy title match (Jaccard ≥ 0.85)

---

## Output format

**SIZE CAP: ≤ 20KB (~300 строк)**
Per paper: metadata + 1 sentence Contrib. No full abstracts.
>20 papers → composite TOP-20 (citations + recency), rest compressed.

```markdown
# arXiv — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов]

## Статьи
### [ax1] {Title}
**DOI:** ... (или "N/A — preprint")
**arXiv ID:** ...
**Authors:** ...
**Year:** ...
**Category:** ...
**Study type:** preprint (+ определить из title/abstract)
**Contrib:** {главный result}

## Мета
- Найдено: N
- Query EN: "..."
- Качество: HIGH/MEDIUM/LOW
```
