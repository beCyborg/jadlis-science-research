# Cochrane + Guidelines Protocol

**Source ID:** cochrane-guidelines
**Prefix:** `[co*]` (Cochrane), `[gl*]` (guidelines)
**Role:** search

---

## Skip Condition

Skip если `discipline = cs` ИЛИ `discipline = physics`.

---

## Cochrane CDSR в PubMed

Cochrane CDSR полностью индексируется в PubMed (journal "Cochrane Database Syst Rev") и Europe PMC. Cochrane SR как статьи УЖЕ ловятся через agents pubmed и europe-pmc. Используй Brave ТОЛЬКО для:
- cochranelibrary.com plain-language summaries и GRADE таблиц
- UpToDate, NICE, WHO guidelines (нет другого API)
НЕ используй Brave для поиска Cochrane SR как статей — они уже в PubMed/Europe PMC agents.

---

## Primary: Brave Search (тариф Search: 50 req/s — параллель OK)

### Cochrane Library + UpToDate (combined via Goggles)

```
mcp__brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN} systematic review guidelines",
  count: 8,
  goggles: "$discard\n$site=cochranelibrary.com\n$site=uptodate.com"
})
```

### NICE Guidelines

```
mcp__brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN} guidelines recommendation",
  count: 5,
  goggles: "$discard\n$site=nice.org.uk"
})
```

### WHO / Major Guidelines

```
mcp__brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN} clinical guideline recommendation",
  count: 5,
  goggles: "$discard\n$site=who.int\n$site=cdc.gov"
})
```

### Brave Retry + Partial Results

Если любой из 3 Brave вызовов вернул ошибку (429 или другая):
1. **Wait 1 sec + Retry 1x**
2. Если retry fails → пропустить этот конкретный источник
3. Продолжить с результатами остальных вызовов (partial results mode)
4. Записать в `## Мета` какие источники пропущены

Минимум 1 из 3 вызовов должен вернуть результаты для записи файла.

**Rate limit:** Brave (тариф Search) — 50 req/s, вызовы можно параллельно. На 429 — подождать 1 сек, retry (max 2).

---

## Особенности парсинга

### Cochrane
- Cochrane reviews — gold standard для systematic reviews
- AMSTAR 2 auto-passes (Cochrane methodology enforces PRISMA)
- Извлекать: title, DOI (если есть), main conclusion, GRADE оценку (часто уже есть)
- Cochrane abstracts доступны бесплатно; fulltext — paywall

### UpToDate
- Не peer-reviewed papers — expert clinical summaries
- Отмечать как `type: clinical_guideline`, не включать в Evidence Table
- Полезно для Phase 5 synthesis (что рекомендуют клиницисты)

### NICE
- UK government clinical guidelines
- Evidence-graded (NICE levels)
- Отмечать как `type: clinical_guideline`

---

## Output format

```markdown
# Cochrane + Guidelines — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов — акцент на consensus guidelines]

## Cochrane Reviews
### [co1] {Title}
**DOI:** ...
**Year:** ...
**GRADE (из Cochrane):** ... (если указан)
**Main conclusion:** ...
**Included studies:** N RCTs, total N participants
**Contrib:** {главный result}

## Clinical Guidelines
### [gl1] {Source: NICE/UpToDate/WHO} — {Title}
**URL:** ...
**Year:** ...
**Recommendation:** ...
**Evidence level (source's own):** ...

## Мета
- Cochrane reviews найдено: N
- Guidelines найдено: M
- Query EN: "..."
```
