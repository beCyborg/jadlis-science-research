# Epistemonikos Protocol

**Source ID:** epistemonikos
**Prefix:** `[ep*]`
**Role:** search (база systematic reviews и их matrix-связей — sibling Cochrane, шире по охвату SR)

---

## Назначение

Epistemonikos (epistemonikos.org) — крупнейшая курируемая база systematic reviews и связанных primary studies («matrix of evidence»). Ценность:
- **SR-heavy** — приоритет на systematic reviews / overviews, дополняет PubMed/Cochrane по охвату не-Cochrane обзоров.
- **Matrix** — связывает SR с их included primary studies (полезно для оценки overlap / circular reporting).
- Многоязычная индексация, но запрос — на английском.

Записи — это `systematic-review` / `review` (реже primary). НЕ дублируй то, что уже пришло из Cochrane/PubMed (дедуп по DOI сделает snowball-dedup агент).

---

## Primary: scrape результатов поиска (firecrawl)

У Epistemonikos нет стабильного открытого REST API для агентов — используем scrape страницы поиска. Загрузи firecrawl через ToolSearch (`select:mcp__plugin_jadlis-research_firecrawl__firecrawl_scrape`).

### Поиск

URL поиска (классификация SR):
```
https://www.epistemonikos.org/en/search?q={REFINED_QUERY_EN_URLENCODED}&classification=systematic-review
```

```
mcp__plugin_jadlis-research_firecrawl__firecrawl_scrape({
  url: "https://www.epistemonikos.org/en/search?q={REFINED_QUERY_EN_URLENCODED}&classification=systematic-review",
  formats: ["markdown"],
  onlyMainContent: true,
  waitFor: 4000
})
```

Из markdown выдели карточки результатов: title, тип (systematic review / structured summary), год, журнал, ссылку на запись. DOI часто виден на странице записи — при необходимости scrape конкретной записи `https://www.epistemonikos.org/en/documents/{slug}` для DOI.

### Парсинг

Для каждого результата извлеки:
- title
- studyType: `systematic-review` (или `review` для overview, `meta-analysis` если явно)
- year
- doi (если показан; иначе null — НЕ выдумывай)
- externalId: Epistemonikos document id/slug если есть
- contrib: 1 предложение о выводе обзора

---

## Fallback: Brave с site-filter

Если firecrawl недоступен или 0 карточек:
1. Загрузи brave (`select:mcp__plugin_jadlis-research_brave-search__brave_web_search`).
2. Один вызов:
```
mcp__plugin_jadlis-research_brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN} systematic review",
  count: 8,
  goggles: "$discard\n$site=epistemonikos.org"
})
```
3. Из результатов вытащи title + URL записи; DOI помечай null, если не виден.
4. Если и это пусто → записать `{WORK_DIR}/epistemonikos.md` с `## Epistemonikos UNAVAILABLE`.

Pipeline продолжит без источника (минимум 2 других).

---

## Маппинг в схему PAPER

| Поле | Источник |
|------|----------|
| `prefix` | `[ep1]`, `[ep2]`, ... |
| `doi` | со страницы записи (если есть), иначе null |
| `externalId` | Epistemonikos document id/slug |
| `studyType` | `systematic-review` / `review` / `meta-analysis` |
| `isOA` | false если неизвестно |
| `citations`/`fwci` | null (не предоставляются) |
| `qualitySignals` | `["systematic-review"]` + `"epistemonikos-curated"` |

---

## Rate limits

firecrawl scrape ~1 req/sec. На 429 → wait 1s, retry (max 2). Не более 2-3 scrape-вызовов суммарно (поиск + 1-2 записи за DOI).

---

## Output format

```markdown
# Epistemonikos — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов: сколько SR найдено, есть ли overview, общий вектор выводов]

## Обзоры
### [ep1] {Title}
**Type:** systematic review / structured summary
**Year:** ...
**DOI:** ... (или N/A)
**Epistemonikos:** {document id/url}
**Contrib:** {вывод обзора одним предложением}

## Мета
- Найдено: N
- Метод: firecrawl scrape / Brave fallback
```
