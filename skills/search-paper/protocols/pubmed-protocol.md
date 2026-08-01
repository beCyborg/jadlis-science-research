# PubMed Protocol

**Source ID:** pubmed
**Prefix:** `[pm*]`
**Role:** search

---

## Primary: REST E-utilities

### NCBI Registration Preflight

E-utilities требуют `tool` и `email` для восстановления доступа при IP-блокировке:
- Проверить регистрацию: https://www.ncbi.nlm.nih.gov/account/settings/ → "API Key Management"
- `tool=search-paper` + `email=${PUBMED_EMAIL}` (твоя почта из `settings.json` → `env`) должны совпадать с NCBI-профилем
- Для batch >100 PMIDs: использовать EFetch History workflow (`usehistory=y` → WebEnv + query_key)

### Search (esearch)

```bash
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={REFINED_QUERY_EN}&retmax={LIMIT}&api_key=${PUBMED_API_KEY}&tool=search-paper&email=${PUBMED_EMAIL}&retmode=json"
```

Из JSON ответа: `esearchresult.idlist` → массив PMIDs.

### Fetch Abstracts (efetch)

```bash
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
mcp__plugin_jadlis-research_brave-search__brave_web_search({
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
>20 papers → composite TOP-20 (citations + recency), rest compressed.

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
