---
name: search-paper
description: >
  Научный ресерч: мульти-источниковый поиск (PubMed, Europe PMC, Semantic Scholar,
  OpenAlex, arXiv, Cochrane, web-experts, Epistemonikos, ClinicalTrials),
  citation snowballing, обогащение (Crossref retraction-check, Unpaywall, fulltext),
  GRADE per-outcome synthesis, adversarial review → Obsidian vault (Знания/Ресерчи/).
  TRIGGER when: user says "научный ресерч", "найди статьи", "что говорит наука",
  "мета-анализ", "systematic review", "evidence-based", "клинические исследования",
  "доказательная медицина", "search papers", "research papers", "literature review",
  "scientific evidence", "PubMed search".
  DO NOT TRIGGER when: general web search (use /jadlis-research:search), community opinions
  or full web+community research (use /jadlis-research:full-research), library docs (use Context7).
allowed-tools:
  - Read
  - Write
  - Glob
  - Bash
  - AskUserQuestion
  - Workflow
  - mcp__brave-search__brave_web_search
  - mcp__firecrawl__firecrawl_scrape
argument-hint: "<query — научный вопрос на русском или английском>"
model: claude-opus-5
effort: xhigh
---

# /jadlis-research:search-paper — научный литературный обзор (гибрид Skill + Workflow)

Тяжёлая часть (query-builder → fan-out по 9 источникам → citation snowballing →
Crossref/Unpaywall enrich с retraction- и anti-hallucination-проверкой → GRADE-синтез →
adversarial critic → fix) исполняется детерминированным workflow **`search-paper-core`**.
Скилл делает интерактивный intake (Phase A: recon + decision-first интервью + опц.
персонализация) и запись в vault (Phase C: vault-контракт).

**Запрос пользователя:** `$ARGUMENTS`

## Архитектура

```
Phase A (INTAKE: S2 recon + decision-first интервью + опц. персонализация)
  → Phase B (Workflow search-paper-core)
  → Phase C (WRITE: vault-контракт + резюме под решение)
```

Режим всегда глубокий (systematic): snowballing + per-claim верификация + retraction-check
всех цитат. Глубину ограничивают saturation/PAPER_CAP/budget-гейты внутри ядра, не режим.

## Константы

```
PLUGIN_ROOT        = ${CLAUDE_PLUGIN_ROOT}
VAULT_PATH         = ${user_config.VAULT_PATH}
VAULT_RESEARCH_DIR = {VAULT_PATH}/Знания/Ресерчи
SKILL_DIR          = {PLUGIN_ROOT}/skills/search-paper
DATE               = !`date +%Y-%m-%d`   (значение уже подставлено при загрузке скилла)
```

## Phase A — INTAKE (главная сессия)

1. **Тема.** Если `$ARGUMENTS` пуст — AskUserQuestion «Какой научный вопрос исследуем?» и остановись.

2. **Recon = научный probe (S2 REST, НЕ Brave).** 1 вызов через Bash curl — наполнить
   варианты интервью реальными числами (сколько мета/RCT/observational, какая дисциплина):
   ```bash
   Q=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$ARGUMENTS")
   curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=${Q}&limit=15&fields=title,year,citationCount,publicationTypes,fieldsOfStudy" \
     -H "x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}" 2>/dev/null || echo "S2_UNAVAILABLE"
   ```
   S2 недоступен → фоллбэк Europe PMC REST (`ebi.ac.uk/europepmc/webservices/rest/search?query=...&format=json`);
   иначе recon пропусти (интервью и без чисел работает). Из ответа оцени `recon`: discipline,
   counts по типам, период.

3. **MESSE-lite + фрейминг.** `discipline ∈ {biomedical, cs, physics, social, general}`.
   Фрейминг **PICO** (явная интервенция) vs **PECO** (питание/экспозиция — дефолт для
   health/nutrition). Это гипотезы — финально решает query-builder в ядре.

