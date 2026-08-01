# Europe PMC Protocol

**Source ID:** europe-pmc
**Prefix:** `[em*]`
**Role:** search

---

## Primary: REST API

**Endpoint:** `https://www.ebi.ac.uk/europepmc/webservices/rest/search`

НЕ `europepmc.org/RestfulWebService` — это страница документации, не query endpoint.

### Search

```bash
curl -s "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={REFINED_QUERY_EN_URLENCODED}&format=json&pageSize={LIMIT}&resultType=core&sort=CITED+desc"
```

### Фильтры

| Фильтр | Europe PMC syntax |
|--------|------------------|
| Year range | `&query={QUERY}+FIRST_PDATE:[{start_year}+TO+{end_year}]` |
| Open access | `&query={QUERY}+OPEN_ACCESS:y` |
| Has DOI | `&query={QUERY}+HAS_DOI:y` |
| Source (PubMed) | `&query={QUERY}+SRC:MED` |

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

При недоступности Europe PMC REST API:

1. **Retry 1x** через 3 сек
2. Если повторный fail → **LIMITED Brave fallback** (max 1 call):

```
mcp__brave-search__brave_web_search({
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
>20 papers → composite TOP-20 (citations + recency), rest compressed.

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

## Мета
- Найдено: N
- Query EN: "..."
- Качество: HIGH/MEDIUM/LOW
```
