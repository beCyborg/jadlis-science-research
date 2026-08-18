export const meta = {
  name: 'search-paper-core',
  description: 'Ядро search-paper: query-builder → fan-out по научным источникам → citation snowballing → Crossref/Unpaywall enrich (retraction + anti-hallucination) → GRADE-синтез → adversarial critic → fix. Vault-контракт — в скилле.',
  phases: [
    { title: 'Query', detail: 'PICO/PECO → блоки синонимов → готовые строки запросов per-source' },
    { title: 'Fan-out', detail: 'до 11 источников параллельно (PubMed/Europe PMC/S2/OpenAlex/arXiv/Cochrane/web-experts/Epistemonikos/ClinicalTrials + опц. scite/consensus)' },
    { title: 'Snowball', detail: 'dedup → ≤6 hubs → forward/backward citation chasing до насыщения (≤2 итераций, cap 120)' },
    { title: 'Enrich', detail: 'батчи DOI: Crossref retraction+titleMatch+funder, Unpaywall OA, fulltext top-OA' },
    { title: 'Synthesize', detail: 'GRADE per-outcome → decision-first draft в workDir' },
    { title: 'Adversarial', detail: 'независимый критик: контраргументы, per-claim challenge, PubPeer, retraction recheck' },
    { title: 'Fix', detail: 'правки confidence≥0.7 → синк TL;DR/Evidence Table/frontmatter' },
  ],
}

// ── Параметры (skill передаёт после Phase A intake; дефолты — для dry-run) ──
const A = (() => { try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch (e) { return {} } })()
const QUERY_RU = A.refinedQueryRu || 'Омега-3 и триглицериды (dry-run)'
const QUERY_EN = A.refinedQueryEn || 'omega-3 fatty acids supplementation effect on triglycerides in adults'
const FRAMING = A.framing === 'PICO' ? 'PICO' : 'PECO'              // питание/экспозиция → PECO (дефолт)
const DISCIPLINE = A.discipline || 'biomedical'                     // biomedical|cs|physics|social|general
const DECISION = A.decisionContext || ''
const POPULATION = A.populationLayer || 'здоровые взрослые, human-приоритет'
const TIME_HORIZON = A.timeHorizon || 'свежее 5 лет, но классику не отбрасывать'
const GUIDELINES = A.guidelines !== false                          // включать ли cochrane/guidelines
const LANG = A.lang === 'en' ? 'en' : 'ru'
const PERSONALIZE = !!A.personalize
const PROFILE_CONTEXT = PERSONALIZE && A.profileContext ? A.profileContext : null
const MODULES = A.modules || {}                                    // {scite:bool, consensus:bool} — env-детект делает скилл
const AI_MODEL = A.aiModel || 'unknown'
const DATE = A.date || 'DRYRUN-DATE'
const WORK_DIR = A.workDir || '.search-paper/dryrun'
// ${CLAUDE_PLUGIN_ROOT} в JS НЕ подставляется — скилл передаёт его значением.
const PLUGIN_ROOT = A.pluginRoot || '.'
const VAULT_PATH = A.vaultPath || ''

// Воркер: пиннинг Opus 5 + effort xhigh через субагента researcher-opus-xhigh (как в full-research-core).
const WORKER_OPTS = A.workerOpts || { agentType: 'jadlis-research:researcher-opus-xhigh' }
const w = extra => Object.assign({}, WORKER_OPTS, extra)

// ── Константы always-deep (saturation/cap/budget гейты вместо tiered-режима) ──
const MIN_SOURCES = 2          // <2 источников → insufficient-sources, скилл не пишет в vault
const PAPER_CAP = 120          // жёсткий потолок корпуса (защита snowball от взрыва)
const HUB_CAP = 6              // ≤6 hub-ов на итерацию snowball
const MAX_SNOWBALL_ITERS = 2
const SATURATION_THRESHOLD = 0.10  // стоп если newUnique/canonical < 0.10
const ENRICH_BATCH = 25        // DOI на один Crossref-батч (polite pool 10 RPS → секунды)
const FULLTEXT_CAP = 6         // top-OA статей под fulltext-summary
const SNOWBALL_BUDGET_FLOOR = 80_000   // не начинать итерацию snowball, если меньше осталось
const FULLTEXT_BUDGET_FLOOR = 50_000   // не тянуть fulltext, если меньше осталось

const SKILL_DIR = `${PLUGIN_ROOT}/skills/search-paper`
const PROTO = id => `${SKILL_DIR}/protocols/${id}`

// ── Реестр источников: 9 бесплатных + 2 опц. модуля ──
const ALL_SOURCES = {
  pubmed:        { source: 'PubMed',          prefix: 'pm', protocol: PROTO('pubmed-protocol.md'),               file: 'pubmed.md',        kind: 'biomed' },
  europepmc:     { source: 'Europe PMC',      prefix: 'em', protocol: PROTO('europe-pmc-protocol.md'),           file: 'europe-pmc.md',    kind: 'biomed' },
  s2:            { source: 'Semantic Scholar', prefix: 's2', protocol: PROTO('s2-protocol.md'),                  file: 's2.md',            kind: 'general' },
  openalex:      { source: 'OpenAlex',        prefix: 'oa', protocol: PROTO('openalex-protocol.md'),             file: 'openalex.md',      kind: 'general' },
  arxiv:         { source: 'arXiv',           prefix: 'ax', protocol: PROTO('arxiv-protocol.md'),                file: 'arxiv.md',         kind: 'preprint' },
  cochrane:      { source: 'Cochrane + Guidelines', prefix: 'co', protocol: PROTO('cochrane-guidelines-protocol.md'), file: 'cochrane.md', kind: 'guideline' },
  webExperts:    { source: 'Web Experts',     prefix: 'w',  protocol: PROTO('web-experts-protocol.md'),          file: 'web-experts.md',   kind: 'expert' },
  epistemonikos: { source: 'Epistemonikos',   prefix: 'ep', protocol: PROTO('epistemonikos-protocol.md'),        file: 'epistemonikos.md', kind: 'guideline' },
  clinicaltrials:{ source: 'ClinicalTrials.gov', prefix: 'ct', protocol: PROTO('clinicaltrials-protocol.md'),    file: 'clinicaltrials.md', kind: 'trials' },
  scite:         { source: 'scite.ai',        prefix: 'sc', protocol: PROTO('scite-module.md'),                  file: 'scite.md',         kind: 'module' },
  consensus:     { source: 'Consensus',       prefix: 'cn', protocol: PROTO('consensus-module.md'),              file: 'consensus.md',     kind: 'module' },
}

