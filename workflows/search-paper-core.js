export const meta = {
  name: 'search-paper-core',
  description: 'Ядро search-paper: query-builder → fan-out по научным источникам → citation snowballing → Crossref/Unpaywall enrich (retraction + anti-hallucination) → GRADE-синтез → adversarial critic → fix. Vault-контракт — в скилле.',
  phases: [
    { title: 'Query', detail: 'PICO/PECO → блоки синонимов → готовые строки запросов per-source' },
    { title: 'Fan-out', detail: 'до 10 источников параллельно (PubMed/Europe PMC/S2/OpenAlex/arXiv/Cochrane/web-experts/Epistemonikos/ClinicalTrials/CORE)' },
    { title: 'Snowball', detail: 'dedup → ≤6 hubs → forward/backward citation chasing до насыщения (≤2 итераций, cap 240)' },
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
const DATE = A.date || 'DRYRUN-DATE'
const WORK_DIR = A.workDir || '.search-paper/dryrun'
// ${CLAUDE_PLUGIN_ROOT} в JS НЕ подставляется — скилл передаёт его значением.
const PLUGIN_ROOT = A.pluginRoot || '.'
const VAULT_PATH = A.vaultPath || ''

// Воркер: пиннинг Opus 5 + effort high через субагента researcher-opus (как в full-research-core).
const WORKER_OPTS = A.workerOpts || { agentType: 'jadlis-science-research:researcher-opus' }
const w = extra => Object.assign({}, WORKER_OPTS, extra)

// Синтез (synth) — единственная роль с реальным Fable-преимуществом (сборка отчёта
// из большого контекста). Идёт обычным субагентом: headless-мост существовал только ради
// обхода собственной CLAUDE_CODE_SUBAGENT_MODEL_FORCE, снятой 07.09.2026. Агенты synth-*
// пиннят модель, effort high и allow-лист инструментов (у agent() нет опции allowedTools).
// Имя аргумента остаётся `fableBridge` — один словарь на все восемь воркфлоу.
const FABLE_SYNTH = A.fableBridge !== false
const SYNTH_AGENT = FABLE_SYNTH ? 'jadlis-science-research:synth-fable' : 'jadlis-science-research:synth-opus'
// ai_model отчёта печатается по тому, что реально исполнилось, а не по догадке вызывающего.
const AI_MODEL = FABLE_SYNTH ? 'claude-fable-5-1' : 'claude-opus-5'
const AI_MODEL_RETRY = 'claude-opus-5'


// ── Константы always-deep (saturation/cap/budget гейты вместо tiered-режима) ──
const MIN_SOURCES = 2          // <2 источников → insufficient-sources, скилл не пишет в vault
// Капы переопределяются аргументами — эталонный замер recall гоняет старые и новые значения
// на одном коде. Замер 21.09.2026 по 7 прогонам: 8 источников × TOP-20 = ~160 сырых → 110–135
// уникальных (пересечение баз ~25%), то есть потолок 120 съедал fan-out целиком и оставлял
// snowball'у 0–10 мест. Связывал лимит на источник, а не пересечение баз.
const capArg = (v, dflt, min, max) => Number.isFinite(+v) && +v >= min ? Math.min(Math.floor(+v), max) : dflt
const PER_SOURCE_TOP = capArg(A.perSourceTop, 30, 5, 100)   // результатов с одного источника
const PAPER_CAP = capArg(A.paperCap, 240, 20, 600)          // жёсткий потолок корпуса (защита snowball от взрыва)
const HUB_CAP = 6              // ≤6 hub-ов на итерацию snowball
const MAX_SNOWBALL_ITERS = 2
const SATURATION_THRESHOLD = 0.10  // стоп если newUnique/canonical < 0.10
const ENRICH_BATCH = 25        // DOI на один Crossref-батч (polite pool 10 RPS → секунды)
const FULLTEXT_CAP = capArg(A.fulltextCap, 10, 0, 30)       // top-OA статей под fulltext-summary
// Пороги бюджета подняты вместе с корпусом: после snowball впереди вдвое больше enrich-батчей
// и вдвое больший вход синтеза.
const SNOWBALL_BUDGET_FLOOR = 120_000  // не начинать итерацию snowball, если меньше осталось
const FULLTEXT_BUDGET_FLOOR = 80_000   // не тянуть fulltext, если меньше осталось
// Co-citation prefilter (scripts/cocite.py): выключается аргументом cocite:false.
const COCITE = A.cocite !== false
const COCITE_HUB_CAP = 20      // обзоров/МА корпуса, чьи списки литературы пересекаем
const COCITE_MAX = 40          // статей за шаг (агент переносит их из JSON в схему)
const REVIEW_TYPES = ['meta-analysis', 'systematic-review', 'review', 'guideline']
// corpusOnly: стоп после snowball, без enrich/синтеза/критика — дешёвый замер полноты выборки.
const CORPUS_ONLY = !!A.corpusOnly

const SKILL_DIR = `${PLUGIN_ROOT}/skills/science-research`
const PROTO = id => `${SKILL_DIR}/protocols/${id}`

// ── Реестр источников: 10 бесплатных ──
// prefix у каждого источника уникален — он же якорь ссылок в отчёте. `co` занят Cochrane,
// поэтому CORE получил `cr` (тест tests/test_sp_sources_registry.py стережёт уникальность).
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
  core:          { source: 'CORE',             prefix: 'cr', protocol: PROTO('core-protocol.md'),                file: 'core.md',          kind: 'grey' },
}

// Базовый набор: 10 бесплатных. arXiv/cochrane/epistemonikos снимаются по дисциплине.
// CORE включён для ВСЕХ дисциплин: серая литература (диссертации, отчёты, репозиторные OA-копии)
// нужна везде — и как антидот publication bias, и как запасной OA-локус для fulltext.
function defaultSources() {
  const base = ['pubmed', 'europepmc', 's2', 'openalex', 'arxiv', 'cochrane', 'webExperts', 'epistemonikos', 'clinicaltrials', 'core']
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
        core: { type: ['string', 'null'], description: 'простые ключевые слова; из операторов только AND/OR и кавычки для фразы' },
      },
      required: ['pubmed', 'europepmc', 's2', 'openalex', 'arxiv', 'cochrane', 'webExperts', 'epistemonikos', 'clinicaltrials', 'core'],
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
    doi: { type: ['string', 'null'], description: 'DOI hub-а, если он известен; null если нет. Нужен третьей ступени чейсинга — OpenCitations работает ТОЛЬКО по DOI' },
    title: { type: 'string' },
    reason: { type: 'string', description: 'почему hub: высокие citations/FWCI / meta/SR' },
  },
  required: ['externalId', 'api', 'doi', 'title', 'reason'],
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
    titleMatch: { type: 'boolean', description: 'title из Crossref совпал с заявленным (anti-hallucination). Семантика НЕ менялась: downstream-фильтры смотрят на titleMatch !== false' },
    yearMatch: { type: ['boolean', 'null'], description: 'год публикации совпал (допуск ±1 — online-first vs print). null, если года не было у статьи или в Crossref' },
    authorMatch: { type: ['boolean', 'null'], description: 'фамилия первого автора совпала (без учёта регистра и диакритики). null, если автора не было у статьи или в Crossref' },
    isRetracted: { type: 'boolean', description: 'update-to[].type == retraction' },
    retractionDate: { type: ['string', 'null'] },
    industryFunded: { type: 'boolean', description: 'funder[] содержит pharma/biotech' },
    oaStatus: { type: ['string', 'null'], enum: ['gold', 'hybrid', 'bronze', 'green', 'closed', null] },
    isOA: { type: 'boolean' },
    oaPdfUrl: { type: ['string', 'null'] },
  },
  required: ['doi', 'crossrefVerified', 'titleMatch', 'yearMatch', 'authorMatch', 'isRetracted', 'retractionDate', 'industryFunded', 'oaStatus', 'isOA', 'oaPdfUrl'],
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
const NUMBER_VERBATIM = {
  type: 'object', additionalProperties: false,
  properties: {
    field: { type: 'string', description: 'что за число: sampleN / effect size / CI / p / доза / длительность' },
    value: { type: 'string', description: 'само число со всеми единицами, как в статье' },
    quote: { type: 'string', description: 'дословный фрагмент-locator на языке оригинала, ≤300 символов, БЕЗ перевода' },
  },
  required: ['field', 'value', 'quote'],
}
const FULLTEXT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    doi: { type: 'string' },
    extracted: { type: 'boolean' },
    summary: { type: 'string', description: 'methods/N/inclusion/results/limitations/COI/RoB-signals, ≤1K токенов' },
    numbersVerbatim: { type: 'array', items: NUMBER_VERBATIM, description: 'locator-ы для чисел; чисел нет или fulltext недоступен → пустой массив' },
    fileWritten: { type: ['string', 'null'] },
  },
  required: ['doi', 'extracted', 'summary', 'numbersVerbatim', 'fileWritten'],
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
// «Unverified» = статья, привязка которой к DOI не подтвердилась Crossref'ом. Два случая:
// (1) прежний — title не сошёлся; (2) новый — title сошёлся, но год И фамилия первого автора
// оба разошлись (один разошедшийся признак не считается: ±1 год ловит допуск, автора часто нет).
// Семантика titleMatch НЕ менялась — downstream-фильтры по `titleMatch !== false` работают как были.
function isUnverifiedItem(e) { return !!e && e.crossrefVerified && (!e.titleMatch || (e.yearMatch === false && e.authorMatch === false)) }

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
   - europepmc — Boolean, КАЖДЫЙ термин с полем: \`(TITLE:x OR ABSTRACT:x) AND (TITLE:"y z" OR ABSTRACT:"y z")\`. Без полей Europe PMC ищет по полному тексту, и сортировка по цитируемости выносит наверх нерелевантное (замер 21.09.2026: 0 попаданий в TOP-50 против 12 с полями).
   - openalex — строка для \`filter=title_and_abstract.search:\` (ключевые слова и фразы в кавычках, без полевых префиксов); по той же причине НЕ для \`search=\`.
   - arxiv / cochrane / epistemonikos / clinicaltrials — нативный синтаксис каждого (прочитай соответствующий protocol при сомнении).
   - core — ПРОСТЫЕ ключевые слова EN. Разрешены ТОЛЬКО операторы \`AND\`/\`OR\` и кавычки для точной фразы: \`(omega-3 OR "fish oil") AND triglycerides\`. Никаких MeSH, полевых префиксов и вложенных скобочных конструкций. \`AND\` между концептами обязателен: пробел CORE трактует широко (18 млн попаданий против 1 312 с AND).
   - webExperts — короткая тема EN.
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

ПРОТОКОЛ: прочитай ${c.protocol} (Read) и следуй ему шаг за шагом — Primary → Fallback при ошибке. Если в протоколе есть секция «Primary: скрипт» — начни с неё и не пиши curl руками, пока скрипт работает; WORK_DIR для вывода скрипта — ${WORK_DIR}.
PLUGIN_ROOT = ${PLUGIN_ROOT}
Пути внутри протоколов и справочников записаны как {PLUGIN_ROOT}/… — подставляй вместо плейсхолдера строку выше. Литеральный \`{PLUGIN_ROOT}\` в команду не отправляй.
${TOOL_NOTE}
${NO_HALLUCINATION}

ПРАВИЛА:
1. LIMIT = ${PER_SOURCE_TOP} — подставляй это число в {LIMIT} протокола (retmax/pageSize/per_page/limit/max_results), дефолт протокола игнорируй. Источник вернул больше → оставь TOP-${PER_SOURCE_TOP} по composite(citations × recency), отметь усечение и общее число найденных (hitCount/total). Brave-каналы с собственным \`count\` в протоколе берут сколько отдаёт протокол.
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
4. Выбери ≤${HUB_CAP} hub-ов для чейсинга: топ по citations/FWCI + ВСЕ мета-анализы и systematic reviews, у которых есть externalId. Для каждого hub: externalId, api ('openalex' предпочтительнее — 100 RPS; 's2' только если нет OpenAlex id), doi, title, reason.
   **doi обязательно переноси из данных статьи**, если он там есть (нормализованный, без \`https://doi.org/\`): при отказе и OpenAlex, и S2 третья ступень чейсинга — OpenCitations — работает только по DOI. DOI в файлах нет → doi=null (НЕ выдумывай).
5. saturationEstimate (0..1): грубая оценка полноты текущего корпуса.
6. Запиши дедупленный seed-список в ${WORK_DIR}/_seed.md.

${NO_HALLUCINATION}
Верни строго по схеме SNOWBALL_DEDUP. НЕ делай сетевых вызовов — работай по файлам.`
}
// Имя файлов чейсера выводится из hub-а одинаково в промпте и в JS (synthFiles собираются без агента).
const chaseTag = hub => String(hub.externalId || hub.doi || 'hub').replace(/[^A-Za-z0-9]+/g, '_').slice(0, 40)
function chasePrompt(hub, seenKeys) {
  const hubArg = /^W\d+$/i.test(hub.externalId || '') ? hub.externalId : (hub.doi || hub.externalId)
  const tag = chaseTag(hub)
  const seenDois = seenKeys.filter(k => /^10\./.test(k))
  return `Ты — citation-chasing агент (forward + backward) для snowballing. Запросы к API, разбор ответов и дедуп делает скрипт; твоя работа — ТОЛЬКО оценить релевантность кандидатов.

HUB: "${hub.title}" — externalId=${hub.externalId}, DOI=${hub.doi || 'нет'}
ЗАПРОС (релевантность): ${QUERY_EN}

${TOOL_NOTE}
${NO_HALLUCINATION}

ШАГИ (уложись в 4–6 ходов, без ручных curl, пока скрипт работает):
1. Через Write сохрани в ${WORK_DIR}/_seen_${tag}.txt уже известные DOI, по одному в строке:
${seenDois.slice(0, 600).join('\n') || '(пусто)'}
2. Одной Bash-командой:
   \`eval "$(bash "${PLUGIN_ROOT}/scripts/secret.sh" --export OPENALEX_API_KEY CROSSREF_MAILTO)"; python3 "${PLUGIN_ROOT}/scripts/chase.py" --hub "${hubArg}"${hub.doi ? ` --doi "${hub.doi}"` : ''} --terms "${CHASE_TERMS}" --seen "${WORK_DIR}/_seen_${tag}.txt" --max 80 --out "${WORK_DIR}/_chase_${tag}.json"\`
   Скрипт сам идёт OpenAlex → (при отказе и наличии DOI) OpenCitations с гидрацией метаданных. В stdout — сводка: apiUsed, forwardTotal, backwardTotal, candidates, kept, note.
3. Прочитай ${WORK_DIR}/_chase_${tag}.json (Read). Кандидаты уже НОВЫЕ (виденные выброшены) и отсортированы по совпадению с терминами темы (termHits), затем по цитируемости; у каждого есть abstractHead.
4. Отбери до 25 РЕЛЕВАНТНЫХ запросу: приоритет — мета-анализы, систематические обзоры, РКИ, затем высоко-цитируемые первичные исследования; свежие работы (direction=forward, последние 3 года) не отбрасывай из-за нулевых цитирований. Нерелевантное по теме — выбрасывай, даже при высоком termHits.
5. Перенеси отобранное в addedPapers по схеме PAPER: prefix "[sn1]"…; title, doi, pmid, externalId, year, citations, fwci, isOA, oaUrl — как в файле (нет → null); influentialCitations=null; sampleN — только если число есть в abstractHead, иначе null; studyType — по type, заголовку и abstractHead (неясно → "other"); contrib ≤30 слов по abstractHead (нет аннотации → "аннотация недоступна; {direction} от hub-а"); qualitySignals — что видно из аннотации, плюс "retracted-flag" при isRetracted=true.

6. Через Write сохрани отобранное в ${WORK_DIR}/snowball_${tag}.md — этот файл читает синтезатор, без него добранные статьи доходят до отчёта голыми DOI. Формат как у источников: заголовок «Snowball от hub-а: {title}», затем по статье — \`### [snN] {title}\`, строка метаданных (DOI · PMID · Year · Type · Citations · OA · direction) и **Contrib:**. addedPapers пуст → файл не пиши.

ЕСЛИ СКРИПТ ЗАВЕРШИЛСЯ С КОДОМ 2 (ни один API не отдал hub):
- Одна ручная попытка через Semantic Scholar: прочитай ${PROTO('s2-protocol.md')}, используй /citations и /references (batch-endpoint), ключ \`\${SEMANTIC_SCHOLAR_API_KEY}\` через \`secret.sh --export\`. Оставь только новые (нет в файле из шага 1) и релевантные, до 25. Получилось — apiUsed="s2", note начни с "script-fail→s2".
- S2 тоже отказал → graceful skip: addedPapers=[], note начни с "chase-skip".

Верни строго по схеме SNOWBALL_RESULT: hubId="${hub.externalId}", apiUsed (из сводки скрипта: "openalex" | "opencitations"; либо "s2"), addedPapers[] (только новые), note = сводка скрипта одной строкой + сколько отобрал из скольких.`
}

