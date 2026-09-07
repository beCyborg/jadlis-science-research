[Русский](README.md) · English

# science-research — Claude Code plugin

Command: `/science-research`.

## Было → стало

To be written (README contract 2026-09, phase 3).

## Как это работает

PubMed, Europe PMC, Semantic Scholar, OpenAlex, arXiv, Cochrane; снежный ком по цитированиям, проверка отзыва статьи, GRADE-синтез → заметка в vault. Требует плагин search (ключи Brave и Firecrawl).

## Установка и первый запуск

```bash
claude plugin marketplace add https://github.com/beCyborg/jadlis-start.git
claude plugin install search@jadlis --config BRAVE_API_KEY=… --config FIRECRAWL_API_KEY=…
claude plugin install science-research@jadlis
```

## Границы, стоимость, обновление

```bash
claude plugin marketplace update jadlis
claude plugin update science-research@jadlis
claude plugin list
```