// Базовый набор: 9 бесплатных. arXiv/cochrane/epistemonikos снимаются по дисциплине.
function defaultSources() {
  const base = ['pubmed', 'europepmc', 's2', 'openalex', 'arxiv', 'cochrane', 'webExperts', 'epistemonikos', 'clinicaltrials']
  const isBiomed = DISCIPLINE === 'biomedical' || DISCIPLINE === 'general'
  const wantsPreprint = /preprint|biorxiv|medrxiv|pre-print/i.test(QUERY_EN)
  return base.filter(s => {
    if (s === 'arxiv') return DISCIPLINE === 'cs' || DISCIPLINE === 'physics' || wantsPreprint
    if ((s === 'cochrane' || s === 'epistemonikos') && !GUIDELINES) return false
    if ((s === 'cochrane' || s === 'epistemonikos' || s === 'clinicaltrials') && !isBiomed) return false
    return true
  })
}
let SELECTED = (Array.isArray(A.sources) && A.sources.length)
  ? A.sources.filter(s => ALL_SOURCES[s])
  : defaultSources()
if (MODULES.scite) SELECTED.push('scite')
if (MODULES.consensus) SELECTED.push('consensus')
SELECTED = [...new Set(SELECTED)]

const TOOL_NOTE = 'ВАЖНО: НЕ используй встроенные WebSearch/WebFetch (забанены). Нужные MCP-инструменты (brave/firecrawl) загружай через ToolSearch перед вызовом. Brave (тариф Search): 50 req/s — параллельные вызовы OK. НЕ спавни вложенных субагентов, НЕ вызывай skills.'
const NO_HALLUCINATION = 'КРИТИЧЕСКОЕ ПРАВИЛО: НИКОГДА не выдумывай DOI, PMID, externalId. Только из ответа API/MCP. Если инструмент не вернул идентификатор — пиши null.'

// ── JSON-схемы (additionalProperties:false, явный required) ──
const CONCEPT = {
  type: 'object', additionalProperties: false,
  properties: {
    label: { type: 'string', description: 'компонент PICO/PECO, напр. "интервенция: омега-3"' },
    synonyms: { type: 'array', items: { type: 'string' }, description: 'OR-блок синонимов' },
    meshTerms: { type: 'array', items: { type: 'string' }, description: 'MeSH-термины (для PubMed); [] если неприменимо' },
  },
  required: ['label', 'synonyms', 'meshTerms'],
}
const SEARCH_PLAN = {
  type: 'object', additionalProperties: false,
  properties: {
    discipline: { type: 'string', enum: ['biomedical', 'cs', 'physics', 'social', 'general'] },
    framing: { type: 'string', enum: ['PICO', 'PECO'] },
    pico: {
      type: 'object', additionalProperties: false,
      properties: {
        population: { type: 'string' },
        intervention: { type: 'string', description: 'для PECO — exposure' },
        comparison: { type: 'string' },
        outcome: { type: 'string' },
      },
      required: ['population', 'intervention', 'comparison', 'outcome'],
    },
    concepts: { type: 'array', items: CONCEPT },
    queries: {
      type: 'object', additionalProperties: false,
      description: 'готовая строка запроса под каждый выбранный источник; null если источник пропущен',
      properties: {
        pubmed: { type: ['string', 'null'], description: 'Boolean+MeSH: (term[mh] OR syn) AND (...)' },
        europepmc: { type: ['string', 'null'] },
        s2: { type: ['string', 'null'], description: 'semantic/relevance строка' },
        openalex: { type: ['string', 'null'] },
        arxiv: { type: ['string', 'null'] },
        cochrane: { type: ['string', 'null'] },
        webExperts: { type: ['string', 'null'] },
        epistemonikos: { type: ['string', 'null'] },
        clinicaltrials: { type: ['string', 'null'] },
        scite: { type: ['string', 'null'] },
        consensus: { type: ['string', 'null'] },
      },
      required: ['pubmed', 'europepmc', 's2', 'openalex', 'arxiv', 'cochrane', 'webExperts', 'epistemonikos', 'clinicaltrials', 'scite', 'consensus'],
    },
    skip: { type: 'array', items: { type: 'string' }, description: 'ключи источников, которые осмысленно пропустить для этого запроса' },
    notes: { type: 'string', description: 'кратко: логика фрейминга и расширения' },
  },
  required: ['discipline', 'framing', 'pico', 'concepts', 'queries', 'skip', 'notes'],
}

const STUDY_TYPES = ['meta-analysis', 'systematic-review', 'rct', 'cohort', 'case-control', 'cross-sectional', 'case-report', 'preprint', 'review', 'guideline', 'clinical-trial-record', 'animal', 'in-vitro', 'other']
const PAPER = {
  type: 'object', additionalProperties: false,
  properties: {
    prefix: { type: 'string', description: 'напр. [pm1], [oa3]' },
    title: { type: 'string' },
    doi: { type: ['string', 'null'], description: 'ТОЛЬКО из API; иначе null' },
    pmid: { type: ['string', 'null'] },
    externalId: { type: ['string', 'null'], description: 'OpenAlex/S2/arXiv/NCT id для snowball' },
    year: { type: ['integer', 'null'] },
    studyType: { type: 'string', enum: STUDY_TYPES },
    sampleN: { type: ['integer', 'null'] },
    citations: { type: ['integer', 'null'] },
    influentialCitations: { type: ['integer', 'null'] },
    fwci: { type: ['number', 'null'], description: 'Field-Weighted Citation Impact (OpenAlex)' },
    isOA: { type: 'boolean' },
    oaUrl: { type: ['string', 'null'] },
    contrib: { type: 'string', description: 'главный результат, ≤30 слов' },
    qualitySignals: { type: 'array', items: { type: 'string' }, description: 'multi-center / pre-registered / blinded / large-N / industry-funded и т.п.' },
  },
  required: ['prefix', 'title', 'doi', 'pmid', 'externalId', 'year', 'studyType', 'sampleN', 'citations', 'influentialCitations', 'fwci', 'isOA', 'oaUrl', 'contrib', 'qualitySignals'],
}
const SEARCH = {
  type: 'object', additionalProperties: false,
  properties: {
    source: { type: 'string' },
    prefix: { type: 'string' },
    findings: { type: 'array', items: { type: 'string' }, description: '3-5 тезисов' },
    papers: { type: 'array', items: PAPER },
    sourceQuality: { type: 'string', enum: ['HIGH', 'MEDIUM', 'LOW'] },
    fileWritten: { type: ['string', 'null'] },
  },
  required: ['source', 'prefix', 'findings', 'papers', 'sourceQuality', 'fileWritten'],
}

const HUB = {
  type: 'object', additionalProperties: false,
  properties: {
    externalId: { type: 'string', description: 'OpenAlex Wxxx / DOI / S2 id / PMID' },
    api: { type: 'string', enum: ['openalex', 's2'], description: 'через какой API чейсить (OpenAlex 100 RPS предпочтительнее)' },
    title: { type: 'string' },
    reason: { type: 'string', description: 'почему hub: высокие citations/FWCI / meta/SR' },
  },
  required: ['externalId', 'api', 'title', 'reason'],
}
const SNOWBALL_DEDUP = {
  type: 'object', additionalProperties: false,
  properties: {
    seedFile: { type: ['string', 'null'], description: 'путь к дедупленному seed-файлу в workDir' },
    canonicalCount: { type: 'integer', description: 'число уникальных статей после дедупа' },
    seenKeys: { type: 'array', items: { type: 'string' }, description: 'нормализованные ключи (DOI-norm или title-key) — для префильтра snowball' },
    hubs: { type: 'array', items: HUB, description: `≤${HUB_CAP} hub-ов: топ citations/FWCI + все meta/SR с external id` },
    saturationEstimate: { type: 'number', description: 'оценка полноты 0..1 (грубо: уникальных найдено / ожидаемо)' },
  },
  required: ['seedFile', 'canonicalCount', 'seenKeys', 'hubs', 'saturationEstimate'],
}
const SNOWBALL_RESULT = {
  type: 'object', additionalProperties: false,
  properties: {
    hubId: { type: 'string' },
    apiUsed: { type: 'string' },
    addedPapers: { type: 'array', items: PAPER, description: 'НОВЫЕ статьи (нет в seenKeys), forward+backward' },
    note: { type: 'string' },
  },
  required: ['hubId', 'apiUsed', 'addedPapers', 'note'],
}