// Co-citation: отбор делает скрипт, агент только запускает его и переносит JSON в схему.
function cocitePrompt(hubIds, seenDois, room) {
  return `Ты — исполнитель детерминированного шага co-citation. Отбор статей делает скрипт, НЕ ты: ничего не добавляй от себя и ничего не выбрасывай.

${TOOL_NOTE}
${NO_HALLUCINATION}

ШАГИ:
1. Через Write сохрани в ${WORK_DIR}/_cocite_seen.txt уже известные DOI, по одному в строке:
${seenDois.slice(0, 600).join('\n') || '(пусто)'}
2. Запусти одной Bash-командой:
   \`eval "$(bash "${PLUGIN_ROOT}/scripts/secret.sh" --export OPENALEX_API_KEY)"; python3 "${PLUGIN_ROOT}/scripts/cocite.py" --hubs "${hubIds.join(',')}" --min 2 --max ${room} --seen "${WORK_DIR}/_cocite_seen.txt" --out "${WORK_DIR}/_cocite.json"\`
   В stdout придёт сводка: hubsResolved, hubsFailed, refsTotal, sharedTotal, kept, remainingUsd.
3. Прочитай ${WORK_DIR}/_cocite.json (Read) и перенеси КАЖДЫЙ элемент papers[] в addedPapers по схеме PAPER, без отбора:
   prefix "[cc1]", "[cc2]"… по порядку файла; title, doi, pmid, externalId, year, citations, fwci, isOA, oaUrl — как в файле (нет значения → null);
   influentialCitations=null; sampleN=null; studyType — по полю type и заголовку (review → "review"/"systematic-review"/"meta-analysis" по заголовку, иначе "other", не гадай);
   contrib = "общая ссылка {citedByHubs} обзоров корпуса"; qualitySignals = ["co-cited:{citedByHubs}"] плюс "retracted-flag" если isRetracted=true.
4. Через Write сохрани человекочитаемый список в ${WORK_DIR}/cocite.md (таблица: prefix | citedByHubs | year | citations | title | doi) и строку сводки из stdout.
5. Скрипт упал или kept=0 → addedPapers=[], note начни с "cocite-skip" и приведи причину (stderr).

Верни строго по схеме SNOWBALL_RESULT: hubId="cocite", apiUsed="openalex", addedPapers[], note = сводка stdout одной строкой.`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Enrich — Crossref/Unpaywall батч + fulltext
// ═══════════════════════════════════════════════════════════════════
function enrichPrompt(dois, idx, topTier) {
  const top = dois.filter(d => topTier.has(d))
  return `Ты — enrichment-агент батча #${idx}. Проверь DOI через Crossref + Unpaywall.

DOI батча (${dois.length}):
${dois.map(d => `- ${d}${topTier.has(d) ? '  [ТОП-ТИР]' : ''}`).join('\n')}

Для каждого DOI через Bash curl (ПОСЛЕДОВАТЕЛЬНО, polite pool):
1. Crossref: \`curl -s "https://api.crossref.org/works/{DOI}?mailto=\${CROSSREF_MAILTO}" -H "User-Agent: search-paper/1.0 (mailto:\${CROSSREF_MAILTO})"\`
   - crossrefVerified: DOI резолвится (HTTP 200, message есть).
   - isRetracted: ИСТИНА, если сработал ЛЮБОЙ сигнал (проверяй ВСЕ три ниже — одного update-to НЕДОСТАТОЧНО; четвёртый сигнал — в пункте 3, только для топ-тира):
     (a) \`message.updated-by[]\` содержит элемент с \`type == "retraction"\` — ОСНОВНОЙ сигнал отозванной статьи (ставит retractionDate = его updated.date-parts);
     (b) title начинается с "RETRACTED", "Retracted:", "WITHDRAWN" — вторичный сигнал (напр. Wakefield 1998: title "RETRACTED: …", updated-by[].type=="retraction");
     (c) \`message.update-to[].type == "retraction"\` — означает, что САМ этот DOI является уведомлением об отзыве (тоже исключаем из доказательной базы).
     Пример: DOI 10.1016/S0140-6736(97)11096-0 → isRetracted=true (через updated-by + title-префикс).
   - industryFunded: \`message.funder[].name\` содержит pharma/biotech (Pfizer, Novartis, Bayer, Merck, GSK, Roche, AbbVie, Sanofi, биотех-вендоры и т.п.).
   - ANTI-HALLUCINATION — сверка ТРЁХ полей с тем, что заявил source-агент:
     • titleMatch: title из Crossref (\`message.title[0]\`) совпадает с заявленным — с точностью до регистра, пунктуации и пробелов? Расходится по смыслу или DOI не резолвится → titleMatch=false (статья «unverified»).
     • yearMatch: год Crossref (\`message.issued.date-parts[0][0]\`, при отсутствии — \`message.published.date-parts[0][0]\`) против заявленного года. **Допуск ±1** — online-first и печатный номер законно расходятся на год. Разница ≥2 → false. Года нет у статьи ИЛИ нет в Crossref → null (не false).
     • authorMatch: фамилия ПЕРВОГО автора (\`message.author[0].family\`) против заявленного первого автора. Сравнивай без учёта регистра и диакритики (Müller = Muller = MULLER, Łopez = Lopez); дефисные и двойные фамилии — совпадение по любой части. Автора нет у статьи ИЛИ нет в Crossref → null (не false).
   Rate limit: 10 RPS polite (gap ~100ms). HTTP 429 → backoff 1s/2s/4s, max 3.
2. Unpaywall: \`curl -s "https://api.unpaywall.org/v2/{DOI}?email=\${UNPAYWALL_EMAIL}"\`
   - isOA, oaStatus (gold/hybrid/bronze/green/closed), oaPdfUrl = best_oa_location.url_for_pdf.
${top.length ? `3. ЧЕТВЁРТЫЙ СИГНАЛ РЕТРАКЦИИ — ТОЛЬКО для ${top.length} DOI, помеченных [ТОП-ТИР] выше. Остальные DOI батча этим запросом НЕ проверяй.
   \`curl -s "https://api.crossref.org/works?filter=updates:{DOI},update-type:retraction&rows=1&mailto=\${CROSSREF_MAILTO}" -H "User-Agent: search-paper/1.0 (mailto:\${CROSSREF_MAILTO})"\`
   - \`message.total-results > 0\` → существует уведомление об отзыве, указывающее НА ЭТОТ DOI → isRetracted=true, даже если в самой записи статьи нет \`updated-by\`. retractionDate = \`message.items[0].update-to[0].updated.date-parts\`.
   - \`total-results == 0\` → сигнал чист; на три предыдущих сигнала это никак не влияет.
   - Проверено 21.09.2026 на DOI 10.1177/1758835919874651: total-results=1, уведомление 10.1177/17588359211061903, \`update-to[0].source = "retraction-watch"\`.
   - ЭТО LIST-ЗАПРОС: polite pool даёт 3 RPS, а не 10 → gap ≥350 мс, строго последовательно. Ради этого лимита сигнал и ограничен топ-тиром: гонять его по всему батчу значило бы удвоить число запросов при том же улове.
` : `3. ЧЕТВЁРТЫЙ СИГНАЛ РЕТРАКЦИИ (Crossref \`filter=updates:…\`) в этом батче не запускается: DOI из топ-тира здесь нет.
`}
Запиши дамп в ${WORK_DIR}/enrich_${idx}.md.
Верни строго по схеме ENRICH_BATCH_SCHEMA: batchIndex=${idx}, items[] (по одному ENRICH_ITEM на DOI), fileWritten.
${NO_HALLUCINATION} НЕ выдумывай поля — если curl не вернул, ставь false/null.`
}
function fulltextPrompt(p) {
  return `Ты — fulltext-extraction агент. Извлеки структурированное резюме одной OA-статьи.

СТАТЬЯ: "${p.title}"
DOI: ${p.doi}
OA PDF/URL: ${p.oaUrl || '(возьми из enrich-файлов в ' + WORK_DIR + ')'}

PLUGIN_ROOT = ${PLUGIN_ROOT}
Пути записаны как {PLUGIN_ROOT}/… — подставляй вместо плейсхолдера строку выше. Литеральный \`{PLUGIN_ROOT}\` в команду не отправляй.

ЗАДАЧА:
1. Получи fulltext — маршрут по типу ссылки:
   - **PDF** (URL оканчивается на .pdf, arXiv /pdf/, любой OA-PDF-locus): ТОЛЬКО \`bash ${PLUGIN_ROOT}/scripts/pdf-fetch.sh "<url>"\` через Bash → скрипт печатает путь к текстовому файлу → прочитай его через Read. Это 0 кредитов. PDF через firecrawl ЗАПРЕЩЁН — PreToolUse-хук плагина (block-pdf-firecrawl.py) его deny-ит, а постраничный парсинг сжигает по кредиту на страницу.
     \`exit 2\` (PDF_UNREACHABLE/PDF_EMPTY: JS-gate, скан, paywall) → лестница локусов:
     a) другой OA-locus из enrich-файлов (Unpaywall \`oa_locations[]\`) → снова pdf-fetch.sh;
     b) и он не открылся → **CORE**: у репозиториев часто лежит открытая копия там, где Unpaywall пусто. Один запрос по DOI:
        \`\`\`bash
        eval "$(bash ${PLUGIN_ROOT}/scripts/secret.sh --export CORE_API_KEY)"
        curl -sL "https://api.core.ac.uk/v3/search/works/?q=doi%3A%22${(p.doi || '').replace(/"/g, '')}%22&limit=1" -H "Authorization: Bearer \${CORE_API_KEY}" | jq -r '.results[0].downloadUrl // empty'
        \`\`\`
        Слэш в конце \`/works/\` обязателен, \`-L\` обязателен (иначе 301 и пустота). Не читай ответ целиком — \`fullText\` в выдаче CORE весит 80–180 тыс. символов; бери только \`downloadUrl\` через jq.
        Непустой \`downloadUrl\` → ОДИН повторный \`bash ${PLUGIN_ROOT}/scripts/pdf-fetch.sh "<downloadUrl>"\`.
     c) пусто / ключа нет / снова exit 2 → extracted=false, дальше не пробуй.
   - **HTML-страница** (журнальная страница, PMC, блог): \`defuddle parse "{url}" --md\` через Bash, при неудаче — firecrawl_scrape (загрузи через ToolSearch). waitFor 5000 только для динамики.
2. Извлеки ТОЛЬКО structured summary (≤1K токенов): methods (1-2 предл.), sample_size (N + популяция), inclusion_criteria (2-3), results_primary (1 абзац), limitations (3), conflict_of_interest (дословно), rob_signals (blinding/ITT/allocation concealment/pre-registration).
3. numbersVerbatim[]: для КАЖДОГО числа, которое может попасть в отчёт (N, эффект, CI, p, доза, длительность), верни объект {field, value, quote}, где quote — ДОСЛОВНЫЙ фрагмент из статьи на языке оригинала (≤300 символов, без перевода и без пересказа), содержащий это число. Числа без дословного locator не возвращай. Чисел нет или fulltext недоступен → пустой массив [].
4. НЕ возвращай raw PDF text.

Запиши в ${WORK_DIR}/fulltext_${(p.doi || p.title).replace(/[^a-z0-9]/gi, '').slice(0, 24)}.md (в файл включи и блок «Числа (verbatim)» с locator-ами).
${TOOL_NOTE}
Верни по схеме FULLTEXT_SCHEMA: doi="${p.doi}", extracted (bool), summary, numbersVerbatim[], fileWritten. Если fulltext недоступен — extracted=false, summary="", numbersVerbatim=[].`
}

