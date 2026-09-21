// Offline harness: runs search-paper-core.js with stubbed agent/parallel/pipeline to prove every
// prompt builder renders without ReferenceError. No network, no model calls.
const fs = require('fs')
const path = require('path')
const P = path.join(__dirname, '..', 'workflows', 'search-paper-core.js')
const src = fs.readFileSync(P, 'utf8').replace('export const meta', 'const meta')

const prompts = []
const paper = (i, ext, doi) => ({
  prefix: `x${i}`, title: `Title ${i}`, doi, pmid: null, externalId: ext, year: 2021,
  studyType: i % 2 ? 'systematic-review' : 'meta-analysis', sampleN: 100, citations: 50 + i, influentialCitations: 2,
  fwci: 1.2, isOA: true, oaUrl: 'http://x/1.pdf', contrib: 'c', qualitySignals: [],
})

async function agent(prompt, opts) {
  prompts.push({ label: opts.label, prompt })
  const l = opts.label
  if (l === 'query') return { discipline: 'biomedical', framing: 'PECO', pico: {}, concepts: [{label:'Melatonin', synonyms:['N-acetyl-5-methoxytryptamine','circadin "PR"'], meshTerms:[]}], queries: {}, skip: [], notes: '' }
  if (l === 'dedup') return {
    seedFile: 'x/_seed.md', canonicalCount: 3,
    seenKeys: ['10.1/a'],
    hubs: [
      { externalId: 'W123', api: 'openalex', doi: 'https://doi.org/10.1/HUB', title: 'h1', reason: 'r' },
      { externalId: 'S2abc', api: 's2', doi: null, title: 'h2', reason: 'r' },
    ],
    saturationEstimate: 0.5,
  }
  if (l === 'cocite') return { hubId: 'cocite', apiUsed: 'openalex', addedPapers: [paper(7, 'W777', '10.1/cc')], note: 'cc' }
  if (l.startsWith('chase')) return { hubId: 'W123', apiUsed: 'openalex', addedPapers: [paper(9, 'W999', '10.1/new')], note: 'n' }
  if (l.startsWith('enrich')) return {
    batchIndex: 0, fileWritten: 'f',
    items: [{ doi: '10.1/a', crossrefVerified: true, titleMatch: true, yearMatch: false, authorMatch: false, isRetracted: false, retractionDate: null, industryFunded: false, oaStatus: 'gold', isOA: true, oaPdfUrl: 'http://x/a.pdf' }],
  }
  if (l.startsWith('fulltext')) return { doi: '10.1/a', extracted: true, summary: 's', numbersVerbatim: [], fileWritten: 'f' }
  if (l.startsWith('synth')) return { reportPath: 'x/draft.md', queryRu: 'q', mainConclusion: 'm', evidenceStrengthMax: 'MODERATE', gradeMax: 'LOW', retractedExcluded: [], relatedCandidates: [], gaps: [], keyDois: ['10.1/a'] }
  if (l === 'adversarial') return { reviewPath: 'x/adversarial.md', reliabilityScore: 7, claimVerdicts: [], retractionRecheck: [], pubpeerFlags: [], edits: [{ id: 'F1', finding: 'f', action: 'a', confidence: 0.9, affectsTldr: true, targetSections: ['TL;DR'] }] }
  if (l === 'fix') return { applied: ['F1'], skipped: [], tldrUpdated: true, evidenceTableUpdated: true, frontmatterUpdated: true, reliabilityScore: 7 }
  // source agents
  return { source: l, prefix: l.slice(0, 2), findings: ['f'], papers: [paper(1, 'W1', '10.1/a'), paper(2, null, '10.1/b' + l), paper(3, 'W3' + l.length, null)], sourceQuality: 'HIGH', fileWritten: `x/${l}.md` }
}
const parallel = fns => Promise.all(fns.map(f => f()))
const pipeline = async (items, fn) => { const o = []; for (const it of items) o.push(await fn(it)); return o }
const phase = () => {}
const log = () => {}
const budget = { remaining: () => 10_000_000 }

const AsyncFn = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFn('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', src)

run(JSON.stringify({ discipline: 'biomedical', workDir: '/tmp/x' }), agent, parallel, pipeline, phase, log, budget)
  .then(res => {
    console.log('RUN OK status=' + res.status + ' papers=' + res.papersTotal + ' prompts=' + prompts.length)
    const want = ['query', 'core', 'dedup', 'cocite', 'chase', 'enrich', 'fulltext', 'synth', 'adversarial', 'fix']
    for (const w of want) console.log(`  ${w}: ${prompts.some(p => p.label.startsWith(w)) ? 'rendered' : 'MISSING'}`)
    const SHELL_OK = /\$\{(SEMANTIC_SCHOLAR_API_KEY|CROSSREF_MAILTO|OPENALEX_API_KEY|UNPAYWALL_EMAIL|CORE_API_KEY|PUBMED_API_KEY|PUBMED_EMAIL)(:-)?\}/g
    const bad = prompts.filter(p => /\$\{|undefined/.test(p.prompt.replace(SHELL_OK, '')))
    console.log('BROKEN_TEMPLATES=' + (bad.map(p => p.label).join(',') || 'none'))
    const missing = want.filter(w => !prompts.some(p => p.label.startsWith(w)))
    if (bad.length || missing.length) { console.log('MISSING=' + missing.join(',')); process.exit(1) }
    if (process.env.SP_DRYRUN_DUMP) fs.writeFileSync(process.env.SP_DRYRUN_DUMP, JSON.stringify(prompts, null, 1))
  })
  .catch(e => { console.log('RUN FAILED: ' + e.stack.split('\n').slice(0, 4).join(' | ')); process.exit(1) })
