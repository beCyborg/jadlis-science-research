# Changelog — jadlis-research

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [1.3.0] — 2026-09-06 — TwitterAPI.io в Twitter-канале / TwitterAPI.io in the Twitter channel

### Для человека

- Twitter-канал `full-research` научился брать ответы на тред, профиль автора и тренды детерминированно через TwitterAPI.io, а не «если Grok сам решит».
- Когда у Grok кончился недельный пул, канал больше не выпадает: при наличии ключа он идёт keyword-only по TwitterAPI.io и честно помечает, что семантики нет.
- Ключ `TWITTERAPI_IO_KEY` опциональный: без него всё работает как раньше.

### For agents

- Added: `scripts/twitterapi.sh` — REST-обёртка над api.twitterapi.io (`search`, `replies`, `quotes`, `user`, `last`, `tweets`, `trends`, `balance`); ключ через `secret.sh`, `exit 2` без ключа; `User-Agent` обязателен (Cloudflare). REST вместо vendor-MCP: MCP отдаёт пустые `get_trends`, отвергает `queryType=Top` у replies и плющит объекты твитов (проверено 06.09.2026).
- Changed: `skills/full-research/protocols/twitter-protocol.md` — секция «Degradation slot (off by default)» заменена на «TwitterAPI.io layer»: Mode A (GROK_OK, ≤3 вызова: replies/user/trends после разбора Grok) и Mode B (GROK_DOWN, keyword-only ≤4 вызова, sourceQuality ≤ MEDIUM); `x_thread_fetch` при наличии ключа не запрашивается; бюджет «2 Grok + ≤3 REST».
- Changed: `skills/full-research/SKILL.md` — гейт `GROK_DOWN` роняет только `grokweb`; `twitter` остаётся при резолве ключа (`twitterapi.sh balance`).
- Changed: `skills/keys/SKILL.md` — `TWITTERAPI_IO_KEY` в опциональных ключах класса B; `README.md` / `README.en.md` — строка ключа и деградация канала.
- Changed: `.claude-plugin/plugin.json` — `version` 1.3.0.
- Migration: none — без ключа поведение прежнее.

## [1.2.0] — 2026-09-06 — ключи переехали в Связку ключей / keys move to the macOS Keychain

### Для человека

- Ключи больше не лежат открытым текстом в `settings.json`: всё живёт в Связке ключей macOS, а скрипты и протоколы читают их одной точкой.
- Скилл `/jadlis-research:keys` теперь показывает, какой ключ откуда взялся, принимает недостающие по одному и предлагает перенести старые значения из файла в Связку.
- Brave, Firecrawl и Exa наконец описаны там же, где научные ключи, — искать по двум местам не надо.

### For agents

- Added: `scripts/secret.sh` — единая точка разрешения ключа. Порядок: env → Keychain generic `jadlis-research`/`KEY` → `pluginSecrets` блоба `Claude Code-credentials` (и `Claude Code-credentials-*`) → `<config-dir>/.credentials.json` → `<config-dir>/settings.json → env`. Режимы `KEY`, `--export K1 K2 …` (для `eval`), `--which KEY`, `--set KEY` (значение со stdin), `--list`.
- Changed: `scripts/websearch.py` — `brave_key()` / `exa_key()` дополнены тихим фолбэком на `secret.sh` (env → `~/.config/exa/key` → Keychain).
- Changed: `scripts/yandex-search.sh`, `scripts/places-fetch.sh`, `scripts/feed-fetch.py`, `skills/search/scripts/selftest.sh` — фолбэк на `secret.sh`, когда переменная окружения пуста.
- Changed: Bash-блоки с `curl` в `skills/search-paper/SKILL.md`, `skills/search-paper/protocols/{pubmed,openalex,s2,adversarial-review}-protocol.md` открываются прелюдом `eval "$(bash "…/scripts/secret.sh" --export …)"` (14 блоков).
- Changed: `skills/full-research/protocols/web-protocol.md` — слоты Tavily и Serper резолвят ключ тем же прелюдом; `skills/full-research/SKILL.md`, `skills/search/SKILL.md`, `skills/search/references/exa-api.md` — формулировки про хранение ключей приведены к стандарту.
- Changed: `skills/keys/SKILL.md` переписан под два класса ключей: класс A (`BRAVE_API_KEY`, `FIRECRAWL_API_KEY`, `REDDITAPIS_KEY`, `YOUTUBE_API_KEY`) вводится через `/plugin configure jadlis-research@jadlis` и проверяется `secret.sh --which`; класс B принимается по одному и пишется `secret.sh --set` через stdin; добавлен шаг переноса legacy-значений из `settings.json → env` с подтверждением.
- Changed: `.claude-plugin/plugin.json` — `version` 1.2.0, описания `BRAVE_API_KEY` / `FIRECRAWL_API_KEY` называют `/plugin configure` как путь смены ключа.
- Added: `README.md` + `README.en.md` плагина по стандарту пяти секций; доки тира 2 — `docs/2-verif/`.
- Migration: ничего вручную переносить не нужно — `secret.sh` последней ступенью всё ещё читает `settings.json → env`. Свернуть legacy-рельсу предлагает шаг 5 скилла `keys`.

