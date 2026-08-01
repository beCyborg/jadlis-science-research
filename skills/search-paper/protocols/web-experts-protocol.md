# Web Experts Protocol

**Source ID:** web-experts
**Prefix:** `[w*]`
**Role:** search

---

## Назначение

Экспертные интерпретации, evidence-based обзоры, AI-агрегированные данные. НЕ primary research — используется для контекста и sanity check в Phase 5 synthesis.

---

## Primary: Brave Search (тариф Search: 50 req/s — параллель OK)

### Evidence-based expert sources

```
mcp__brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN}",
  count: 10,
  extra_snippets: true,
  goggles: "$discard\n$site=examine.com\n$site=sciencebasedmedicine.org\n$site=statnews.com\n$site=astralcodexten.com\n$site=redpenreviews.org"
})
```

> **scite.ai и consensus.app вынесены в опциональные trust-модули** (`protocols/scite-module.md`, `protocols/consensus-module.md`) — они дают структурированные supporting/contrasting-сигналы и Consensus Meter по API/scrape, а не ловятся web-поиском. Подключаются автоматически при наличии `SCITE_API_KEY` / `CONSENSUS_API_KEY`. Здесь, в web-experts, их site-фильтры больше не используются.

### Domain-specific experts (для biomedical)

```
mcp__brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN} evidence review",
  count: 5,
  goggles: "$discard\n$site=science.org\n$site=nytimes.com\n$site=medicalnewstoday.com"
})
```

### Domain-specific experts (для cs/physics)

```
mcp__brave-search__brave_web_search({
  query: "{REFINED_QUERY_EN} research analysis",
  count: 5,
  goggles: "$discard\n$site=distill.pub\n$site=lilianweng.github.io\n$site=paperswithcode.com"
})
```

### Brave Retry + Partial Results

Если любой из Brave вызовов вернул ошибку (429 или другая):
1. **Wait 1 sec + Retry 1x**
2. Если retry fails → пропустить этот конкретный набор доменов
3. Продолжить с результатами остальных вызовов (partial results mode)
4. Записать в `## Мета` какие группы источников пропущены

Минимум 1 из 3 Brave вызовов должен вернуть результаты для записи файла.

**Rate limit:** Brave (тариф Search) — 50 req/s, три вызова можно параллельно в одном сообщении. На 429 — подождать 1 сек, retry (max 2).

---

## Источники и их роль

| Домен | Роль | Тип | Discipline |
|-------|------|-----|-----------|
| examine.com | Evidence-based supplement/nutrition reviews | Expert review | biomedical |
| sciencebasedmedicine.org | Skeptical medical analysis | Expert blog | biomedical |
| statnews.com | Health/pharma journalism | News | biomedical |
| astralcodexten.com | Deep analytical essays, meta-science | Expert blog | general |
| scite.ai | Smart citations (supporting/contrasting) | AI tool | all |
| consensus.app | AI-aggregated research consensus | AI tool | all |
| science.org | Science/Nature journalism | Expert review | biomedical |
| distill.pub | ML/AI explainers | Expert review | cs |
| paperswithcode.com | SOTA benchmarks, reproducibility | Database | cs |

---

## Парсинг

- Не извлекать как "статьи" — это не peer-reviewed papers
- Извлечь: source, URL, key claims, cited papers (DOI если есть)
- Полезно для Phase 5: "эксперты согласны/не согласны с нашим выводом"
- Полезно для Phase 6: adversarial sanity check

---

## Output format

```markdown
# Web Experts — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов — экспертные интерпретации]

## Источники
### [w1] {Source domain} — {Title}
**URL:** ...
**Type:** expert review / AI aggregation / news
**Key claims:**
- {claim 1}
- {claim 2}
**Referenced papers:** {DOI if mentioned}
**Stance:** supports / contradicts / nuances mainstream view

## AI Aggregation (если доступно)
### consensus.app
- Consensus: {agree/disagree/mixed}
- % studies supporting: ...

### scite.ai
- Supporting citations: N
- Contrasting citations: M

## Мета
- Источников найдено: N
- Query EN: "..."
```
