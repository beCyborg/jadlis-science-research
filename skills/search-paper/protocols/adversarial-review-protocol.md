# Adversarial Review Protocol

**Role:** independent critic (Phase 6)
**Budget:** S2 REST ≤13 | Crossref curl ≤10 | Brave ≤5

---

## 7 шагов

### Шаг 1. Контраргументы к ТОП-3 выводам (no tools)

Для каждого из 3 сильнейших выводов отчёта:
- Почему может быть НЕВЕРЕН?
- Альтернативные объяснения (confounders, reverse causation, placebo)?
- Circular reporting (≥2 papers цитируют один оригинал → 1 independent source)?

### Шаг 2. Live claim verification — S2 REST (max 5 вызовов)

Для 3-5 ключевых claims ищи ОПРОВЕРГАЮЩИЕ данные:

```bash
curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=${CLAIM_URLENCODED}+contradicts+OR+failed+to+replicate+OR+no+effect&limit=5&fields=title,year,citationCount,publicationTypes" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

Результат per claim: **CONFIRMED** / **CHALLENGED** / **OUTDATED**

### Шаг 3. Retraction recheck — Crossref curl (top-10 DOI)

```bash
for doi in {TOP_10_DOIS}; do
  response=$(curl -s "https://api.crossref.org/works/${doi}?mailto=${CROSSREF_MAILTO}" \
    -H "User-Agent: search-paper/1.0 (mailto:${CROSSREF_MAILTO})")
  # check update-to[].type == "retraction"
  echo "$response" | python3 -c "
import json, sys
d = json.load(sys.stdin).get('message', {})
# Отозванная СТАТЬЯ помечается через updated-by[].type=='retraction' (не update-to — это на самом уведомлении).
# Плюс вторичные сигналы: title-префикс 'RETRACTED'/'WITHDRAWN'; update-to[].type=='retraction' (DOI = само уведомление).
upd_by = d.get('updated-by', []) or []
upd_to = d.get('update-to', []) or []
title = (d.get('title') or [''])[0].upper()
retracted = (
    any(u.get('type') == 'retraction' for u in upd_by)
    or title.startswith('RETRACTED') or title.startswith('WITHDRAWN')
    or any(u.get('type') == 'retraction' for u in upd_to)
)
if retracted:
    print(f'RETRACTED: {doi}')
" 2>/dev/null
  sleep 0.1  # polite pool rate limit
done
```

**ВАЖНО:** проверяй `updated-by` (а не только `update-to`). Пример: Wakefield 1998 (`10.1016/S0140-6736(97)11096-0`) — `update-to` пуст, но `updated-by[].type=='retraction'` есть и title начинается с «RETRACTED:».

**HTTP 429 → exponential backoff:** 1s, 2s, 4s. Max 3 retries per DOI.

### Шаг 3.5. PubPeer flag check (top-10 papers)

Для top-10 статей из Evidence Table — проверить через PubPeer:

Прочитай протокол: `{SKILL_DIR}/references/pubpeer-check.md`

Для каждой из top-10 статей:
```
mcp__plugin_jadlis-research_brave-search__brave_web_search({
  query: "site:pubpeer.com \"{first 8 words of paper title}\"",
  count: 3
})
```

| Результат | Действие |
|-----------|----------|
| 0 результатов | `pubpeer_flag: false` |
| ≥1 с matching title | `pubpeer_flag: true` + URL → classify severity |
| title не совпадает | `pubpeer_flag: false` (false positive) |

**Severity classification (ОБЯЗАТЕЛЬНО для каждого PubPeer hit):**
При ≥1 результате — прочитай контент PubPeer записи через Firecrawl (firecrawl_scrape).
Классифицируй severity:
- **critical** — data manipulation, image issues, statistical fraud, fabrication → в таблицу с действием "downgrade"
- **minor** — методологические вопросы, запросы на уточнение → "flag-only" 
- **neutral/positive** — подтверждения, реплики, благодарности → "ignore"
Без severity classification → действие = "flag-only" (НЕ downgrade)

Добавить в output: `### PubPeer flags` секцию с результатами.

### Шаг 4. Publication bias assessment — S2 REST (max 3 вызова) + аналитика

**Citation graph:** для top-3 мета-анализов:
```bash
curl -s "https://api.semanticscholar.org/graph/v1/paper/${S2_PAPER_ID}/citations?limit=20&fields=title,year,citationCount" \
  -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}"
```

