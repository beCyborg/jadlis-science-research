// Unit tests for the pure helpers of search-paper-core.js. The workflow body is not a module —
// the harness cuts the block between the SP_UNITS_START/SP_UNITS_END markers and evaluates it on
// its own, so the helpers must never reach for a run constant.
// Plus one end-to-end assertion that the corpus cap really trips capHitSnowball (the check used to
// sit inside a `//` comment and never ran).
const fs = require('fs')
const path = require('path')

const P = path.join(__dirname, '..', 'workflows', 'search-paper-core.js')
const SRC = fs.readFileSync(P, 'utf8')

const block = SRC.split('// SP_UNITS_START')[1]
if (!block) { console.log('FAIL: SP_UNITS_START marker missing'); process.exit(1) }
const body = block.split('// SP_UNITS_END')[0]
const U = new Function(`${body}\nreturn { normDoi, paperKey, isUnverifiedItem, isGreyLitItem, fallbackQuery, ensureCoverage, paperSubquestions, paperScore, rankedCut, coverageCounts }`)()

let failed = 0
const ok = (name, cond, extra) => {
  console.log(`${cond ? 'ok  ' : 'FAIL'} ${name}${cond || extra === undefined ? '' : ' — ' + JSON.stringify(extra)}`)
  if (!cond) failed++
}

// ── A1: покрытие подтем ──────────────────────────────────────────────────────────────────────
const SOURCES = ['pubmed', 'europepmc', 'openalex']
{
  const plan = {
    subquestions: [
      { id: 'q1', label: 'Сон', terms: ['sleep onset'] },
      { id: 'q2', label: 'Сперма', terms: ['sperm', 'semen quality'] },
    ],
    extraQueries: [{ key: 'pubmed:q1', source: 'pubmed', subquestionId: 'q1', query: 'x' }],
    coverage: [{ subquestionId: 'q1', queryKeys: ['pubmed:main'] }],
  }
  const r = U.ensureCoverage(plan, SOURCES, 6)
  const cov = new Map(r.coverage.map(c => [c.subquestionId, c.queryKeys]))
  ok('coverage: подтема без покрытия получает запасные запросы', (cov.get('q2') || []).length === 3, cov.get('q2'))
  ok('coverage: fallback отмечен в отчёте функции', r.fallbacks.join() === 'q2', r.fallbacks)
  ok('coverage: покрытая подтема не трогается', (cov.get('q1') || []).join() === 'pubmed:main')
  ok('coverage: запасные запросы дописаны в extraQueries', r.extraQueries.length === 4, r.extraQueries.length)
  const pm = r.extraQueries.find(e => e.key === 'pubmed:fallback:q2')
  ok('coverage: запрос PubMed синтаксически осмыслен', !!pm && pm.query === '"sperm"[tiab] AND "semen quality"[tiab]', pm && pm.query)
  const em = r.extraQueries.find(e => e.key === 'europepmc:fallback:q2')
  ok('coverage: запрос Europe PMC идёт с полями', !!em && em.query.startsWith('(TITLE:"sperm" OR ABSTRACT:"sperm")'), em && em.query)
}
{
  // одна тема без подтем — поведение как раньше, ни одного лишнего запроса
  const r = U.ensureCoverage({ subquestions: [], extraQueries: [], coverage: [] }, SOURCES, 6)
  ok('coverage: тема без подтем не порождает запросов', r.extraQueries.length === 0 && r.fallbacks.length === 0)
  const r2 = U.ensureCoverage({}, SOURCES, 6)
  ok('coverage: пустой план не падает', r2.extraQueries.length === 0 && r2.coverage.length === 0)
}
{
  // cap на источник соблюдается: 8 непокрытых подтем, но не больше 6 запросов на источник
  const subqs = Array.from({ length: 8 }, (_, i) => ({ id: `q${i}`, label: `l${i}`, terms: [`term${i}`] }))
  const r = U.ensureCoverage({ subquestions: subqs, extraQueries: [], coverage: [] }, SOURCES, 6)
  const perSource = SOURCES.map(s => r.extraQueries.filter(e => e.source === s).length)
  ok('coverage: ≤6 доп. запросов на источник', perSource.every(n => n <= 6), perSource)
}