// ═══════════════════════════════════════════════════════════════════
// Phase Synthesize — GRADE per-outcome decision-first draft
// ═══════════════════════════════════════════════════════════════════
function synthPrompt(allFiles, enrichItems, papersTotal, addedBySnowball, aiModel) {
  const retracted = enrichItems.filter(e => e.isRetracted).map(e => e.doi)
  const unverified = enrichItems.filter(isUnverifiedItem).map(e => e.doi)
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
- UNVERIFIED (Crossref не подтвердил привязку статьи к DOI: либо titleMatch=false, либо titleMatch=true при разошедшихся ОДНОВРЕМЕННО годе и фамилии первого автора → НЕ в Evidence Table без явной пометки «не верифицировано»; в выводы такие статьи не берём): ${JSON.stringify(unverified)}

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
ai_model: "${aiModel}"
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
- ЧИСЛА ТОЛЬКО С LOCATOR: любое число в отчёте (N, размер эффекта, CI, p, доза, длительность) обязано иметь дословный locator — запись в numbersVerbatim[] соответствующего fulltext-файла (поля field/value/quote). Нет quote — числа в отчёте нет: пиши качественно («снижение умеренное»), без цифры. Цифры из абстрактов допустимы только если абстракт процитирован дословно в файле источника.
- Видимая зона (до первого [!note]-) ≤140 строк.

СОХРАНЕНИЕ: через Write сохрани draft в ${WORK_DIR}/draft.md (НЕ в vault — запишет скилл).
Верни по схеме SYNTH: reportPath="${WORK_DIR}/draft.md", queryRu, mainConclusion, evidenceStrengthMax, gradeMax, retractedExcluded, relatedCandidates (3-6 ключевых слов), gaps, keyDois (DOI ключевых статей выводов — для recheck критиком).
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

ИНСТРУМЕНТЫ (бюджет): S2 REST ≤13 (paper/search «contradicts OR failed to replicate OR no effect», citations), Crossref curl ≤10 (retraction recheck keyDois), Brave ≤5 (PubPeer + sanity-проверка согласия экспертных источников). Загружай brave/firecrawl через ToolSearch.
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
const uniquePapersRaw = dedupePapers(rawPapers)
// Телеметрия капов: усечение fan-out'а по PAPER_CAP фиксируем отдельно от усечения snowball'а.
// Записи реестра испытаний и страницы экспертных сайтов — не статьи: у них нет DOI/цитирований, snowball и
// enrich их не трогают. Под потолок они не идут, иначе съедают места добора по цитированиям — самой точной
// части корпуса (замер 21.09.2026: точность fan-out 11%, cocite 22%, chase 30–35%; ct+w занимали 53 места из 240).
const SIDE_SRC = new Set([ALL_SOURCES.clinicaltrials.prefix, ALL_SOURCES.webExperts.prefix])
const isSide = p => (p._srcs || [p._src]).every(x => SIDE_SRC.has(x))
const sidePapers = uniquePapersRaw.filter(isSide)
const mainPapersRaw = uniquePapersRaw.filter(p => !isSide(p))
const capHitFanout = mainPapersRaw.length > PAPER_CAP
let allPapers = mainPapersRaw.slice(0, PAPER_CAP)
let capHitSnowball = false
let stoppedBy = 'noHubs'
log(`Дедуп fan-out: ${rawPapers.length} rawPapers → ${uniquePapersRaw.length} unique${capHitFanout ? ` (усечено до PAPER_CAP=${PAPER_CAP})` : ''}.`)
log(`Источников ответило: ${searchResults.length}/${runSources.length}, с результатами: ${sourcesAnswered}. Статей: ${rawPapers.length} сырых → ${allPapers.length} уникальных (cap ${PAPER_CAP}).`)

if (sourcesAnswered < MIN_SOURCES) {
  log(`Менее ${MIN_SOURCES} источников с результатами — отдаю что есть, без синтеза.`)
  return { workDir: WORK_DIR, status: 'insufficient-sources', sourcesAnswered, runSources, files: sourceFiles, searchResults, papersTotal: allPapers.length }
}

// Термины темы для scripts/chase.py: метки и синонимы концептов из плана запросов, иначе слова QUERY_EN.
// Запятая — разделитель аргумента, кавычки ломают shell-строку — вычищаем оба.
const CHASE_STOP = new Set(['with', 'from', 'that', 'this', 'their', 'which', 'adults', 'adult', 'effect', 'effects', 'efficacy', 'relative', 'combination', 'versus', 'among', 'between'])
const CHASE_TERMS = (() => {
  const fromPlan = ((plan && plan.concepts) || []).flatMap(c => [c.label, ...(c.synonyms || [])])
  const raw = fromPlan.length ? fromPlan : QUERY_EN.split(/[^A-Za-z0-9-]+/).filter(t => t.length > 3 && !CHASE_STOP.has(t.toLowerCase()))
  return [...new Set(raw.map(t => String(t || '').toLowerCase().replace(/[",`$\\]/g, ' ').trim()).filter(t => t.length > 2))].slice(0, 24).join(',')
})()

// ── Phase Snowball (dedup → ≤2 итерации hub-chasing с saturation-гейтами) ──
phase('Snowball')
const dedup = await agent(dedupPrompt(sourceFiles), w({ label: 'dedup', phase: 'Snowball', schema: SNOWBALL_DEDUP }))
const seen = new Set((dedup?.seenKeys || []).map(k => k.toLowerCase()))
// подстрахуем seenKeys ключами из allPapers (на случай, если dedup-агент вернул не всё)
for (const p of allPapers) { const k = paperKey(p); if (k) seen.add(k.toLowerCase()) }
let canonicalCount = Math.max(dedup?.canonicalCount || 0, seen.size)
// doi нормализуем здесь: агент может вернуть его в форме https://doi.org/… , а OpenCitations
// ждёт голый `doi:10.x/y`.
let hubs = (dedup?.hubs || []).filter(h => h.externalId).slice(0, HUB_CAP)
  .map(h => ({ ...h, doi: normDoi(h.doi) || null }))
let addedBySnowball = 0
let saturation = dedup?.saturationEstimate ?? 0

// ── Co-citation prefilter: детерминированный backward-добор ДО агентов-чейсеров ──
// Обзоры/мета-анализы корпуса → их списки литературы → работы, на которые ссылаются ≥2 из них.
// Замер 21.09.2026 (две темы, эталон — списки литературы отложенных SR): случайная backward-ссылка
// попадает в эталон в 3–6% случаев, общая для ≥2 обзоров — в 20–40%, для ≥3 — в 46–56%.
// Один агент, один скрипт, ~1 запрос OpenAlex на обзор; чейсерам ниже остаётся forward и хвост.
const snowballFiles = []   // дампы чейсеров для синтеза (snowball_{tag}.md)
let addedByCocite = 0
const reviewHubs = allPapers
  .filter(p => REVIEW_TYPES.includes(p.studyType) && (/^W\d+$/i.test(p.externalId || '') || normDoi(p.doi)))
  .sort((a, b) => (b.citations || 0) - (a.citations || 0))
  .slice(0, COCITE_HUB_CAP)
  .map(p => /^W\d+$/i.test(p.externalId || '') ? p.externalId : normDoi(p.doi))
if (COCITE && reviewHubs.length >= 2 && allPapers.length < PAPER_CAP) {
  const room = Math.min(COCITE_MAX, PAPER_CAP - allPapers.length)
  const co = await agent(cocitePrompt(reviewHubs, [...seen].filter(k => /^10\./.test(k)), room),
    w({ label: 'cocite', phase: 'Snowball', schema: SNOWBALL_RESULT }))
  for (const p of (co?.addedPapers || [])) {
    const k = paperKey(p).toLowerCase()
    if (!k || seen.has(k) || allPapers.length >= PAPER_CAP) continue
    seen.add(k); allPapers.push({ ...p, _src: 'cc', _srcs: ['cc'] }); addedByCocite++
  }
  canonicalCount += addedByCocite
  addedBySnowball += addedByCocite
  log(`Co-citation: ${reviewHubs.length} обзоров-hub-ов → +${addedByCocite} статей (${co?.note || 'нет note'}). Корпус ${allPapers.length}.`)
} else {
  log(`Co-citation пропущен: обзоров с id ${reviewHubs.length} (<2), либо корпус у потолка, либо cocite:false.`)
}

for (let iter = 0; iter < MAX_SNOWBALL_ITERS; iter++) {
  if (!hubs.length) { stoppedBy = 'noHubs'; log(`Snowball iter ${iter}: нет hub-ов — стоп.`); break }
  if (allPapers.length >= PAPER_CAP) { stoppedBy = 'cap'; capHitSnowball = true; log(`Snowball: достигнут PAPER_CAP=${PAPER_CAP} — стоп.`); break }
  if (budget.remaining() < SNOWBALL_BUDGET_FLOOR) { stoppedBy = 'budget'; log(`Snowball: бюджет < ${SNOWBALL_BUDGET_FLOOR} — стоп, к синтезу.`); break }
  stoppedBy = 'iters'   // перезапишется, если цикл выйдет по одному из гейтов ниже

  const seenArr = [...seen]
  const chased = (await parallel(hubs.map(h => () =>
    agent(chasePrompt(h, seenArr), w({ label: `chase:${h.externalId}`.slice(0, 40), phase: 'Snowball', schema: SNOWBALL_RESULT }))
  ))).filter(Boolean)
  for (const h of hubs) { const r = chased.find(c => c.hubId === h.externalId); if (r && (r.addedPapers || []).length) snowballFiles.push(`${WORK_DIR}/snowball_${chaseTag(h)}.md`) }

  // JS-дедуп новых статей против seen + между hub-ами
  const fresh = []
  for (const r of chased) for (const p of (r.addedPapers || [])) {
    const k = paperKey(p).toLowerCase()
    if (!k || seen.has(k)) continue
    seen.add(k); fresh.push({ ...p, _src: 'sn', _srcs: ['sn'] });   // было p.prefix: в телеметрии источников вместо 'sn' копились '[oa2]', '[oa3]'… if (allPapers.length + fresh.length >= PAPER_CAP) { capHitSnowball = true; break }
  }
  const before = allPapers.length
  allPapers = allPapers.concat(fresh).slice(0, PAPER_CAP)
  const newUnique = allPapers.length - before   // было fresh.length: счётчик завышался, когда потолок отрезал хвост
  addedBySnowball += newUnique
  const ratio = canonicalCount > 0 ? newUnique / canonicalCount : 0
  canonicalCount += newUnique
  saturation = Math.min(1, saturation + (1 - saturation) * Math.max(0, 1 - ratio))
  log(`Snowball iter ${iter}: +${newUnique} новых (ratio ${ratio.toFixed(2)}), всего ${allPapers.length}, saturation≈${saturation.toFixed(2)}`)

  if (ratio < SATURATION_THRESHOLD) { stoppedBy = 'saturation'; log(`Snowball: насыщение (ratio<${SATURATION_THRESHOLD}) — стоп.`); break }
  // hubs для следующей итерации: топ свежих статей с externalId по цитированиям (JS, без агента)
  hubs = fresh.filter(p => p.externalId).sort((a, b) => (b.citations || 0) - (a.citations || 0)).slice(0, HUB_CAP)
    // doi прокидываем всегда: без него у chase-агента нет третьей ступени (OpenCitations по DOI).
    .map(p => ({ externalId: p.externalId, api: /^W\d/i.test(p.externalId) ? 'openalex' : 's2', doi: normDoi(p.doi) || null, title: p.title, reason: 'snowball frontier' }))
}
allPapers = allPapers.concat(sidePapers)   // возвращаем побочные записи: синтезу они нужны, потолку — нет
log(`Snowball завершён: +${addedBySnowball} статей, корпус ${allPapers.length}, saturation≈${saturation.toFixed(2)}, stoppedBy=${stoppedBy}, capHitFanout=${capHitFanout}, capHitSnowball=${capHitSnowball}`)

const capStats = {
  stoppedBy,               // noHubs | cap | budget | saturation | iters
  capHitFanout,            // PAPER_CAP усёк корпус сразу после fan-out
  capHitSnowball,          // PAPER_CAP усёк добор snowball'а
  rawPapers: rawPapers.length,
  uniquePapers: uniquePapersRaw.length,
  paperCap: PAPER_CAP,
  sideRecords: sidePapers.length,   // записи реестра/экспертные страницы — вне потолка
  perSourceTop: PER_SOURCE_TOP,
  addedByCocite,           // из них co-citation-шаг (scripts/cocite.py), остальное — чейсеры
}

if (CORPUS_ONLY) {
  log('corpusOnly: корпус собран, enrich/синтез/критик пропущены.')
  return {
    workDir: WORK_DIR, status: 'corpus-only', sourcesAnswered, runSources, files: sourceFiles,
    papersTotal: allPapers.length, addedBySnowball, saturation, capStats,
    corpus: allPapers.map(p => ({ doi: normDoi(p.doi) || null, pmid: p.pmid || null, title: p.title, year: p.year || null, srcs: p._srcs || [p._src] })),
  }
}

// ── Phase Enrich (pipeline по батчам DOI: Crossref+Unpaywall, затем fulltext top-OA) ──
phase('Enrich')
const allDois = [...new Set(allPapers.map(p => normDoi(p.doi)).filter(Boolean))]
const doiBatches = chunk(allDois, ENRICH_BATCH)

// Топ-тир — для четвёртого сигнала ретракции (Crossref `filter=updates:{DOI}`). Это list-запрос:
// 3 RPS polite вместо 10, то есть по всему корпусу он удвоил бы число запросов ради единиц находок.
// Критерий: мета/SR/RCT ИЛИ верхняя треть корпуса по цитированиям.
const TOP_TIER_TYPES = new Set(['meta-analysis', 'systematic-review', 'rct'])
const citesSorted = allPapers.map(p => p.citations || 0).sort((a, b) => a - b)
const citesCut = citesSorted.length ? citesSorted[Math.floor(citesSorted.length * 2 / 3)] : 0
const topTierDois = new Set()
for (const p of allPapers) {
  const d = normDoi(p.doi)
  if (d && (TOP_TIER_TYPES.has(p.studyType) || (p.citations || 0) >= citesCut)) topTierDois.add(d)
}
log(`Enrich: ${allDois.length} уникальных DOI → ${doiBatches.length} батчей по ≤${ENRICH_BATCH}; топ-тир для 4-го сигнала ретракции: ${topTierDois.size}.`)

let enrichItems = []
if (doiBatches.length) {
  const enrichBatches = (await pipeline(
    doiBatches.map((b, i) => ({ dois: b, idx: i })),
    b => agent(enrichPrompt(b.dois, b.idx, topTierDois), w({ label: `enrich:${b.idx}`, phase: 'Enrich', schema: ENRICH_BATCH_SCHEMA })),
  )).filter(Boolean)
  enrichItems = enrichBatches.flatMap(b => b.items || [])
}
const retractedCount = enrichItems.filter(e => e.isRetracted).length
const unverified = enrichItems.filter(isUnverifiedItem)
const unverifiedCount = unverified.length
const unverifiedByMeta = unverified.filter(e => e.titleMatch).length
log(`Enrich: проверено ${enrichItems.length} DOI — retracted=${retractedCount}, unverified=${unverifiedCount} (из них titleMatch=true, но год+автор разошлись: ${unverifiedByMeta}).`)

// fulltext top-OA (budget-gated): titleMatch=true, не retracted, isOA
let fulltextResults = []
if (budget.remaining() >= FULLTEXT_BUDGET_FLOOR) {
  const enrichByDoi = new Map(enrichItems.map(e => [e.doi, e]))
  const oaCandidates = allPapers
    .map(p => ({ p, e: enrichByDoi.get(normDoi(p.doi)) }))
    // titleMatch !== false оставлено как было; isUnverifiedItem добавляет второй случай
    // (год+автор разошлись) — тянуть fulltext под чужой DOI смысла нет.
    .filter(({ p, e }) => (p.isOA || (e && e.isOA)) && (!e || (!e.isRetracted && e.titleMatch !== false && !isUnverifiedItem(e))) && normDoi(p.doi))
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
// cocite.md — единственный файл, где у co-cited статей есть заголовки и число цитирующих обзоров.
const synthFiles = [...sourceFiles, `${WORK_DIR}/_seed.md`, ...(addedByCocite ? [`${WORK_DIR}/cocite.md`] : []), ...snowballFiles, ...enrichFiles, ...fulltextFiles]
// Опции собираются явно, НЕ через w(): переданный вызывающим workerOpts.model пережил бы
// слияние и побил frontmatter агента (per-invocation модель приоритетнее).
const synthOpts = (label, agentType) => ({ label, phase: 'Synthesize', schema: SYNTH, agentType })

let synth = await agent(synthPrompt(synthFiles, enrichItems, allPapers.length, addedBySnowball, AI_MODEL),
  synthOpts(FABLE_SYNTH ? 'synth→fable' : 'synth', SYNTH_AGENT))

// Одна попытка на Opus 5 — только на Fable-ветке: при fableBridge:false первый вызов уже был
// на Opus, и повтор перезапустил бы то, что человек мог пропустить намеренно.
let synthFellBack = false
if (!synth && FABLE_SYNTH) {
  log('synth (Fable) вернул null — одна попытка на Opus 5.')
  synth = await agent(synthPrompt(synthFiles, enrichItems, allPapers.length, addedBySnowball, AI_MODEL_RETRY),
    synthOpts('synth→opus-retry', 'jadlis-science-research:synth-opus'))
  synthFellBack = true
}
// Ранний выход обязателен: без него прогон молча уходит в Adversarial и возвращает
// status:'ok' без подтверждённого отчёта — хуже падения.
if (!synth) {
  log('Синтез не удался дважды. Материалы собраны, отчёт не написан.')
  return { workDir: WORK_DIR, status: 'synthesis-failed', papersTotal: allPapers.length }
}
// draft.md, not report.md: CC 2.1.276+ blocks subagent Write to ^(REPORT|SUMMARY|FINDINGS|ANALYSIS).*\.md$
const reportPath = synth.reportPath || `${WORK_DIR}/draft.md`
const aiModelActual = (FABLE_SYNTH && !synthFellBack) ? 'claude-fable-5-1' : 'claude-opus-5'
log(`Синтез готов: ${reportPath}. Evidence=${synth?.evidenceStrengthMax}, GRADE_max=${synth?.gradeMax}, модель=${aiModelActual}.`)

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
  capStats,
  aiModelActual,
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
