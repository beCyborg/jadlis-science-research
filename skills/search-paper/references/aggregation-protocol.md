# Протокол агрегации результатов

**Версия:** v3.0 (GRADE-based, adapted from search-paper v2.2.0)
**Дата:** 2026-04-20

---

## 1. Work Directory

```
WORK_DIR = .search-paper/{SESSION_ID}_{QUERY_SLUG}
```

- `SESSION_ID` = `$(date +%s%N)` (наносекунды, избегает parallel collision)
- `QUERY_SLUG` = lowercase ASCII, spaces→hyphens, max 40 chars. Non-ASCII → first 8 chars of SESSION_ID.

### Файлы

| Файл | Путь | Описание |
|------|------|----------|
| Per-source results | `{WORK_DIR}/{source_id}.md` | Результаты от каждого search агента |
| Crossref enrichment | `{WORK_DIR}/enrichment_crossref.md` | DOI verify + retraction + funder |
| Unpaywall enrichment | `{WORK_DIR}/enrichment_unpaywall.md` | OA PDF + status |
| Fulltext summary | `{WORK_DIR}/fulltext_{doi_slug}.md` | Per-paper extraction (≤ 2K tokens) |
| Final report | `{VAULT_RESEARCH_DIR}/{QUERY_RU}.md` | Vault-canonical отчёт |

---

## 2. DOI Normalization

Перед дедупликацией:

```
1. trim whitespace
2. remove "https://doi.org/" prefix
3. remove "http://dx.doi.org/" prefix
4. remove "doi:" prefix
5. lowercase
```

---

## 3. Deduplication Rules

### Приоритет методов

```
1. DOI exact match (primary, case-insensitive после нормализации)
   ↓
2. Fuzzy title match: Jaccard similarity ≥ 0.85 (secondary)
   ↓
3. Authors + Year fallback: ≥2 авторов совпадают + year + title Jaccard ≥ 0.5
   ↓
4. Считать разными статьями
```

### Merge priority

```
DOI source → PubMed → S2 → Europe PMC → OpenAlex → arXiv
```

Для каждого поля берётся значение из наиболее приоритетного source, где оно не null.
Поле `sources[]` содержит ВСЕ источники, где статья найдена.

### Enrichment fields merge

| Поле | Источник | Правило |
|------|----------|---------|
| `license` | Crossref > Unpaywall | Не перезаписывать существующее |
| `oa_pdf_url` | Unpaywall | Если не null → записать |
| `oa_status` | Unpaywall | gold/hybrid/bronze/green/closed |
| `is_retracted` | Crossref (`update-to.type == "retraction"`) | Boolean |
| `funder` | Crossref (`funder` field) | Industry funding flag |
| `pubpeer_flag` | Phase 6 PubPeer check | Boolean |

---

## 4. GRADE-Based Ranking (замена quality_score)

### Принцип

Study type = **контейнер для выбора assessment framework**, НЕ automatic rank:
- Meta-analysis / Systematic Review → AMSTAR 2
- RCT → Cochrane RoB 2.0 / ROBUST-RCT
- Cohort / Case-control → Newcastle-Ottawa Scale

### GRADE per-outcome assessment

Для каждого **outcome** (НЕ для каждой статьи):

**Starting quality:**
- RCT → HIGH
- Observational → LOW

**5 downgrade factors:**
1. Risk of bias (RoB 2.0 / NOS domain scores)
2. Inconsistency (I² heterogeneity, direction of effects)
3. Indirectness (PICO mismatch)
4. Imprecision (wide CI, small N)
5. Publication bias (funnel asymmetry, Egger's p < 0.10)

**3 upgrade factors (observational only):**
1. Large effect (RR > 2 or < 0.5)
2. Dose-response gradient
3. All plausible confounders would reduce effect

**Final:** HIGH / MODERATE / LOW / VERY LOW per outcome.

### Evidence Strength (per recommendation)

| Level | Criteria |
|-------|---------|
| STRONG | ≥2 HIGH/MODERATE quality outcomes из 2+ independent sources |
| MODERATE | 1 HIGH или ≥2 MODERATE outcomes |
| WEAK | Only LOW quality outcomes, или insufficient data |
| UNVERIFIED | No GRADE assessment possible (insufficient study info) |

### Circular reporting check

Если ≥2 статьи цитируют один оригинал как единственный primary source → считаем как 1 independent source.

---

## 5. Legacy Quality Score (fallback для non-biomedical)

Сохранён для `--sort quality` в non-GRADE contexts:

```
quality_score = round(
  fwci_or_citation_norm × 0.30 +
  influential_ratio × 0.20 +
  recency × 0.15 +
  weighted_source_count_norm × 0.20 +
  study_type_bonus × 0.15
) × 5
```

Диапазон: [1, 5]. Null-handling: см. v1.4 aggregation-protocol.

---

## 6. Collision Handling (vault drop)

```bash
test -e "{REPORT_PATH}" && echo EXISTS || echo FREE
```

- FREE → Write в `{REPORT_PATH}`
- EXISTS → `{QUERY_RU} ({DATE}).md` → test → если EXISTS → `v2`, `v3`, ...

Последняя строка ответа synthesis agent: `REPORT_PATH=<итоговый путь>`.
