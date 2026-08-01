# scite.ai Module (опциональный)

**Source ID:** scite
**Prefix:** `[sc*]`
**Role:** trust-signal (supporting vs contrasting citations — direct сигнал «оспаривают/подтверждают»)
**Статус:** ОПЦИОНАЛЬНЫЙ модуль. Включается только если `modules.scite=true` (скилл выставляет при наличии `SCITE_API_KEY` в env).

---

## Зачем

scite.ai даёт **Smart Citations** — классификацию цитат на *supporting* / *contrasting* / *mentioning*. Это прямой сигнал доверия, дополняющий бесплатные сигналы (OpenAlex citations, Crossref retractions): высокая доля *contrasting* — red flag даже у часто цитируемой статьи.

НЕ ядро доверия (платный) — лишь усиление adversarial-линзы «активно ищи contrasting».

---

## Гейт включения

```
SCITE_API_KEY в env? — НЕТ → этот модуль НЕ запускается (скилл не добавит 'scite' в sources).
                       — ДА  → modules.scite=true, агент запускается.
```

Если агент запущен, но `SCITE_API_KEY` пуст → записать `{WORK_DIR}/scite.md` с `## scite SKIPPED (no key)` и вернуть пустой результат. НЕ блокировать pipeline.

---

## Primary: scite API

**Base:** `https://api.scite.ai`
**Auth:** `-H "Authorization: Bearer ${SCITE_API_KEY}"`

### Tally по DOI (supporting/contrasting/mentioning)

```bash
curl -s "https://api.scite.ai/tallies/{DOI}" -H "Authorization: Bearer ${SCITE_API_KEY}"
```

Ответ: `total`, `supporting`, `contrasting`, `mentioning`, `citingPublications`.

### Batch tallies

```bash
curl -s -X POST "https://api.scite.ai/tallies" \
  -H "Authorization: Bearer ${SCITE_API_KEY}" -H "Content-Type: application/json" \
  -d '{"dois": ["10.x/...", "10.y/..."]}'
```

Подавай DOI ключевых статей (из переданного запроса/контекста). Без отдельного поиска — scite работает по уже найденным DOI как trust-enrichment.

---

## Использование результата

- `contrasting / total > 0.15` → **red flag**: «значимая доля опровергающих цитат», в qualitySignals статьи добавить `"scite-contrasting-high"`.
- `supporting` высок и `contrasting` низок → `"scite-supported"`.
- Передаётся синтезатору как доп. сигнал и критику для секции «Противоречия».

---

## Маппинг

Модуль НЕ добавляет новые PAPER (не поисковик) — возвращает enrichment-сигналы. В схеме SEARCH:
- `papers` = [] (или те же DOI с qualitySignals scite-*), `findings` = сводка supporting/contrasting по ключевым DOI.

## Output format

```markdown
# scite.ai — trust signals по ключевым DOI

## Сводка
- DOI проверено: N
- Со значимой долей contrasting (>15%): M

## По статьям
### {DOI}
- supporting: X / contrasting: Y / mentioning: Z
- flag: scite-contrasting-high / scite-supported / —
```

## Rate limits

Зависит от тарифа ключа. Последовательно, gap ~200ms. На 429 → backoff 1s/2s, max 2.