4. **Decision-first интервью (ВСЕГДА, скипа нет).** AskUserQuestion, 3 вопроса. Узость запроса
   → варианты pre-selected, но вопрос о решении несжимаем:
   - **Q1 «Какое решение ты примешь по итогам?»** (header: «Решение») — варианты-гипотезы из recon:
     начать ресёрч под конкретное действие · скорректировать тему · проверить конкретный claim ·
     понять поле. → `decisionContext` (1-2 предложения).
   - **Q2 «Какая популяция в фокусе?»** (header: «Популяция») — здоровые взрослые · клиническая
     (с диагнозом) · human-приоритет (доклинику только как поддержку) · включить доклинику
     (mouse/in-vitro). → `populationLayer` + indirectness-слой для синтеза.
   - **Q3 «Охват» (multiSelect)** (header: «Охват») — свежее 5 лет · вся история · + клинические
     гайдлайны (Cochrane/NICE/WHO) · отчёт на EN. → `timeHorizon`, `guidelines`, `lang`.

   Comparison и Outcome НЕ спрашиваем — их выводит ядро из статей.

5. **Опц. персонализация (Q4).** Отдельным AskUserQuestion: «Персонализировать вывод под твой
   профиль здоровья?» (да/нет). Vault читается **ТОЛЬКО при "да"**, точечно, и **только главной
   сессией** (не субагентами — изоляция приватных данных):
   - Найди в vault заметки о здоровье: `Glob` по `{VAULT_PATH}/Потребности/**/*доров*/**/*.md`.
     Ничего не нашлось — скажи об этом и продолжай с `personalize=false`.
   - Из найденного бери: TL;DR-callout медкарты (`> [!abstract]`, первые ~40 строк),
     активные находки (frontmatter `status: active` → title + severity), метрики
     (frontmatter `last_value` + `status`). Сырьё лабораторных анализов НЕ бери.
   Собери компактный `profileContext` (≤30 строк: ключевые маркеры + активные находки +
   противопоказания-флаги). На "нет" — `personalize=false`, `profileContext=null`, vault не трогаем.

   > `profileContext` — единственный слот, куда попадают приватные медданные, и он не
   > выходит за пределы этого прогона: в отчёт пишутся выводы, а не сам профиль.

6. **Сборка `args` + подготовка.** Вычисли `SESSION_ID = ${CLAUDE_SESSION_ID}`;
   `QUERY_SLUG` (транслит латиницей, ≤40, lowercase, дефисы); `QUERY_RU` (краткая русская
   формулировка ≤25 симв); `WORK_DIR = .search-paper/{SESSION_ID}_{QUERY_SLUG}`.
   `mkdir -p "{WORK_DIR}" "{VAULT_RESEARCH_DIR}"`.
   **Env-детект модулей:** `modules = { scite: SCITE_API_KEY непуст, consensus: CONSENSUS_API_KEY непуст }`
   (через Bash `[ -n "${SCITE_API_KEY:-}" ]`). Сообщи: «Запущен научный ресёрч (always-deep) по N
   источникам. Ожидаю результаты…»

## Phase B — INVOKE

```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/search-paper-core.js",
  args: {
    pluginRoot: PLUGIN_ROOT,            // ${CLAUDE_PLUGIN_ROOT} в JS НЕ подставляется — передаём значением
    vaultPath: VAULT_PATH,
    refinedQueryRu: QUERY_RU_FULL,      // полная русская формулировка
    refinedQueryEn: REFINED_QUERY_EN,   // EN-перевод (критично для PubMed/S2/arXiv)
    framing: "PICO" | "PECO",
    discipline: "biomedical" | "cs" | "physics" | "social" | "general",
    decisionContext: DECISION_CONTEXT,
    populationLayer: POPULATION_LAYER,
    timeHorizon: TIME_HORIZON,
    guidelines: true | false,
    lang: "ru" | "en",
    personalize: true | false,
    profileContext: PROFILE_CONTEXT | null,   // только если personalize
    recon: RECON_SUMMARY,
    modules: { scite: bool, consensus: bool },
    aiModel: "<ID модели текущей сессии, напр. claude-opus-5>",
    date: DATE,
    workDir: WORK_DIR
  }
})
```

Ядро само читает протоколы источников, строит per-source запросы, делает snowballing,
retraction-check всех DOI (Crossref `update-to`), anti-hallucination (`titleMatch`), GRADE
per-outcome синтез, adversarial review и применяет правки. Дождись `<task-notification>`,
затем используй объект: `{workDir, status, sourcesAnswered, papersTotal, addedBySnowball,
reportPath, queryRu, relatedCandidates, retractedExcluded, enrich, synthMeta}`. Прогресс — в `/workflows`.

