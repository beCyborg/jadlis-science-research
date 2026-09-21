# Source Registry

**Версия:** v5.3 (10 search + 3 enrichment; ядро `search-paper-core`)
**Дата:** 2026-09-21

> Источники оркеструются workflow-ядром `search-paper-core` (Fan-out фаза). Skip по дисциплине и осмысленности делает query-builder (`SEARCH_PLAN.skip`) + JS-фильтр `defaultSources()`. Snowball-фаза добавляет статьи через OpenAlex/S2 `/citations`+`/references` (citation-chasing).

---

## Реестр источников

### Search sources (Fan-out — параллельные агенты)

| Source ID | Prefix | Primary Tool | Fallback | Limit | Skip Condition |
|-----------|--------|-------------|----------|---------------|----------------|
| pubmed | `[pm*]` | REST: `eutils.ncbi.nlm.nih.gov` (esearch + efetch) | **Limited: 1 Brave call after retry fails** | {LIMIT} = 40 | — |
| europe-pmc | `[em*]` | REST: `ebi.ac.uk/europepmc/webservices/rest/search` | **Limited: 1 Brave call after retry fails** | {LIMIT} = 40 | — |
| s2 | `[s2*]` | REST: `api.semanticscholar.org/graph/v1/paper/search` | **Brave fallback (degraded)** | {LIMIT} = 40 | — |
| openalex | `[oa*]` | REST: `api.openalex.org/works?search=` | **No Brave fallback (FWCI unavailable)** | {LIMIT} = 40 | — |
| arxiv | `[ax*]` | REST: `export.arxiv.org/api/query` | **No Brave fallback (retry only)** | {LIMIT} = 40 | discipline=biomedical AND no "preprint" |
| cochrane-guidelines | `[co*]` | Brave + Goggles: `$site=cochranelibrary.com` + `$site=uptodate.com` + `$site=nice.org.uk` | — (Brave IS primary) | своё `count` протокола | discipline=cs,physics; GUIDELINES=false |
| web-experts | `[w*]` | Brave + Goggles: `$site=` domains list | — (Brave IS primary) | своё `count` протокола | — |
| epistemonikos | `[ep*]` | firecrawl scrape: `epistemonikos.org/search` (SR-база) | **Brave `$site=epistemonikos.org`** | своё `count` протокола | discipline=cs,physics; GUIDELINES=false |
| clinicaltrials | `[ct*]` | REST v2: `clinicaltrials.gov/api/v2/studies` | **No Brave fallback (retry only)** | {LIMIT} = 40 | discipline=cs,physics |
| core | `[cr*]` | REST v3: `api.core.ac.uk/v3/search/works/` (слэш на конце обязателен, `curl -sL`) | **No Brave fallback (retry only)** | {LIMIT} = 40 | — (включён для всех дисциплин) |

> **Колонка Limit.** Число задаёт ядро в промпте агента (`PER_SOURCE_TOP`, дефолт **40** с 2.2.0,
> переопределяется аргументом `perSourceTop`) — дефолты протоколов игнорируются. Brave-каналы
> (Cochrane, web-experts, Epistemonikos) берут столько, сколько прописано в их собственном протоколе.
> Источникам pubmed / europepmc / openalex ядро передаёт основной запрос **и короткие запросы по
> подтемам**; все они исполняются одним вызовом `source-fetch.py --queries-file`, бюджет на запрос —
> `max(8, LIMIT / число запросов)`.

> **CORE — серая литература, а не ещё одна журнальная база.** Диссертации, отчёты, рабочие бумаги,
> репозиторные OA-копии: то, чего нет в PubMed/S2/OpenAlex, и антидот publication bias.
> Префикс `cr`, потому что `co` занят Cochrane. Две ловушки: (1) без слэша на конце — 301 и
> HTML редиректа вместо JSON; (2) в ответе поиска приходит поле `fullText` на 80–180 тыс. символов
> на запись — вырезать через `jq 'del(.results[].fullText)'` ДО чтения, иначе контекст агента
> затапливает. `doi` бывает `null` (репозиторные работы), `downloadUrl` — прямая ссылка на PDF.
> Тот же поиск по DOI (`q=doi:"{DOI}"`) — запасной OA-локус для fulltext-фазы.