## [1.1.0] — 2026-09-06 — доказательность, протоколы одним проходом, языковые слои / evidence gate, one-pass protocols, language layers

### Для человека

- Цитата без сохранённого куска страницы больше не может считаться подтверждённой — потолок надёжности снижается автоматически.
- Появились языковые слои: японский, китайский, корейский и европейские площадки читаются на своём языке, а не через английский пересказ.
- Ресерч стал брать полный текст страниц дешевле: сначала бесплатные способы, Firecrawl — последним.

### For agents

- Added: снапшот-гейт schema v4 в `workflows/full-research-core.js` — пер-цитатный потолок relevance (`no-snapshot`, `llm-mediated` для codexweb/grokweb/yandex и хостов x.com/twitter.com, `short-snapshot` < 1 000 символов, `quote-not-found`). Повышений нет; escape — `args.channelCeiling`. В результате прогона `snapshotGate` (`byReason`, `byChannel`, `ceilingCapped`), в `channelStatus` — `snapshotDemotedBy`, `ceiling`, `snapshotBytesMedian`; в evidence — `snapshotChars`, `snapshotExtractor`.
- Added: языковой слот `args.languages[]` / `args.queries{}`, определение языка запроса ru/en/ja/zh/ko, справочник `skills/full-research/references/language-layers.md`.
- Added: каналы `ja` / `zh` / `ko` / `eu` (trigger-scoped, в дефолт не входят) с протоколами и общим фетчером `scripts/feed-fetch.py` (Qiita API v2, Hatena search RSS, Zenn, note.com, V2EX, Velog, tistory, DOU, Golem, heise, Xataka, Menéame, Stack Exchange API v2.3 keyless, Mastodon tag timelines) — снапшоты с `Extractor: feed-fetch`.
- Added: лестница извлечения снапшотов в `skills/full-research/protocols/web-protocol.md` Layer 3 — PDF → `pdf-fetch.sh`; HTML → `defuddle parse --md`; CSR → `r.jina.ai` (локальная альтернатива Crawl4AI 0.9.3); URL-точный индекс → `websearch.py contents --full`; Tavily только при `TAVILY_API_KEY`; Firecrawl последним и никогда для PDF и x.com.
- Added: гейты доказательности в `protocols/reddit-protocol.md` и `protocols/hackernews-protocol.md` по вердикту слепого A/B 2026-09-06 — запрет цитат «только заголовок», свип по вовлечённости и событиям, per-quote провенанс, формат контраргумента.
- Added: слоты без включения — Serper (`SERPER_API_KEY`) и DataForSEO в web-протоколе, TwitterAPI.io (`TWITTERAPI_IO_KEY`, только при `GROK_DOWN`) в twitter-протоколе.
- Added: `hooks/block-pdf-firecrawl.py` дополнительно deny-ит Firecrawl по x.com/twitter.com.
- Changed: intake `full-research` переехал в plan mode (`EnterPlanMode` → бриф → `ExitPlanMode` = гейт запуска).
- Changed: Codex → `gpt-6-astra` в канале codexweb и в эскалации третьего голоса; везде явный `service_tier="default"` и `model_reasoning_effort="high"`. Откат — `args.codexModel: "gpt-5.6-sol"`.
- Changed: язык рабочего контура — английский (промпты ядра, схемы, девять из десяти протоколов, SKILL.md, агенты). Русскими остаются `report.md`, вопросы пользователю, `queryRu`, RU-примеры в Yandex/Telegram-протоколах, `quotes[]` в языке оригинала и `reddit-protocol.md` целиком.
- Changed: `scripts/urlhealth.py` — x.com и twitter.com убраны из `KNOWN_BLOCKED`, добавлены поля `snapshotChars` и `snapshotExtractor`.
- Changed: `scripts/reddit-archive.py` — ступень PullPush заменена на `www.reddit.com/search.rss` с браузерным User-Agent (PullPush отдаёт 429 с любого IP с 2026-08-26).
- Changed: `scripts/pdf-fetch.sh` — гард Chrome-заглушек, TTL кэша (`PDF_FETCH_TTL_DAYS`, дефолт 30), выход из лок-цикла без блокировки.
- Changed: `skills/search/SKILL.md` — примеры `contents` с `--full` (дефолт режет страницу до 8 000 символов).
- Breaking: `ledgerSchemaVersion` поднят до 4 — тренды confirmed не смешиваются с v3.

## [1.0.0] — 2026-09-01 — первый релиз ресерч-стека / first research-stack release

### Для человека

- Один плагин вместо россыпи скиллов: обычный поиск, полный ресерч по сообществам, научный обзор и тройная проверка плана.
- Отчёты сразу ложатся в vault, а не остаются в чате.

### For agents

- Added: скиллы `skills/search`, `skills/full-research`, `skills/search-paper`, `skills/verif`, `skills/keys`.
- Added: workflows `workflows/full-research-core.js` и `workflows/search-paper-core.js`, агенты `agents/researcher-opus-xhigh.md` и `agents/orchestrator-fable-xhigh.md`.
- Added: ledger schema v3 — evidence-префиксы куратора, шаг `urlhealth`, линза W2, эскалация в Codex, статус DISPUTED.
- Added: пять MCP-серверов в `.mcp.json` (brave-search, firecrawl, reddit, reddit-alt, youtube).
