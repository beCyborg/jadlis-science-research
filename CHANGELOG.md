# Changelog — jadlis-research

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [1.1.0] — 2026-09-06

План 2 «доказательность → протоколы одним проходом → языки» (транши 0–3).

### Added
- **Снапшот-гейт schema v4** в `full-research-core`: пер-цитатный потолок relevance —
  `no-snapshot`, `llm-mediated` (codexweb/grokweb/yandex и хосты x.com/twitter.com по константе),
  `short-snapshot` (< 1 000 символов), `quote-not-found`. Повышений нет; явный escape —
  `args.channelCeiling: {codexweb: "HIGH"}`. В результате прогона — `snapshotGate`
  (`byReason`, `byChannel`, `ceilingCapped`), в `channelStatus` — `snapshotDemotedBy`,
  `ceiling`, `snapshotBytesMedian`; в evidence — `snapshotChars`, `snapshotExtractor`.
- **Языковой слот**: `args.languages[]` и `args.queries{}`; определение языка запроса
  ru/en/ja/zh/ko (кандзи-только запросы различаются по маркерам синдзитай vs упрощённых).
  Правило «площадку ищем на её языке» + справочник `references/language-layers.md`.
- **Языковые слои каналов** `ja` / `zh` / `ko` / `eu` (trigger-scoped, в дефолт не входят)
  с протоколами и общим фетчером `scripts/feed-fetch.py` (Qiita API v2, Hatena search RSS,
  Zenn, note.com, V2EX, Velog, tistory, DOU, Golem, heise, Xataka, Menéame,
  Stack Exchange API v2.3 keyless, Mastodon tag timelines) — снапшоты с `Extractor: feed-fetch`.
- **Лестница извлечения снапшотов** в `web-protocol.md` Layer 3: PDF → `pdf-fetch.sh`;
  HTML → `defuddle parse --md`; CSR → `r.jina.ai` (локальная альтернатива — Crawl4AI 0.9.3);
  URL-точный индекс → `websearch.py contents --full`; Tavily — только при `TAVILY_API_KEY`
  (keyless-режима у Tavily нет); Firecrawl — последним и никогда для PDF и x.com.
- **Гейты доказательности** в протоколах reddit и hackernews по вердикту слепого A/B
  2026-09-06: запрет цитат «только заголовок», свип по вовлечённости и событиям,
  per-quote провенанс, формат контраргумента «кто + почему + голоса + ссылка».
- **Слоты без включения**: Serper (при `SERPER_API_KEY`) и DataForSEO в web-протоколе,
  TwitterAPI.io (при `TWITTERAPI_IO_KEY`, только при `GROK_DOWN`) в twitter-протоколе.
- Хук `block-pdf-firecrawl.py` дополнительно deny-ит Firecrawl по x.com/twitter.com.
- Intake `full-research` переехал в plan mode (`EnterPlanMode` → бриф → `ExitPlanMode` = гейт запуска).

### Changed
- **Codex → `gpt-6-astra`** в канале codexweb и в эскалации третьего голоса; везде явный
  `service_tier="default"` (priority ≈2,5× расхода квоты) и `model_reasoning_effort="high"`.
  Откат — `args.codexModel: "gpt-5.6-sol"` и литералы протокола.
- **Язык рабочего контура — английский**: промпты ядра, схемы, девять из десяти протоколов,
  SKILL.md, агенты. Русскими остаются отчёт `report.md`, вопросы пользователю, `queryRu`,
  RU-примеры запросов в Yandex/Telegram-протоколах, `quotes[]` в языке оригинала и
  `reddit-protocol.md` целиком (вердикт A/B: RU-форма даёт больше цитат и контраргументов).
- `urlhealth.py`: x.com и twitter.com убраны из `KNOWN_BLOCKED` (теперь измеряются),
  добавлены поля `snapshotChars` и `snapshotExtractor`.
- Reddit: ступень PullPush заменена на `www.reddit.com/search.rss` с браузерным User-Agent
  (`reddit-archive.py search`, PullPush отдаёт 429 с любого IP с 2026-08-26).
- `pdf-fetch.sh`: гард Chrome-заглушек (404/challenge/login больше не кэшируются как PDF),
  TTL кэша (`PDF_FETCH_TTL_DAYS`, дефолт 30), выход из лок-цикла без блокировки.
- `/search`: примеры `contents` — с `--full` (дефолт режет страницу до 8 000 символов).

### Fixed
- `ledgerSchemaVersion` поднят до 4 — тренды confirmed не смешиваются с v3.

## [1.0.0] — 2026-09-01

Первый релиз: скиллы `search`, `full-research`, `search-paper`, `verif`, `keys`;
ledger schema v3 (evidence-префиксы куратора, urlhealth, линза W2, эскалация в Codex, DISPUTED).