const ENRICH_ITEM = {
  type: 'object', additionalProperties: false,
  properties: {
    doi: { type: 'string' },
    crossrefVerified: { type: 'boolean', description: 'DOI резолвится в Crossref' },
    titleMatch: { type: 'boolean', description: 'title/authors/year из Crossref совпали с заявленными (anti-hallucination)' },
    isRetracted: { type: 'boolean', description: 'update-to[].type == retraction' },
    retractionDate: { type: ['string', 'null'] },
    industryFunded: { type: 'boolean', description: 'funder[] содержит pharma/biotech' },
    oaStatus: { type: ['string', 'null'], enum: ['gold', 'hybrid', 'bronze', 'green', 'closed', null] },
    isOA: { type: 'boolean' },
    oaPdfUrl: { type: ['string', 'null'] },
  },
  required: ['doi', 'crossrefVerified', 'titleMatch', 'isRetracted', 'retractionDate', 'industryFunded', 'oaStatus', 'isOA', 'oaPdfUrl'],
}
const ENRICH_BATCH_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    batchIndex: { type: 'integer' },
    items: { type: 'array', items: ENRICH_ITEM },
    fileWritten: { type: ['string', 'null'] },
  },
  required: ['batchIndex', 'items', 'fileWritten'],
}
const FULLTEXT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    doi: { type: 'string' },
    extracted: { type: 'boolean' },
    summary: { type: 'string', description: 'methods/N/inclusion/results/limitations/COI/RoB-signals, ≤1K токенов' },
    fileWritten: { type: ['string', 'null'] },
  },
  required: ['doi', 'extracted', 'summary', 'fileWritten'],
}

const SYNTH = {
  type: 'object', additionalProperties: false,
  properties: {
    reportPath: { type: 'string' },
    queryRu: { type: 'string', description: 'краткая русская формулировка ≤25 симв для имени файла' },
    mainConclusion: { type: 'string' },
    evidenceStrengthMax: { type: 'string', enum: ['STRONG', 'MODERATE', 'WEAK', 'UNVERIFIED'] },
    gradeMax: { type: 'string', enum: ['HIGH', 'MODERATE', 'LOW', 'VERY LOW'] },
    retractedExcluded: { type: 'array', items: { type: 'string' }, description: 'DOI/title исключённых отозванных' },
    relatedCandidates: { type: 'array', items: { type: 'string' }, description: 'ключевые слова для obsidian-поиска связанных заметок' },
    gaps: { type: 'array', items: { type: 'string' } },
    keyDois: { type: 'array', items: { type: 'string' }, description: 'DOI ключевых статей выводов — для retraction recheck критиком' },
  },
  required: ['reportPath', 'queryRu', 'mainConclusion', 'evidenceStrengthMax', 'gradeMax', 'retractedExcluded', 'relatedCandidates', 'gaps', 'keyDois'],
}
const EDIT_ITEM = {
  type: 'object', additionalProperties: false,
  properties: {
    id: { type: 'string', description: 'F1, F2, ...' },
    finding: { type: 'string' },
    action: { type: 'string', description: 'GRADE downgrade / caveat / red flag / переформулировка / исключить' },
    confidence: { type: 'number', description: '0..1; <0.7 fix-агент пропустит' },
    affectsTldr: { type: 'boolean' },
    targetSections: { type: 'array', items: { type: 'string' } },
  },
  required: ['id', 'finding', 'action', 'confidence', 'affectsTldr', 'targetSections'],
}
const CLAIM_VERDICT = {
  type: 'object', additionalProperties: false,
  properties: {
    claim: { type: 'string' },
    verdict: { type: 'string', enum: ['CONFIRMED', 'CHALLENGED', 'OUTDATED'] },
    evidence: { type: 'string' },
  },
  required: ['claim', 'verdict', 'evidence'],
}
const ADVERSARIAL = {
  type: 'object', additionalProperties: false,
  properties: {
    reviewPath: { type: ['string', 'null'], description: 'путь к adversarial.md в workDir' },
    reliabilityScore: { type: 'integer', description: '0..10 итоговая надёжность отчёта' },
    claimVerdicts: { type: 'array', items: CLAIM_VERDICT },
    retractionRecheck: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { doi: { type: 'string' }, status: { type: 'string', enum: ['clean', 'RETRACTED', 'unresolved'] } }, required: ['doi', 'status'] } },
    pubpeerFlags: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { title: { type: 'string' }, severity: { type: 'string', enum: ['critical', 'minor', 'neutral', 'none'] }, url: { type: ['string', 'null'] } }, required: ['title', 'severity', 'url'] } },
    edits: { type: 'array', items: EDIT_ITEM, description: 'авторитетная таблица правок для fix-агента' },
  },
  required: ['reviewPath', 'reliabilityScore', 'claimVerdicts', 'retractionRecheck', 'pubpeerFlags', 'edits'],
}
const FIX = {
  type: 'object', additionalProperties: false,
  properties: {
    applied: { type: 'array', items: { type: 'string' }, description: 'ID применённых правок' },
    skipped: { type: 'array', items: { type: 'string' }, description: 'ID + причина пропуска' },
    tldrUpdated: { type: 'boolean' },
    evidenceTableUpdated: { type: 'boolean' },
    frontmatterUpdated: { type: 'boolean' },
    reliabilityScore: { type: 'integer' },
  },
  required: ['applied', 'skipped', 'tldrUpdated', 'evidenceTableUpdated', 'frontmatterUpdated', 'reliabilityScore'],
}

