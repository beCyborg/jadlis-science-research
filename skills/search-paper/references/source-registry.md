# Source Registry

**Версия:** v5.0 (9 search + 2 опц. trust-модуля + 3 enrichment; ядро `search-paper-core`)
**Дата:** 2026-06-10

> Источники оркеструются workflow-ядром `search-paper-core` (Fan-out фаза). Skip по дисциплине и осмысленности делает query-builder (`SEARCH_PLAN.skip`) + JS-фильтр `defaultSources()`. Snowball-фаза добавляет статьи через OpenAlex/S2 `/citations`+`/references` (citation-chasing).

---

## Реестр источников

### Search sources (Fan-out — параллельные агенты)

| Source ID | Prefix | Primary Tool | Fallback | Default Limit | Skip Condition |
|-----------|--------|-------------|----------|---------------|----------------|
| pubmed | `[pm*]` | REST: `eutils.ncbi.nlm.nih.gov` (esearch + efetch) | **Limited: 1 Brave call after retry fails** | 20 | — |
| europe-pmc | `[em*]` | REST: `ebi.ac.uk/europepmc/webservices/rest/search` | **Limited: 1 Brave call after retry fails** | 20 | — |
| s2 | `[s2*]` | REST: `api.semanticscholar.org/graph/v1/paper/search` | **Brave fallback (degraded)** | 20 | — |
| openalex | `[oa*]` | REST: `api.openalex.org/works?search=` | **No Brave fallback (FWCI unavailable)** | 20 | — |
| arxiv | `[ax*]` | REST: `export.arxiv.org/api/query` | **No Brave fallback (retry only)** | 20 | discipline=biomedical AND no "preprint" |
| cochrane-guidelines | `[co*]` | Brave + Goggles: `$site=cochranelibrary.com` + `$site=uptodate.com` + `$site=nice.org.uk` | — (Brave IS primary) | 10 | discipline=cs,physics; GUIDELINES=false |
| web-experts | `[w*]` | Brave + Goggles: `$site=` domains list | — (Brave IS primary) | 10 | — |
| epistemonikos | `[ep*]` | firecrawl scrape: `epistemonikos.org/search` (SR-база) | **Brave `$site=epistemonikos.org`** | 8 | discipline=cs,physics; GUIDELINES=false |
| clinicaltrials | `[ct*]` | REST v2: `clinicaltrials.gov/api/v2/studies` | **No Brave fallback (retry only)** | 20 | discipline=cs,physics |

### Опциональные trust-модули (env-автодетект)

| Module ID | Prefix | Tool | Гейт | Роль |
|-----------|--------|------|------|------|
| scite | `[sc*]` | `api.scite.ai/tallies` (Bearer) | `SCITE_API_KEY` set | supporting/contrasting tally по DOI |
| consensus | `[cn*]` | API / firecrawl scrape `consensus.app` | `CONSENSUS_API_KEY` set | Consensus Meter (yes/possibly/no) |

### Enrichment sources (Phase 4)

| Source ID | Purpose | Primary Tool | Fallback |
|-----------|---------|-------------|----------|
| crossref | DOI verify + retraction check + funder + license | REST: `api.crossref.org/works/{DOI}?mailto=` | **Retry with ?mailto= + 429 backoff** |
| unpaywall | OA PDF URL + OA status | REST: `api.unpaywall.org/v2/{DOI}?email=` | **Retry only** |
| fulltext | Per-paper structured extraction (top-3 OA) | OA-страница (HTML) → `defuddle parse` + Read; **OA/arXiv = PDF-URL → `bash {PLUGIN_ROOT}/scripts/pdf-fetch.sh "<url>"` → Read (0 кр)** | Skip if no OA |

> **PDF-предчек.** OA-фуллтекст или arXiv часто отдаётся прямым PDF-URL — НЕ скрапь через Firecrawl (1 кр/страницу, хук deny-ит): `bash {PLUGIN_ROOT}/scripts/pdf-fetch.sh "<pdf-url>"` → Read. `exit 2` → попробуй другой OA-locus из Unpaywall; если и он закрыт — помечай статью как fulltext-недоступную и работай по абстракту.

### Web-experts Goggles domains

```
examine.com
sciencebasedmedicine.org
statnews.com
astralcodexten.com
scite.ai
consensus.app
science.org/blogs/pipeline
```

---

## API Key Registration

| Service | Registration URL | Env Var |
|---------|-----------------|---------|
| PubMed (NCBI) | https://www.ncbi.nlm.nih.gov/account/settings/ | `PUBMED_API_KEY`, `PUBMED_EMAIL` |
| Semantic Scholar | https://www.semanticscholar.org/product/api | `SEMANTIC_SCHOLAR_API_KEY` |
| OpenAlex | https://openalex.org (freemium dashboard) | `OPENALEX_API_KEY`, `OPENALEX_MAILTO` |
| Crossref | polite pool по `mailto=` в URL, регистрация не нужна | `CROSSREF_MAILTO` |
| Unpaywall | по `email=` в URL, регистрация не нужна | `UNPAYWALL_EMAIL` |
| CORE | https://core.ac.uk/services/api (будущее расширение) | `CORE_API_KEY` |

---

## Минимум для отчёта

Pipeline требует **минимум 2 search sources** с результатами для продолжения синтеза. Если < 2 — ошибка с перечнем недоступных.

---

## Добавление нового источника

1. Создать `protocols/{id}-protocol.md`
2. Добавить строку в таблицу выше
3. Добавить case в SKILL.md Phase 3 agent dispatch