// ── A4: ранжированная обрезка ────────────────────────────────────────────────────────────────
{
  const subqs = [
    { id: 'wide', label: 'Широкая', terms: ['nicotine'] },
    { id: 'narrow', label: 'Узкая', terms: ['sperm'] },
  ]
  const corpus = []
  // 295 громких статей широкой подтемы + 5 тихих статей узкой: при обрезке по позиции узкая гибнет
  for (let i = 0; i < 295; i++) {
    corpus.push({ title: `Nicotine study ${i}`, doi: `10.1/w${i}`, year: 2020, citations: 500 + i, contrib: '' })
  }
  for (let i = 0; i < 5; i++) {
    corpus.push({ title: `Snus and sperm quality ${i}`, doi: `10.1/n${i}`, year: 2022, citations: 1, contrib: '' })
  }
  const cut = U.rankedCut(corpus, 240, subqs, 5, 2026)
  const narrow = cut.filter(p => /sperm/.test(p.title)).length
  ok('rankedCut: корпус обрезан до потолка', cut.length === 240, cut.length)
  ok('rankedCut: все 5 статей узкой подтемы выжили', narrow === 5, narrow)
  const positional = corpus.slice(0, 240).filter(p => /sperm/.test(p.title)).length
  ok('rankedCut: обрезка по позиции их теряла (контроль)', positional === 0, positional)
  ok('rankedCut: порядок исходного массива сохранён',
    cut.every((p, i, a) => i === 0 || corpus.indexOf(a[i - 1]) < corpus.indexOf(p)))
}
{
  const corpus = [{ title: 'a', citations: 1 }, { title: 'b', citations: 2 }]
  ok('rankedCut: корпус меньше потолка возвращается как есть', U.rankedCut(corpus, 240, [], 5, 2026).length === 2)
  ok('rankedCut: без подтем режет по рангу, не падает', U.rankedCut(corpus, 1, [], 5, 2026).length === 1)
  ok('rankedCut: пустой вход', U.rankedCut(null, 10, null, 5, 2026).length === 0)
}
{
  // квота не должна съесть весь потолок: 3 подтемы × 5 при потолке 6
  const subqs = [{ id: 'a', label: 'a', terms: ['alpha'] }, { id: 'b', label: 'b', terms: ['beta'] }, { id: 'c', label: 'c', terms: ['gamma'] }]
  const corpus = []
  for (const t of ['alpha', 'beta', 'gamma']) for (let i = 0; i < 10; i++) corpus.push({ title: `${t} ${i}`, citations: i })
  const cut = U.rankedCut(corpus, 6, subqs, 5, 2026)
  ok('rankedCut: квота не переполняет потолок', cut.length === 6, cut.length)
}
{
  // свежесть: статья 2025 года с 30 цитатами весит больше обзора 1998 года с 200
  const fresh = U.paperScore({ year: 2025, citations: 30 }, 2026)
  const old = U.paperScore({ year: 1998, citations: 200 }, 2026)
  ok('paperScore: свежесть учитывается', fresh > old, { fresh, old })
  ok('paperSubquestions: совпадение по contrib, не только по заголовку',
    U.paperSubquestions({ title: 'x', contrib: 'эффект на sperm count' }, [{ id: 'q', terms: ['sperm'] }]).join() === 'q')
}