// ── helpers ──
function chunk(arr, n) { const out = []; for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n)); return out }
function normDoi(d) { return (d || '').trim().replace(/^https?:\/\/(dx\.)?doi\.org\//i, '').replace(/^doi:/i, '').toLowerCase() }
function paperKey(p) { return normDoi(p.doi) || (p.pmid ? `pmid:${p.pmid}` : '') || (p.externalId ? `ext:${p.externalId}` : '') || `t:${(p.title || '').toLowerCase().slice(0, 60)}` }

// ═══════════════════════════════════════════════════════════════════
// Phase Query — PICO/PECO → блоки синонимов → per-source строки
// ═══════════════════════════════════════════════════════════════════
function queryPrompt() {
  return `Ты — query-builder научного литературного обзора. Преврати запрос в МЕТОДОЛОГИЮ-ДАННЫЕ: блоки синонимов и готовые строки запросов под каждый источник. Source-агенты запрос НЕ строят — берут твои строки как есть.

ЗАПРОС (RU): ${QUERY_RU}
ЗАПРОС (EN): ${QUERY_EN}
ФРЕЙМИНГ: ${FRAMING} (PICO — явная интервенция; PECO — экспозиция/питание)
ДИСЦИПЛИНА (гипотеза): ${DISCIPLINE}
ПОПУЛЯЦИЯ: ${POPULATION}
ГОРИЗОНТ: ${TIME_HORIZON}
${DECISION ? `РЕШЕНИЕ ПОЛЬЗОВАТЕЛЯ: ${DECISION}` : ''}

ВЫБРАННЫЕ ИСТОЧНИКИ: ${SELECTED.join(', ')}
(для невыбранных — поставь null в queries и добавь в skip)

ПОДГОТОВКА: через Bash выполни \`mkdir -p ${WORK_DIR}\` (директория для файлов фаз).

ЗАДАЧА:
1. Разложи запрос по ${FRAMING}: population, intervention/exposure, comparison, outcome. Comparison/Outcome можно оставить широкими — их детализируют статьи.
2. Для КАЖДОГО компонента собери блок синонимов (OR) + MeSH-термины (для PubMed). Учитывай варианты написания, бренды/генерики, аббревиатуры.
3. Собери готовые строки запросов:
   - pubmed — Boolean с MeSH: \`(концепт1[mh] OR син OR син) AND (концепт2[mh] OR ...)\`, при необходимости фильтры [pt]/[dp]. Прочитай ${PROTO('pubmed-protocol.md')} для синтаксиса.
   - s2 — relevance/semantic строка (без скобок-MeSH).
   - openalex / europepmc / arxiv / cochrane / epistemonikos / clinicaltrials — нативный синтаксис каждого (прочитай соответствующий protocol при сомнении).
   - webExperts — короткая тема EN.
   - scite / consensus — только если в выбранных.
4. skip[]: какие источники бессмысленны для запроса (напр. arXiv для чисто клинического вопроса; clinicaltrials для не-интервенционного).
5. Материализуй методологию в данные, агент-источник не должен ничего достраивать.

${NO_HALLUCINATION}
Верни строго по схеме SEARCH_PLAN. Всё на ${LANG === 'en' ? 'английском' : 'русском'} (строки запросов — на языке источника).`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Fan-out — промпт источника
// ═══════════════════════════════════════════════════════════════════
function sourcePrompt(key, plan) {
  const c = ALL_SOURCES[key]
  const qstr = (plan.queries && plan.queries[key]) || QUERY_EN
  return `Ты — научный поисковый агент источника ${c.source}. Найди релевантные статьи и запиши результат.

ГОТОВАЯ СТРОКА ЗАПРОСА (используй как есть, не переписывай логику): ${qstr}
ИСХОДНЫЙ ВОПРОС (RU): ${QUERY_RU}
EN: ${QUERY_EN}
ГОРИЗОНТ: ${TIME_HORIZON}
ДИСЦИПЛИНА: ${plan.discipline || DISCIPLINE}
${DECISION ? `РЕШЕНИЕ: ${DECISION} (приоритет — статьи, помогающие принять именно его)` : ''}

ПРОТОКОЛ: прочитай ${c.protocol} (Read) и следуй ему шаг за шагом — Primary → Fallback при ошибке.
PLUGIN_ROOT = ${PLUGIN_ROOT}
Пути внутри протоколов и справочников записаны как {PLUGIN_ROOT}/… — подставляй вместо плейсхолдера строку выше. Литеральный \`{PLUGIN_ROOT}\` в команду не отправляй.
${TOOL_NOTE}
${NO_HALLUCINATION}

ПРАВИЛА:
1. Лимит ~20 результатов; >20 → оставь TOP-20 по composite(citations × recency), отметь усечение.
2. Для каждой статьи заполни поля PAPER: prefix ([${c.prefix}1], [${c.prefix}2], ...), title, doi/pmid/externalId (ТОЛЬКО из API), year, studyType (enum), sampleN, citations, influentialCitations, fwci (если источник даёт), isOA, oaUrl, contrib (≤30 слов), qualitySignals (multi-center/pre-registered/blinded/large-N/industry-funded/animal/in-vitro).
3. externalId — обязателен где есть (OpenAlex Wxxx, S2 id, arXiv id, NCT id): нужен для snowball-чейсинга.
4. studyType определяй по publicationTypes/type/заголовку; если неясно — "other".

СОХРАНЕНИЕ: через Write сохрани человекочитаемый дамп в ${WORK_DIR}/${c.file} (заголовок, ключевые находки, по статье — метаданные). Затем верни по схеме SEARCH: source="${c.source}", prefix="${c.prefix}", findings[], papers[], sourceQuality, fileWritten="${WORK_DIR}/${c.file}".
Если источник недоступен после фоллбэков — sourceQuality="LOW", papers=[], отметь в findings.`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Snowball — dedup + hub-chasing
// ═══════════════════════════════════════════════════════════════════
function dedupPrompt(files) {
  return `Ты — агент дедупликации и выбора hub-ов для citation snowballing.

ЗАПРОС: ${QUERY_EN}
Файлы источников (Read каждый):
${files.map(f => `- ${f}`).join('\n')}

Прочитай протокол агрегации: ${SKILL_DIR}/references/aggregation-protocol.md (DOI-нормализация, Jaccard≥0.85, authors+year fallback).

ЗАДАЧА:
1. Прочитай все файлы, собери единый список статей.
2. Дедуп: DOI-norm exact → fuzzy title (Jaccard≥0.85) → authors+year. Посчитай canonicalCount.
3. seenKeys[]: для каждой уникальной статьи — нормализованный ключ (DOI-norm, иначе pmid:/ext:/t:первые60символов title).
4. Выбери ≤${HUB_CAP} hub-ов для чейсинга: топ по citations/FWCI + ВСЕ мета-анализы и systematic reviews, у которых есть externalId. Для каждого hub: externalId, api ('openalex' предпочтительнее — 100 RPS; 's2' только если нет OpenAlex id), title, reason.
5. saturationEstimate (0..1): грубая оценка полноты текущего корпуса.
6. Запиши дедупленный seed-список в ${WORK_DIR}/_seed.md.

${NO_HALLUCINATION}
Верни строго по схеме SNOWBALL_DEDUP. НЕ делай сетевых вызовов — работай по файлам.`
}
function chasePrompt(hub, seenKeys) {
  return `Ты — citation-chasing агент (forward + backward) для snowballing.

HUB: "${hub.title}" — externalId=${hub.externalId}, через API=${hub.api}
ЗАПРОС (релевантность): ${QUERY_EN}

ЗАДАЧА:
1. Через ${hub.api === 'openalex' ? `OpenAlex (прочитай ${PROTO('openalex-protocol.md')})` : `Semantic Scholar (прочитай ${PROTO('s2-protocol.md')}, используй /citations и /references, batch-endpoint)`} получи:
   - FORWARD: статьи, ЦИТИРУЮЩИЕ hub (citations).
   - BACKWARD: статьи из СПИСКА ЛИТЕРАТУРЫ hub (references).
2. Оставь только РЕЛЕВАНТНЫЕ запросу и НОВЫЕ — которых НЕТ среди уже виденных ключей:
${seenKeys.slice(0, 400).map(k => `  ${k}`).join('\n')}
   (ключ статьи: DOI-norm, иначе pmid:/ext:/t:первые60символов title)
3. Приоритет — мета/SR/RCT и высоко-цитируемые. Верни до 25 новых статей.

${TOOL_NOTE}
${NO_HALLUCINATION}
Используй list-запросы (не singleton в цикле), per_page вверх. HTTP 429 → graceful skip (без Brave-fallback).
Верни строго по схеме SNOWBALL_RESULT: hubId="${hub.externalId}", apiUsed, addedPapers[] (только новые), note.`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Enrich — Crossref/Unpaywall батч + fulltext
// ═══════════════════════════════════════════════════════════════════
function enrichPrompt(dois, idx) {
  return `Ты — enrichment-агент батча #${idx}. Проверь DOI через Crossref + Unpaywall.

DOI батча (${dois.length}):
${dois.map(d => `- ${d}`).join('\n')}

Для каждого DOI через Bash curl (ПОСЛЕДОВАТЕЛЬНО, polite pool):
1. Crossref: \`curl -s "https://api.crossref.org/works/{DOI}?mailto=\${CROSSREF_MAILTO}" -H "User-Agent: search-paper/1.0 (mailto:\${CROSSREF_MAILTO})"\`
   - crossrefVerified: DOI резолвится (HTTP 200, message есть).
   - isRetracted: ИСТИНА, если ЛЮБОЙ из сигналов (проверяй ВСЕ три — одного update-to НЕДОСТАТОЧНО):
     (a) \`message.updated-by[]\` содержит элемент с \`type == "retraction"\` — ОСНОВНОЙ сигнал отозванной статьи (ставит retractionDate = его updated.date-parts);
     (b) title начинается с "RETRACTED", "Retracted:", "WITHDRAWN" — вторичный сигнал (напр. Wakefield 1998: title "RETRACTED: …", updated-by[].type=="retraction");
     (c) \`message.update-to[].type == "retraction"\` — означает, что САМ этот DOI является уведомлением об отзыве (тоже исключаем из доказательной базы).
     Пример: DOI 10.1016/S0140-6736(97)11096-0 → isRetracted=true (через updated-by + title-префикс).
   - industryFunded: \`message.funder[].name\` содержит pharma/biotech (Pfizer, Novartis, Bayer, Merck, GSK, Roche, AbbVie, Sanofi, биотех-вендоры и т.п.).
   - titleMatch (ANTI-HALLUCINATION): сверь title из Crossref с заявленным title статьи — совпадает (с точностью до регистра/пунктуации/года)? Если расходится или DOI не резолвится → titleMatch=false (статья «unverified»).
   Rate limit: 10 RPS polite (gap ~100ms). HTTP 429 → backoff 1s/2s/4s, max 3.
2. Unpaywall: \`curl -s "https://api.unpaywall.org/v2/{DOI}?email=\${UNPAYWALL_EMAIL}"\`
   - isOA, oaStatus (gold/hybrid/bronze/green/closed), oaPdfUrl = best_oa_location.url_for_pdf.

Запиши дамп в ${WORK_DIR}/enrich_${idx}.md.
Верни строго по схеме ENRICH_BATCH_SCHEMA: batchIndex=${idx}, items[] (по одному ENRICH_ITEM на DOI), fileWritten.
${NO_HALLUCINATION} НЕ выдумывай поля — если curl не вернул, ставь false/null.`
}
function fulltextPrompt(p) {
  return `Ты — fulltext-extraction агент. Извлеки структурированное резюме одной OA-статьи.

СТАТЬЯ: "${p.title}"
DOI: ${p.doi}
OA PDF/URL: ${p.oaUrl || '(возьми из enrich-файлов в ' + WORK_DIR + ')'}

ЗАДАЧА:
1. Получи fulltext: \`defuddle parse "{url}" --md\` через Bash ИЛИ firecrawl_scrape (waitFor 5000 для PDF). Загрузи firecrawl через ToolSearch при необходимости.
2. Извлеки ТОЛЬКО structured summary (≤1K токенов): methods (1-2 предл.), sample_size (N + популяция), inclusion_criteria (2-3), results_primary (1 абзац), limitations (3), conflict_of_interest (дословно), rob_signals (blinding/ITT/allocation concealment/pre-registration).
3. НЕ возвращай raw PDF text.

Запиши в ${WORK_DIR}/fulltext_${(p.doi || p.title).replace(/[^a-z0-9]/gi, '').slice(0, 24)}.md.
${TOOL_NOTE}
Верни по схеме FULLTEXT_SCHEMA: doi="${p.doi}", extracted (bool), summary, fileWritten. Если fulltext недоступен — extracted=false, summary="".`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Synthesize — GRADE per-outcome decision-first draft
// ═══════════════════════════════════════════════════════════════════
function synthPrompt(allFiles, enrichItems, papersTotal, addedBySnowball) {
  const retracted = enrichItems.filter(e => e.isRetracted).map(e => e.doi)
  const unverified = enrichItems.filter(e => e.crossrefVerified && !e.titleMatch).map(e => e.doi)
  return `Ты — научный аналитик-синтезатор. Из сырья источников + enrich + fulltext построй ДОКАЗАТЕЛЬНЫЙ отчёт в формате DECISION-FIRST: читатель видит выводы/действия/кому верить; процесс (GRADE-таблица, Evidence Table, ссылки) — в свёрнутых [!note]- в конце.

ЗАПРОС (RU): ${QUERY_RU}
EN: ${QUERY_EN}
ДАТА: ${DATE}
${DECISION ? `РЕШЕНИЕ ПОЛЬЗОВАТЕЛЯ (весь отчёт строится под него): ${DECISION}` : 'РЕШЕНИЕ: не задано — выведи вердикт под самое вероятное решение.'}
${PROFILE_CONTEXT ? `\nПЕРСОНАЛИЗАЦИЯ (профиль здоровья пользователя — учитывай в «под твой профиль…», флаги безопасности наверх):\n${PROFILE_CONTEXT}\n` : ''}
Корпус: ${papersTotal} статей (из них ${addedBySnowball} добавлено snowball-чейсингом).

ФАЙЛЫ (Read нужные):
${allFiles.map(f => `- ${f}`).join('\n')}

ОБЯЗАТЕЛЬНО прочитай:
- ${SKILL_DIR}/references/quality-framework.md — GRADE per-outcome, RoB 2.0/ROBUST-RCT, AMSTAR 2, NOS, Red flags.
- ${SKILL_DIR}/examples/sample-report.md — ПРИМЕР стиля: тон, плотность, оформление.
  Обязательный контракт — спека формата выше; структуру и объём адаптируй под тему.

ENRICHMENT-ФЛАГИ:
- ОТОЗВАННЫЕ (исключить из выводов и Evidence Table, перечислить в retractedExcluded): ${JSON.stringify(retracted)}
- UNVERIFIED (titleMatch=false → НЕ в Evidence Table без явной пометки «не верифицировано»): ${JSON.stringify(unverified)}

МЕТОДОЛОГИЯ СИНТЕЗА (процесс в отчёт НЕ пишется, только его итог):
1. Dedup: DOI→fuzzy title→authors+year. sources[] = все источники статьи.
2. GRADE per-OUTCOME (не per-paper): старт RCT→HIGH, observational→LOW; 5 downgrade (RoB/inconsistency/indirectness/imprecision/pub-bias), 3 upgrade для observational. Study type = контейнер выбора фреймворка (meta→AMSTAR2, RCT→RoB2, cohort→NOS).
3. Red flags из enrich: retracted (исключить), industry-funded, small-N (<100 RCT), single-center, no pre-registration.
4. Circular reporting: ≥2 статьи на 1 оригинал = 1 independent source.
5. Двойная шкала: бейдж цитаты [id·PMID·GRADE] несёт certainty доказательства; надёжность ИСТОЧНИКА (A–E) — в таблице «Кому доверять».

ФОРМАТ — Obsidian Flavored Markdown, frontmatter В САМОМ НАЧАЛЕ:
---
type: research
created: ${DATE}
ai_drafted: true
verified: false
ai_model: "${AI_MODEL}"
tags: []
query: "${QUERY_RU.replace(/"/g, '«')}"
decision: "${DECISION.replace(/"/g, '«') || ''}"
discipline: "${DISCIPLINE}"
framing: "${FRAMING}"
papers_total: ${papersTotal}
added_by_snowball: ${addedBySnowball}
evidence_strength_max: "{STRONG/MODERATE/WEAK/UNVERIFIED}"
grade_max: "{HIGH/MODERATE/LOW/VERY LOW}"
retracted_excluded: {N}
personalized: ${PERSONALIZE}
gaps: [{2-4 строки}]
work_dir: "${WORK_DIR}"
---

СТРУКТУРА (видимая зона ≤140 строк; обоснования НЕ удаляй — сворачивай в [!note]-):
1. # {Тема} + строка **Дата:** | **Источников:** N | **Статей:** ${papersTotal}
2. > [!abstract] TL;DR — 3 инсайта, у каждого GRADE; ответ «что делать» в первых 2 предложениях.
3. > [!success] Вердикт под твоё решение — прямой ответ на decision.
4. > [!danger] Безопасность — ТОЛЬКО если есть (противопоказания, побочки; флаги из профиля — наверх). Нет рисков → секцию пропусти.
5. ## Что делать — каждый пункт > [!tip] (сильное доказательство) или > [!question] (слабое); GRADE per outcome; ${PROFILE_CONTEXT ? '«под твой профиль: …» с реальными метриками; ' : ''}бейджи-ссылки.
6. ## Чего НЕ делать — > [!failure].
7. ## Как относиться / читать сигналы — > [!info]: Very Low ≠ «не работает»; observational ≠ causal; surrogate vs hard outcome; mouse→human.
8. ## Кому доверять в теме — таблица Источник | Надёжность A–E | Почему (Cochrane/SR=A, Examine/RedPen=A–B, эксперты-практики=B, mainstream=D, продавцы=E).
9. > [!warning] Red flags — industry COI / small-N / retracted-рядом.
10. > [!bug] Что оспорил критик — 1-3, ТОЛЬКО изменившее вывод (допишет fix-агент; оставь заголовок-заглушку).
11. > [!todo] Gaps.
12. ## Связанные заметки — ПУСТАЯ заглушка (wikilinks добавит скилл).
13. > [!note]- GRADE-таблица — per outcome: Outcome | Дизайн | N статей | Downgrades | GRADE.
14. > [!note]- Evidence Table TOP-8 — Paper | studyType | N | citations | GRADE | флаги; + методология (источники, snowball, dedup).
15. > [!note]- Все ссылки — по источникам, строка: [префикс·бейдж](DOI/URL) Название — одна строка RU.
16. > [!note]- Disclaimer — GRADE по абстрактам — ограничение; titleMatch-верификация; не выдавать GRADE авторитетнее, чем есть.

ПРАВИЛА:
- Язык: ${LANG === 'en' ? 'английский' : 'русский'}. Цитаты переводи; оригинал не дублируй.
- Ссылки ТОЛЬКО одинарные скобки: [pm1·HIGH](url). ❌ НЕ [[pm1]](url). Без wikilinks в body/frontmatter.
- DOI ТОЛЬКО из данных. Отозванные — не в выводы. Unverified — не в Evidence Table без пометки.
- Видимая зона (до первого [!note]-) ≤140 строк.

СОХРАНЕНИЕ: через Write сохрани draft в ${WORK_DIR}/report.md (НЕ в vault — запишет скилл).
Верни по схеме SYNTH: reportPath="${WORK_DIR}/report.md", queryRu, mainConclusion, evidenceStrengthMax, gradeMax, retractedExcluded, relatedCandidates (3-6 ключевых слов), gaps, keyDois (DOI ключевых статей выводов — для recheck критиком).
НЕ спавни субагентов, читай только файлы в ${WORK_DIR} и указанные референсы.`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Adversarial — независимый критик (не редактирует отчёт)
// ═══════════════════════════════════════════════════════════════════
function adversarialPrompt(reportPath, keyDois) {
  return `Ты — независимый критик-верификатор научного отчёта. НЕ соглашайся с выводами — атакуй их. Ты НЕ редактируешь отчёт, только формируешь таблицу правок для fix-агента.

ОТЧЁТ (Read): ${reportPath}
ПРОТОКОЛ (Read и следуй 7 шагам): ${PROTO('adversarial-review-protocol.md')}
PubPeer-протокол: ${SKILL_DIR}/references/pubpeer-check.md

KEY DOIs для retraction recheck: ${JSON.stringify(keyDois)}

ИНСТРУМЕНТЫ (бюджет): S2 REST ≤13 (paper/search «contradicts OR failed to replicate OR no effect», citations), Crossref curl ≤10 (retraction recheck keyDois), Brave ≤5 (PubPeer + consensus/scite sanity). Загружай brave/firecrawl через ToolSearch.
${TOOL_NOTE}

ЗАДАЧА:
1. Контраргументы к ТОП-3 выводам (confounders, reverse causation, circular reporting).
2. Per-claim verification 3-5 ключевых claims через S2 — активно ищи CONTRASTING: CONFIRMED/CHALLENGED/OUTDATED. ВАЖНО: absence of evidence ≠ CONFIRMED.
3. Retraction recheck KEY DOIs через Crossref (update-to.type==retraction).
4. PubPeer flags top-статей: severity critical/minor/neutral/none.
5. Publication bias, bias assessment (geographic/industry/temporal/language), gaps.
6. Итоговая надёжность X/10.

Запиши полный разбор в ${WORK_DIR}/adversarial.md (НЕ в отчёт).
Верни по схеме ADVERSARIAL: reviewPath, reliabilityScore (0-10), claimVerdicts[], retractionRecheck[], pubpeerFlags[], edits[] (таблица правок: id F1.., finding, action, confidence 0-1, affectsTldr, targetSections; один finding — одна строка, без дублей; confidence<0.7 fix пропустит).
Всё на русском. НЕ спавни субагентов.`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Fix — применяет правки critic (отделён от критика намеренно)
// ═══════════════════════════════════════════════════════════════════
function fixPrompt(reportPath, edits, reliabilityScore) {
  return `Ты — fix-агент. Примени правки adversarial-критика к отчёту. НЕ генерируй новые findings — только применяй данные.

ОТЧЁТ (Read + Edit): ${reportPath}

ТАБЛИЦА ПРАВОК (единственный источник; применяй ТОЛЬКО confidence≥0.7):
${JSON.stringify(edits, null, 2)}
ИТОГОВАЯ НАДЁЖНОСТЬ от критика: ${reliabilityScore}/10

ПОРЯДОК:
1. Для каждой правки confidence≥0.7 (сверху вниз): применяй через Edit ко ВСЕМ targetSections (Что делать §N → claim+GRADE+evidence; Evidence Table → GRADE column; Red flags; Чего НЕ делать; > [!bug] — впиши 1-3 пункта, изменившие вывод). В конце изменённой строки — маркер [AR-fix].
2. Если хоть одна правка affectsTldr=true → перечитай обновлённый body и перепиши TL;DR (> [!abstract]) под актуальные GRADE/оговорки, добавь [AR-fix].
3. Обнови frontmatter: evidence_strength_max, grade_max — если максимумы изменились; retracted_excluded если менялось.
4. Заполни > [!bug] «Что оспорил критик» 1-3 пунктами (только то, что реально изменило вывод).
НЕ применяй confidence<0.7. НЕ удаляй секции целиком. НЕ трогай verified:false.

Верни по схеме FIX: applied[], skipped[] (id+причина), tldrUpdated, evidenceTableUpdated, frontmatterUpdated, reliabilityScore=${reliabilityScore}.
НЕ спавни субагентов.`
}

// ═══════════════════════════════════════════════════════════════════
// ИСПОЛНЕНИЕ
// ═══════════════════════════════════════════════════════════════════

// ── Phase Query ──
phase('Query')
log(`Query-builder: ${FRAMING}, дисциплина ${DISCIPLINE}, источников выбрано ${SELECTED.length}`)
const plan = await agent(queryPrompt(), w({ label: 'query', phase: 'Query', schema: SEARCH_PLAN }))
const planSkip = new Set((plan && plan.skip) || [])
const runSources = SELECTED.filter(s => !planSkip.has(s))
log(`План готов. Дисциплина: ${plan?.discipline}. К поиску: ${runSources.join(', ')}${planSkip.size ? ` (skip: ${[...planSkip].join(', ')})` : ''}`)

// ── Phase Fan-out (barrier: snowball требует объединённый seed-set) ──
phase('Fan-out')
const searchResults = (await parallel(runSources.map(key => () =>
  agent(sourcePrompt(key, plan || {}), w({ label: key, phase: 'Fan-out', schema: SEARCH }))
))).filter(Boolean)

const sourceFiles = searchResults.map(r => r.fileWritten).filter(Boolean)
const sourcesAnswered = searchResults.filter(r => (r.papers || []).length > 0).length
const rawPapers = searchResults.flatMap(r => (r.papers || []).map(p => ({ ...p, _src: r.prefix })))

// JS-дедуп по paperKey СРАЗУ после fan-out: 8 источников сильно пересекаются (одни статьи в
// PubMed/S2/OpenAlex/Europe PMC). Без дедупа сырой счётчик ложно трогает PAPER_CAP и душит snowball.
function dedupePapers(list) {
  const byKey = new Map(); const out = []
  for (const p of list) {
    const k = paperKey(p).toLowerCase()
    if (!k) { out.push({ ...p, _srcs: [p._src] }); continue }
    const prev = byKey.get(k)
    if (!prev) { const np = { ...p, _srcs: [p._src] }; byKey.set(k, np); out.push(np); continue }
    prev._srcs = [...new Set([...(prev._srcs || []), p._src])]
    for (const f of ['doi', 'pmid', 'externalId', 'year', 'sampleN', 'citations', 'influentialCitations', 'fwci', 'oaUrl']) {
      if (prev[f] == null && p[f] != null) prev[f] = p[f]
    }
    if (!prev.isOA && p.isOA) prev.isOA = true
  }
  return out
}
let allPapers = dedupePapers(rawPapers).slice(0, PAPER_CAP)
log(`Источников ответило: ${searchResults.length}/${runSources.length}, с результатами: ${sourcesAnswered}. Статей: ${rawPapers.length} сырых → ${allPapers.length} уникальных (cap ${PAPER_CAP}).`)

if (sourcesAnswered < MIN_SOURCES) {
  log(`Менее ${MIN_SOURCES} источников с результатами — отдаю что есть, без синтеза.`)
  return { workDir: WORK_DIR, status: 'insufficient-sources', sourcesAnswered, runSources, files: sourceFiles, searchResults, papersTotal: allPapers.length }
}

// ── Phase Snowball (dedup → ≤2 итерации hub-chasing с saturation-гейтами) ──
phase('Snowball')
const dedup = await agent(dedupPrompt(sourceFiles), w({ label: 'dedup', phase: 'Snowball', schema: SNOWBALL_DEDUP }))
const seen = new Set((dedup?.seenKeys || []).map(k => k.toLowerCase()))
// подстрахуем seenKeys ключами из allPapers (на случай, если dedup-агент вернул не всё)
for (const p of allPapers) { const k = paperKey(p); if (k) seen.add(k.toLowerCase()) }
let canonicalCount = Math.max(dedup?.canonicalCount || 0, seen.size)
let hubs = (dedup?.hubs || []).filter(h => h.externalId).slice(0, HUB_CAP)
let addedBySnowball = 0
let saturation = dedup?.saturationEstimate ?? 0

for (let iter = 0; iter < MAX_SNOWBALL_ITERS; iter++) {
  if (!hubs.length) { log(`Snowball iter ${iter}: нет hub-ов — стоп.`); break }
  if (allPapers.length >= PAPER_CAP) { log(`Snowball: достигнут PAPER_CAP=${PAPER_CAP} — стоп.`); break }
  if (budget.remaining() < SNOWBALL_BUDGET_FLOOR) { log(`Snowball: бюджет < ${SNOWBALL_BUDGET_FLOOR} — стоп, к синтезу.`); break }

  const seenArr = [...seen]
  const chased = (await parallel(hubs.map(h => () =>
    agent(chasePrompt(h, seenArr), w({ label: `chase:${h.externalId}`.slice(0, 40), phase: 'Snowball', schema: SNOWBALL_RESULT }))
  ))).filter(Boolean)

  // JS-дедуп новых статей против seen + между hub-ами
  const fresh = []
  for (const r of chased) for (const p of (r.addedPapers || [])) {
    const k = paperKey(p).toLowerCase()
    if (!k || seen.has(k)) continue
    seen.add(k); fresh.push({ ...p, _src: p.prefix || 'sn' }); if (allPapers.length + fresh.length >= PAPER_CAP) break
  }
  const newUnique = fresh.length
  allPapers = allPapers.concat(fresh).slice(0, PAPER_CAP)
  addedBySnowball += newUnique
  const ratio = canonicalCount > 0 ? newUnique / canonicalCount : 0
  canonicalCount += newUnique
  saturation = Math.min(1, saturation + (1 - saturation) * Math.max(0, 1 - ratio))
  log(`Snowball iter ${iter}: +${newUnique} новых (ratio ${ratio.toFixed(2)}), всего ${allPapers.length}, saturation≈${saturation.toFixed(2)}`)

  if (ratio < SATURATION_THRESHOLD) { log(`Snowball: насыщение (ratio<${SATURATION_THRESHOLD}) — стоп.`); break }
  // hubs для следующей итерации: топ свежих статей с externalId по цитированиям (JS, без агента)
  hubs = fresh.filter(p => p.externalId).sort((a, b) => (b.citations || 0) - (a.citations || 0)).slice(0, HUB_CAP)
    .map(p => ({ externalId: p.externalId, api: /^W\d/i.test(p.externalId) ? 'openalex' : 's2', title: p.title, reason: 'snowball frontier' }))
}
log(`Snowball завершён: +${addedBySnowball} статей, корпус ${allPapers.length}, saturation≈${saturation.toFixed(2)}`)

// ── Phase Enrich (pipeline по батчам DOI: Crossref+Unpaywall, затем fulltext top-OA) ──
phase('Enrich')
const allDois = [...new Set(allPapers.map(p => normDoi(p.doi)).filter(Boolean))]
const doiBatches = chunk(allDois, ENRICH_BATCH)
log(`Enrich: ${allDois.length} уникальных DOI → ${doiBatches.length} батчей по ≤${ENRICH_BATCH}.`)

let enrichItems = []
if (doiBatches.length) {
  const enrichBatches = (await pipeline(
    doiBatches.map((b, i) => ({ dois: b, idx: i })),
    b => agent(enrichPrompt(b.dois, b.idx), w({ label: `enrich:${b.idx}`, phase: 'Enrich', schema: ENRICH_BATCH_SCHEMA })),
  )).filter(Boolean)
  enrichItems = enrichBatches.flatMap(b => b.items || [])
}
const retractedCount = enrichItems.filter(e => e.isRetracted).length
const unverifiedCount = enrichItems.filter(e => e.crossrefVerified && !e.titleMatch).length
log(`Enrich: проверено ${enrichItems.length} DOI — retracted=${retractedCount}, unverified(titleMatch=false)=${unverifiedCount}.`)

// fulltext top-OA (budget-gated): titleMatch=true, не retracted, isOA
let fulltextResults = []
if (budget.remaining() >= FULLTEXT_BUDGET_FLOOR) {
  const enrichByDoi = new Map(enrichItems.map(e => [e.doi, e]))
  const oaCandidates = allPapers
    .map(p => ({ p, e: enrichByDoi.get(normDoi(p.doi)) }))
    .filter(({ p, e }) => (p.isOA || (e && e.isOA)) && (!e || (!e.isRetracted && e.titleMatch !== false)) && normDoi(p.doi))
    .sort((a, b) => (b.p.citations || 0) - (a.p.citations || 0))
  const seenOa = new Set(); const topOa = []
  for (const { p, e } of oaCandidates) { const k = normDoi(p.doi); if (seenOa.has(k)) continue; seenOa.add(k); topOa.push({ ...p, oaUrl: p.oaUrl || (e && e.oaPdfUrl) || null }); if (topOa.length >= FULLTEXT_CAP) break }
  if (topOa.length) {
    log(`Fulltext: тяну summary для ${topOa.length} top-OA статей.`)
    fulltextResults = (await parallel(topOa.map(p => () =>
      agent(fulltextPrompt(p), w({ label: `fulltext:${(p.doi || '').slice(0, 24)}`, phase: 'Enrich', schema: FULLTEXT_SCHEMA }))
    ))).filter(Boolean)
  }
} else {
  log(`Fulltext пропущен: бюджет < ${FULLTEXT_BUDGET_FLOOR}.`)
}
const fulltextFiles = fulltextResults.map(r => r.fileWritten).filter(Boolean)

// ── Phase Synthesize ──
phase('Synthesize')
const enrichFiles = doiBatches.map((_, i) => `${WORK_DIR}/enrich_${i}.md`)
const synthFiles = [...sourceFiles, `${WORK_DIR}/_seed.md`, ...enrichFiles, ...fulltextFiles]
const synth = await agent(synthPrompt(synthFiles, enrichItems, allPapers.length, addedBySnowball), w({ label: 'synth', phase: 'Synthesize', schema: SYNTH }))
const reportPath = synth?.reportPath || `${WORK_DIR}/report.md`
log(`Синтез готов: ${reportPath}. Evidence=${synth?.evidenceStrengthMax}, GRADE_max=${synth?.gradeMax}.`)

// ── Phase Adversarial ──
phase('Adversarial')
const adversarial = await agent(adversarialPrompt(reportPath, synth?.keyDois || []), w({ label: 'adversarial', phase: 'Adversarial', schema: ADVERSARIAL }))
const edits = (adversarial?.edits || [])
log(`Критик: надёжность ${adversarial?.reliabilityScore}/10, правок предложено ${edits.length}.`)

// ── Phase Fix ──
phase('Fix')
const actionable = edits.filter(e => (e.confidence || 0) >= 0.7)
let fix = null
if (actionable.length) {
  fix = await agent(fixPrompt(reportPath, edits, adversarial?.reliabilityScore ?? 0), w({ label: 'fix', phase: 'Fix', schema: FIX }))
  log(`Fix: применено ${fix?.applied?.length || 0}/${actionable.length}, TL;DR обновлён: ${fix?.tldrUpdated}.`)
} else {
  log('Fix: actionable-правок (confidence≥0.7) нет — пропускаю.')
}

// ── Return-контракт ──
return {
  workDir: WORK_DIR,
  status: 'ok',
  sourcesAnswered,
  runSources,
  files: synthFiles,
  papersTotal: allPapers.length,
  addedBySnowball,
  saturation,
  enrich: { checked: enrichItems.length, retracted: retractedCount, unverified: unverifiedCount },
  reportPath,
  queryRu: synth?.queryRu || QUERY_RU,
  relatedCandidates: synth?.relatedCandidates || [],
  retractedExcluded: synth?.retractedExcluded || [],
  synthMeta: {
    mainConclusion: synth?.mainConclusion,
    evidenceStrengthMax: synth?.evidenceStrengthMax,
    gradeMax: synth?.gradeMax,
    gaps: synth?.gaps || [],
    reliabilityScore: (fix && fix.reliabilityScore) ?? adversarial?.reliabilityScore ?? null,
    adversarial: { reliabilityScore: adversarial?.reliabilityScore, editsProposed: edits.length, editsApplied: fix?.applied?.length || 0 },
  },
}
