# PubPeer Flag Check Protocol

**Версия:** v1.0
**Дата:** 2026-04-20

---

## Назначение

PubPeer (pubpeer.com) — платформа post-publication peer review. Наличие комментариев на PubPeer — red flag, требующий downgrade evidence strength.

## Протокол проверки (Phase 6 Adversarial)

Для **top-10 статей** из Evidence Table:

### Шаг 1: Поиск через Brave

```
mcp__plugin_jadlis-research_brave-search__brave_web_search({
  query: 'site:pubpeer.com "{first 8 words of paper title}"',
  count: 3
})
```

### Шаг 2: Интерпретация

| Результат | Действие |
|-----------|----------|
| 0 результатов | `pubpeer_flag: false` — нет комментариев |
| ≥1 результат с matching title | `pubpeer_flag: true` + URL → downgrade |
| Результат но title не совпадает | `pubpeer_flag: false` — false positive |

### Шаг 3: Влияние на Evidence Strength

Даже **1 PubPeer-коммент** требует:
1. Отметки в Evidence Table: `PubPeer: YES (URL)`
2. Downgrade evidence strength для claims, опирающихся на эту статью
3. Упоминания в Adversarial Review секции

### Ограничения

- PubPeer индексирует не все журналы
- Отсутствие комментариев ≠ отсутствие проблем
- Некоторые комментарии — методологические дискуссии, не обвинения в fraud