Искать в citing papers: "failed to replicate", "no significant effect", "contradicts".

**Аналитическая оценка** (из fulltext данных мета-анализов, если доступны):
- Funnel plot asymmetry — упомянуто ли в тексте?
- Egger's test result — p-value если указан
- Small-study effects — цитируется ли в limitations?

### Шаг 5. GRADE downgrade check (no tools)

Независимая оценка per outcome:
- Не переоценил ли synthesis agent уверенность?
- Проверить каждый downgrade factor (RoB, inconsistency, indirectness, imprecision, pub bias)
- Если расхождение → указать конкретный outcome и предложить корректировку

### Шаг 6. Consensus / scite sanity — Brave (max 3 SEQUENTIAL вызова)

```
mcp__plugin_jadlis-research_brave-search__brave_web_search({
  query: "{MAIN_CONCLUSION}",
  count: 5,
  goggles: "$discard\n$site=consensus.app\n$site=scite.ai"
})
```

Или раздельно по сайтам (1-2 вызова на consensus.app, 1 на scite.ai).
Разногласие с основным выводом → WARNING в отчёте.

### Шаг 7. Gaps + Bias assessment (no tools)

- Geographic bias (все из одной страны/региона?)
- Source-type bias (перекос в сторону одного типа исследований?)
- Temporal bias (основные findings из одного периода?)
- Language bias (только англоязычные?)
- Missing populations (подгруппы не покрыты?)

---

## Output format (≤ 10KB)

```markdown
## Adversarial Review

*Независимая верификация: {DATE}*

### Контраргументы к основным выводам
1. **{Вывод 1}:** {контраргумент} | Опровергло бы: {данные}

### Верификация ключевых claims
| # | Claim | Результат | Источник | Confidence |
|---|-------|-----------|----------|------------|
| V1 | {claim 1} | CONFIRMED/CHALLENGED/OUTDATED | S2 paper + DOI | 0.9 |

### Retraction recheck
| DOI | Status |
|-----|--------|
| ... | clean / RETRACTED |

### PubPeer flags
| # | Paper | PubPeer URL | Severity | Действие |
|---|-------|-------------|----------|----------|
| P1 | {title} | {url или "нет записи"} | critical/minor/neutral/none | downgrade/flag-only/ignore |

Severity classification:
- **critical** — data manipulation, fabrication, statistical errors → downgrade evidence
- **minor** — methodological questions, clarifications → flag в Red Flags, не downgrade
- **neutral/positive** — acknowledgments, replications → ignore
- **none** — нет записи → ignore

### Publication bias
- Funnel plot / Egger's: {findings}
- Citation graph: {findings}

### Circular reporting check
- {analysis of citation independence}

### Bias assessment
- Geographic: ...
- Industry: ...
- Source-type: ...
- Temporal: ...

### Gaps
- {список пробелов}

### Итоговая оценка надёжности
X/10 — {обоснование}

### Рекомендуемые правки
Авторитетная таблица handoff для fix-agent. Каждый actionable finding = одна строка.
Один finding НЕ дублируется (если CHALLENGED claim имеет PubPeer flag — одна строка, не две).

| ID | Claim / Finding | Действие | Confidence | Затрагивает TL;DR | Целевые секции |
|----|-----------------|----------|------------|-------------------|----------------|
| F1 | {claim} | GRADE downgrade / caveat / Red flag / переформулировка | 0.9 | да/нет | TL;DR, Что делать §N, Evidence Table |
| F2 | ... | ... | ... | ... | ... |

Правила:
- ID = F{N}, стабильный в рамках обзора
- Confidence < 0.7 → fix-agent пропустит (speculation)
- Если finding не требует правки текста (чисто информационный gap) → не включать
- M (total) = количество строк в этой таблице
```

---

## Бюджет инструментов — ИТОГО

| Tool | Max вызовов | Шаги |
|------|-------------|------|
| S2 REST `paper/search` | 5 | Шаг 2 |
| S2 REST `paper/{id}/citations` | 3 | Шаг 4 |
| S2 REST (total) | ≤13 | Шаги 2+4 (+ запас) |
| Crossref curl | ≤10 | Шаг 3 |
| Brave `brave_web_search` | ≤5 | Шаги 3.5 + 6 |

**Шаги без инструментов:** 1, 5, 7 — чисто аналитические.
