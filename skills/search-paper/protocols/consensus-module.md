# Consensus Module (опциональный)

**Source ID:** consensus
**Prefix:** `[cn*]`
**Role:** trust-signal (AI-агрегированный консенсус по вопросу — «yes/no/mixed» + доля поддерживающих исследований)
**Статус:** ОПЦИОНАЛЬНЫЙ модуль. Включается только если `modules.consensus=true` (скилл выставляет при наличии `CONSENSUS_API_KEY` в env).

---

## Зачем

Consensus (consensus.app) агрегирует научные ответы на yes/no-вопросы: «Consensus Meter» (% исследований за/против/смешанно). Полезно как **sanity-check** основного вывода и сигнал для секции «Противоречия».

НЕ ядро доверия (платный/закрытый) — лишь дополнительная линза. Главный риск, который он помогает ловить — ложный консенсус, навязанный одним типом источников.

---

## Гейт включения

```
CONSENSUS_API_KEY в env? — НЕТ → модуль НЕ запускается.
                          — ДА  → modules.consensus=true, агент запускается.
```

Если запущен без ключа → `{WORK_DIR}/consensus.md` с `## consensus SKIPPED (no key)`, пустой результат, pipeline не блокируется.

---

## Primary: Consensus API (если доступен ключ)

Consensus не публикует стабильный открытый REST для агентов. Если у ключа есть документированный endpoint — используй его (Bearer auth). Сформулируй вопрос как yes/no из запроса (напр. «Does omega-3 supplementation lower triglycerides?»).

## Fallback: scrape (firecrawl)

Если API недоступен — scrape публичной страницы результата. Загрузи firecrawl (`select:mcp__plugin_jadlis-research_firecrawl__firecrawl_scrape`):
```
mcp__plugin_jadlis-research_firecrawl__firecrawl_scrape({
  url: "https://consensus.app/search/?q={YES_NO_QUESTION_URLENCODED}",
  formats: ["markdown"],
  onlyMainContent: true,
  waitFor: 5000
})
```
Из markdown вытащи Consensus Meter (yes/possibly/no %), 3-5 ключевых утверждений с цитатами. DOI помечай null, если не виден.

Если и scrape пуст → `## consensus UNAVAILABLE`, пустой результат.

---

## Использование результата

- Consensus Meter сверяется с `mainConclusion` синтеза: расхождение → WARNING критику.
- В схеме SEARCH: `papers` = [] (не поисковик первичных статей), `findings` = Consensus Meter + ключевые утверждения.

## Output format

```markdown
# Consensus — sanity-check по "{YES_NO_QUESTION}"

## Consensus Meter
- Yes / Possibly / No: X% / Y% / Z%
- Вывод: agree / mixed / disagree с основным тезисом

## Ключевые утверждения
- {claim} — {источник, DOI если есть}

## Мета
- Метод: API / firecrawl scrape
```

## Rate limits

firecrawl ~1 req/sec; 429 → wait 1s, retry max 2. Не более 2 вызовов.