// ── A6: серая литература и «исчезнувшие молча» ───────────────────────────────────────────────
{
  const greyItem = { doi: '10.1/bfr', crossrefVerified: false, greyLit: true, titleMatch: true }
  const ghost = { doi: '10.1/ghost', crossrefVerified: false, greyLit: false, titleMatch: false }
  const badTitle = { doi: '10.1/x', crossrefVerified: true, greyLit: false, titleMatch: false }
  const metaMismatch = { doi: '10.1/y', crossrefVerified: true, greyLit: false, titleMatch: true, yearMatch: false, authorMatch: false }
  const clean = { doi: '10.1/z', crossrefVerified: true, greyLit: false, titleMatch: true, yearMatch: true, authorMatch: true }
  ok('greyLit: DataCite-запись не считается неверифицированной', !U.isUnverifiedItem(greyItem) && U.isGreyLitItem(greyItem))
  ok('greyLit: DOI без резолва теперь ПОПАДАЕТ в unverified', U.isUnverifiedItem(ghost) && !U.isGreyLitItem(ghost))
  ok('greyLit: прежние случаи не изменились', U.isUnverifiedItem(badTitle) && U.isUnverifiedItem(metaMismatch) && !U.isUnverifiedItem(clean))
  ok('greyLit: null не ломает', U.isUnverifiedItem(null) === false && U.isGreyLitItem(undefined) === false)
}

// ── A9: телеметрия покрытия ──────────────────────────────────────────────────────────────────
{
  const subqs = [{ id: 'q1', label: 'Сон', terms: ['sleep'] }, { id: 'q2', label: 'Сперма', terms: ['sperm'] }]
  const cov = U.coverageCounts([{ title: 'sleep a' }, { title: 'sleep b' }, { title: 'other' }], subqs)
  ok('coverage: подтема с нулём видна в телеметрии', cov['Сон'] === 2 && cov['Сперма'] === 0, cov)
}