### Препринты

Отдельного источника под bioRxiv/medRxiv нет: их API отдаёт только выгрузку по диапазону дат, поиска по
ключевым словам у него нет. Канал препринтов в биомедицине — второй подзапрос Europe PMC с `SRC:PPR`
(до 10 записей **сверх** LIMIT, отдельная секция дампа, `qualitySignals: preprint`).
CS/physics-препринты приходят через arXiv, как и раньше.

### Enrichment sources (Phase 4)

| Source ID | Purpose | Primary Tool | Fallback |
|-----------|---------|-------------|----------|
| crossref | DOI verify + retraction check (4 сигнала) + anti-hallucination (title/year/author) + funder + license | REST: `api.crossref.org/works/{DOI}?mailto=` + list-запрос `works?filter=updates:{DOI},update-type:retraction` для топ-тира | **Retry with ?mailto= + 429 backoff** |
| opencitations | Третья ступень citation-chasing, когда отказали и OpenAlex, и S2 | REST v2 без ключа: `api.opencitations.net/index/v2/{citations,references}/doi:{DOI}` | **Метаданных не даёт — гидрация DOI пакетом через Crossref/OpenAlex** |
| unpaywall | OA PDF URL + OA status | REST: `api.unpaywall.org/v2/{DOI}?email=` | **Retry only** |
| fulltext | Per-paper structured extraction (top-3 OA) | OA-страница (HTML) → `defuddle parse` + Read; **OA/arXiv = PDF-URL → `bash {PLUGIN_ROOT}/scripts/pdf-fetch.sh "<url>"` → Read (0 кр)** | Skip if no OA |

> **PDF-предчек.** OA-фуллтекст или arXiv часто отдаётся прямым PDF-URL — НЕ скрапь через Firecrawl (1 кр/страницу, хук deny-ит): `bash {PLUGIN_ROOT}/scripts/pdf-fetch.sh "<pdf-url>"` → Read. `exit 2` → попробуй другой OA-locus из Unpaywall; если и он закрыт — помечай статью как fulltext-недоступную и работай по абстракту.

### Web-experts Goggles domains

```
examine.com
sciencebasedmedicine.org
statnews.com
astralcodexten.com
science.org/blogs/pipeline
```

---

## API Key Registration

| Service | Registration URL | Env Var |
|---------|-----------------|---------|
| PubMed (NCBI) | https://www.ncbi.nlm.nih.gov/account/settings/ | `PUBMED_API_KEY`, `PUBMED_EMAIL` |
| Semantic Scholar | https://www.semanticscholar.org/product/api | `SEMANTIC_SCHOLAR_API_KEY` |
| OpenAlex | https://openalex.org (freemium dashboard) | `OPENALEX_API_KEY` (обязателен: `&api_key=`; `OPENALEX_MAILTO` — только контакт, на лимиты не влияет) |
| Crossref | polite pool по `mailto=` в URL, регистрация не нужна | `CROSSREF_MAILTO` |
| Unpaywall | по `email=` в URL, регистрация не нужна | `UNPAYWALL_EMAIL` |
| CORE | https://core.ac.uk/services/api (ключ обязателен: `Authorization: Bearer`) | `CORE_API_KEY` |
| OpenCitations | ключ не нужен, регистрация не нужна | — |

---

## Минимум для отчёта

Pipeline требует **минимум 2 search sources** с результатами для продолжения синтеза. Если < 2 — ошибка с перечнем недоступных.

---

## Добавление нового источника

1. Создать `protocols/{id}-protocol.md` (структура — как у соседей).
2. Добавить строку в таблицу выше.
3. Прописать источник в `workflows/search-paper-core.js`: `ALL_SOURCES` (уникальный `prefix`!),
   массив `base` в `defaultSources()` + условие skip по дисциплине, `SEARCH_PLAN.queries`
   (свойство **и** `required[]`), подсказка по синтаксису запроса в `queryPrompt()`.
4. Обновить счётчики источников: `meta.phases` Fan-out, шапка этого файла, SKILL.md, README.
5. `uv run --with pytest pytest tests/ -q` — `tests/test_sp_sources_registry.py` проверяет
   наличие файла протокола, уникальность префиксов и полноту `SEARCH_PLAN.queries`.
