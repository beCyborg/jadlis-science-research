// Args guard of search-paper-core.js (2.3.6): a broken call must throw BEFORE the first agent()
// call — no silent fall-through to the dry-run defaults. Stubbed agent/parallel/pipeline, no
// network, no model calls. The agent stub returns null, so a run that passes the guard ends early
// on its own (insufficient sources) — the harness only needs to see that agents were reached.
const fs = require('fs')
const path = require('path')

const P = path.join(__dirname, '..', 'workflows', 'search-paper-core.js')
const src = fs.readFileSync(P, 'utf8').replace('export const meta', 'const meta')
const AsyncFn = Object.getPrototypeOf(async function () {}).constructor

const run = async args => {
  const calls = []
  const agent = async (prompt, opts) => { calls.push(opts.label); return null }
  const fn = new AsyncFn('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', src)
  try {
    await fn(args, agent, fns => Promise.all(fns.map(f => f())),
      async (items, f) => { const o = []; for (const it of items) o.push(await f(it)); return o },
      () => {}, () => {}, { remaining: () => 10_000_000 })
    return { err: null, calls }
  } catch (e) { return { err: e, calls } }
}

const FULL = {
  pluginRoot: '/tmp/plugin', vaultPath: '/tmp/vault',
  refinedQueryRu: 'Мелатонин и засыпание', refinedQueryEn: 'melatonin sleep onset latency in adults',
  framing: 'PICO', discipline: 'biomedical', decisionContext: 'd', populationLayer: 'p', timeHorizon: 't',
  guidelines: true, lang: 'ru', personalize: false, profileContext: null, recon: 'r',
  date: '2026-10-02', workDir: '/tmp/vault/.search-paper/abc_melatonin',
}

let failed = 0
const ok = (name, cond, extra) => {
  console.log(`${cond ? 'ok  ' : 'FAIL'} ${name}${cond ? '' : ' — ' + extra}`)
  if (!cond) failed++
}
const msg = r => (r.err && r.err.message) || ''

;(async () => {
  {
    const r = await run(undefined)
    ok('guard:no-args', r.err && r.calls.length === 0 && msg(r).includes('search-paper-core') &&
      msg(r).includes('refinedQueryRu') && msg(r).includes('dryRun:true') && msg(r).includes('resumeFromRunId'),
      `${r.calls.length} calls, ${msg(r)}`)
  }
  {
    const r = await run('{"refinedQueryRu": "„Омега-3“ и "триглицериды"", "workDir": "/tmp/x"}')
    ok('guard:curly-quotes', r.err && r.calls.length === 0 && msg(r).includes('not valid JSON') &&
      msg(r).includes('curly quotes „“') && msg(r).includes('resume does not inherit args') && msg(r).includes('триглицериды'),
      `${r.calls.length} calls, ${msg(r)}`)
  }
  {
    const r = await run({ ...FULL, workDir: '.search-paper/abc_melatonin' })
    ok('guard:relative-workdir', r.err && r.calls.length === 0 && msg(r).includes('absolute'), `${r.calls.length} calls, ${msg(r)}`)
  }
  {
    const { refinedQueryEn: _e, ...noEn } = FULL
    const r = await run(JSON.stringify({ ...noEn, date: '  ' }))
    ok('guard:missing-and-empty', r.err && r.calls.length === 0 && msg(r).includes('refinedQueryEn, date') && msg(r).includes('Arrived string:'),
      `${r.calls.length} calls, ${msg(r)}`)
  }
  {
    const r = await run('[1, 2]')
    ok('guard:not-an-object', r.err && r.calls.length === 0 && msg(r).includes('must be an object'), `${r.calls.length} calls, ${msg(r)}`)
  }
  {
    const r = await run(JSON.stringify(FULL))
    ok('guard:full-args-pass', !r.err && r.calls[0] === 'query', `err ${msg(r)}, calls ${r.calls.join(',')}`)
  }
  {
    const r = await run({ dryRun: true })
    ok('guard:dryrun-defaults', !r.err && r.calls[0] === 'query', `err ${msg(r)}, calls ${r.calls.join(',')}`)
  }
  console.log(failed ? `GUARD FAILED=${failed}` : 'GUARD OK')
  process.exit(failed ? 1 : 0)
})().catch(e => { console.log('GUARD CRASHED: ' + e.stack.split('\n').slice(0, 4).join(' | ')); process.exit(1) })