// ── A8: потолок действительно взводит capHitSnowball ─────────────────────────────────────────
;(async () => {
  const src = SRC.replace('export const meta', 'const meta')
  const paper = (i, ext, doi) => ({
    prefix: `x${i}`, title: `Title ${i} sleep`, doi, pmid: null, externalId: ext, year: 2021,
    studyType: i % 2 ? 'systematic-review' : 'meta-analysis', sampleN: 100, citations: 50 + i,
    influentialCitations: 2, fwci: 1.2, isOA: true, oaUrl: 'http://x/1.pdf', contrib: 'c', qualitySignals: [],
  })
  let n = 0
  const agent = async (prompt, opts) => {
    const l = opts.label
    if (l === 'query') return { discipline: 'biomedical', framing: 'PECO', pico: {}, concepts: [], subquestions: [], extraQueries: [], coverage: [], queries: {}, skip: [], notes: '' }
    if (l === 'dedup') return { seedFile: 's', canonicalCount: 1, seenKeys: [], hubs: [{ externalId: 'W1', api: 'openalex', doi: null, title: 'h', reason: 'r' }], saturationEstimate: 0.1 }
    if (l === 'cocite') return { hubId: 'cocite', apiUsed: 'openalex', addedPapers: [], note: '' }
    if (l.startsWith('chase')) return { hubId: 'W1', apiUsed: 'openalex', addedPapers: Array.from({ length: 30 }, () => paper(++n, `W${1000 + n}`, `10.9/${n}`)), note: 'n' }
    if (l.startsWith('enrich')) return { batchIndex: 0, fileWritten: 'f', items: [] }
    if (l.startsWith('synth')) return { reportPath: 'x/draft.md', queryRu: 'q', mainConclusion: 'm', evidenceStrengthMax: 'LOW', gradeMax: 'LOW', retractedExcluded: [], relatedCandidates: [], gaps: [], keyDois: [] }
    if (l === 'adversarial') return { reviewPath: 'r', missingPapers: [], reliabilityScore: 5, claimVerdicts: [], retractionRecheck: [], pubpeerFlags: [], edits: [] }
    if (l === 'fix') return { applied: [], skipped: [], tldrUpdated: false, evidenceTableUpdated: false, frontmatterUpdated: false, reliabilityScore: 5 }
    // источники: 8 статей каждый — 3 источника хватает, чтобы упереться в потолок 20
    return { source: l, prefix: l.slice(0, 2), findings: ['f'], papers: Array.from({ length: 8 }, () => paper(++n, `W${n}`, `10.5/${l}${n}`)), sourceQuality: 'HIGH', fileWritten: `x/${l}.md` }
  }
  const AsyncFn = Object.getPrototypeOf(async function () {}).constructor
  const run = new AsyncFn('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', src)
  const res = await run(
    JSON.stringify({ discipline: 'biomedical', workDir: '/tmp/x', paperCap: 20, corpusOnly: true }),
    agent, fns => Promise.all(fns.map(f => f())), async (items, fn) => { const o = []; for (const it of items) o.push(await fn(it)); return o },
    () => {}, () => {}, { remaining: () => 10_000_000 })
  ok('capHitSnowball: потолок во время snowball взводит флаг', res.capStats.capHitSnowball === true, res.capStats)
  ok('capHitSnowball: корпус не превысил потолок', res.papersTotal <= 20 + res.capStats.sideRecords, res.papersTotal)

  // ── A10: синтез по умолчанию на Opus, повтор при null — на другом семействе, в обе стороны ──
  const SP = 'jadlis-science-research:'
  const cases = [
    { name: 'по умолчанию', args: {}, first: [SP + 'synth-opus', 'claude-opus-5-5'], retry: [SP + 'synth-fable', 'claude-fable-5-1'], retryLabel: 'synth→fable-retry' },
    { name: 'fableBridge:true', args: { fableBridge: true }, first: [SP + 'synth-fable', 'claude-fable-5-1'], retry: [SP + 'synth-opus', 'claude-opus-5-5'], retryLabel: 'synth→opus-retry' },
  ]
  const runSynth = async (extra, nulls) => {
    const calls = []
    const stub = async (prompt, opts) => {
      if (!opts.label.startsWith('synth')) return agent(prompt, opts)
      calls.push({ label: opts.label, agentType: opts.agentType, aiModel: (/ai_model: "([^"]+)"/.exec(prompt) || [])[1] })
      return calls.length <= nulls ? null : { reportPath: 'x/draft.md', queryRu: 'q', mainConclusion: 'm', evidenceStrengthMax: 'LOW', gradeMax: 'LOW', retractedExcluded: [], relatedCandidates: [], gaps: [], keyDois: [] }
    }
    const r = await run(
      JSON.stringify({ discipline: 'biomedical', workDir: '/tmp/x', paperCap: 20, ...extra }),
      stub, fns => Promise.all(fns.map(f => f())), async (items, fn) => { const o = []; for (const it of items) o.push(await fn(it)); return o },
      () => {}, () => {}, { remaining: () => 10_000_000 })
    return { r, calls }
  }
  for (const c of cases) {
    const clean = await runSynth(c.args, 0)
    ok(`synth ${c.name}: первый вызов — ${c.first[0].split(':')[1]}, ai_model ${c.first[1]}`,
      clean.calls.length === 1 && clean.calls[0].agentType === c.first[0] && clean.calls[0].aiModel === c.first[1] && clean.r.aiModelActual === c.first[1], clean.calls)
    const retried = await runSynth(c.args, 1)
    const rc = retried.calls[1] || {}
    ok(`synth ${c.name}: null → один повтор на ${c.retry[0].split(':')[1]}, aiModelActual=${c.retry[1]}`,
      retried.calls.length === 2 && rc.label === c.retryLabel && rc.agentType === c.retry[0] && rc.aiModel === c.retry[1] && retried.r.aiModelActual === c.retry[1] && retried.r.status === 'ok',
      { calls: retried.calls, aiModelActual: retried.r.aiModelActual })
    const failedTwice = await runSynth(c.args, 2)
    ok(`synth ${c.name}: два null → synthesis-failed, третьего вызова нет`, failedTwice.calls.length === 2 && failedTwice.r.status === 'synthesis-failed', failedTwice.calls.length)
  }
  console.log(failed ? `UNITS FAILED=${failed}` : 'UNITS OK')
  process.exit(failed ? 1 : 0)
})().catch(e => { console.log('UNITS CRASHED: ' + e.stack.split('\n').slice(0, 4).join(' | ')); process.exit(1) })