## Phase C — WRITE (vault-контракт, главная сессия)

Контракт: `${CLAUDE_PLUGIN_ROOT}/shared/obsidian-write-contract.md` (не менять). Шаги:

1. **Частичный результат.** `status: "insufficient-sources"` (<2 источников) → сообщи об ошибке,
   покажи `{WORK_DIR}`, в vault НЕ пиши. Иначе продолжай.

2. **Прочитай draft:** `{WORK_DIR}/report.md`.

3. **Pre-write dedup (obsidian).** Через Bash (если Obsidian открыт; иначе CLI-шаги пропусти):
   ```bash
   obsidian search query="{ключевые слова QUERY_RU}" path="Знания/Ресерчи" limit=5 format=json 2>/dev/null || echo "CLI_UNAVAILABLE"
   obsidian search query="{ключевое слово}" limit=10 format=json 2>/dev/null || echo "CLI_UNAVAILABLE"
   ```
   Очень близкий дубликат → supersede (frontmatter `supersedes:` + `> [!info] Обновляет [[…]]`).

4. **Коллизия имён.** `REPORT_PATH = {VAULT_RESEARCH_DIR}/{queryRu}.md`. `test -e` → EXISTS →
   `{queryRu} ({DATE}).md` → снова test → ` v2`, ` v3`… до свободного.

5. **Wikilinks + запись.** В разделе `## Связанные заметки` (он пуст-заглушка) проставь wikilinks
   `[[Название]]` **ТОЛЬКО** на заметки, реально найденные на шаге 3 (`relatedCandidates` — лишь
   подсказки для поиска; НЕ создавай unresolved links). CLI недоступен → убери раздел. Запиши
   финальный файл в `REPORT_PATH` (Write — draft с заполненным разделом; `verified: false` сохрани).

6. **Post-write (daily note).** Если Obsidian открыт:
   ```bash
   NOTE_NAME=$(basename "{REPORT_PATH}" .md)
   obsidian append path="Периоды/День/$(date +%F).md" content="- [[${NOTE_NAME}]] — научный ресерч, ожидает ревью" 2>/dev/null || true
   obsidian backlinks file="${NOTE_NAME}" counts 2>/dev/null || true
   ```

7. **Резюме пользователю (decision-first):**
   - **Вердикт под решение** (`decisionContext`): что делать / чего не делать / при каком условии —
     2-4 предложения из `synthMeta.mainConclusion` и `[!success]` draft-отчёта.
   - **Насколько верить:** `synthMeta.gradeMax` / `evidenceStrengthMax` / `reliabilityScore` критика.
   - **Что отсеяли:** `retractedExcluded` (отозванные) + `enrich.unverified` (titleMatch=false, не в
     Evidence Table) + claims, оспоренные критиком — они **не вошли** в выводы (фильтрация, не критика поверх).
   - **Охват:** `papersTotal` статей (из них `addedBySnowball` добавил snowball); `gaps`.
   - **Персонализация:** если включена — какие выводы помечены «под твой профиль…».
   - Путь к отчёту `REPORT_PATH` (vault `Знания/Ресерчи`) + `{WORK_DIR}/` (полный процесс:
     per-source, enrich, adversarial.md). Напоминание: `verified: false` → попадёт в
     `Обзоры/wiki-stream.base` «Pending AI drafts»; после ревью пользователь ставит `verified: true`.

## Обработка ошибок

- `insufficient-sources` (<2 источников с результатами) — покажи что собралось, в vault не пиши.
- Source-агенты имеют встроенные фоллбэки внутри протоколов (Brave `site:` / retry).
- obsidian CLI недоступен (Obsidian закрыт) — vault-контракт деградирует: пиши файл в `REPORT_PATH`
  без dedup/wikilinks/записи в дневную заметку, предупреди пользователя. Callouts работают всегда.
- Профиль читает ТОЛЬКО главная сессия и ТОЛЬКО при `personalize=true` — приватные данные не уходят в субагенты.
