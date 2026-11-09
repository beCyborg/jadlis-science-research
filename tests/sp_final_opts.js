// Offline check of the final-agent routing (2.4.0): synth + critic with/without args.finalOpts,
// and the Opus retries after a null answer. Reuses the agent stubs of sp_dryrun.js. No network.
const fs = require('fs')
const path = require('path')
const P = path.join(__dirname, '..', 'workflows', 'search-paper-core.js')
const src = fs.readFileSync(P, 'utf8').replace('export const meta', 'const meta')
const stubSrc = fs.readFileSync(path.join(__dirname, 'sp_dryrun.js'), 'utf8')
const stubPart = stubSrc.slice(0, stubSrc.indexOf('\nconst AsyncFn'))
const AsyncFn = Object.getPrototypeOf(async function () {}).constructor

async function runCore(args, nullLabels = []) {
  const env = new Function('require', '__dirname', stubPart + '\nreturn { agent, parallel, pipeline, phase, log, budget }')(require, __dirname)
  const calls = []
  const logs = []
  const agent = async (prompt, opts) => {
    calls.push(Object.assign({}, opts))
    if (nullLabels.includes(opts.label)) return null
    const base = opts.label.replace(/→.*$/, '')
    return env.agent(prompt, Object.assign({}, opts, { label: base }))
  }
  const run = new AsyncFn('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', src)
  const res = await run(JSON.stringify(Object.assign({ dryRun: true, discipline: 'biomedical', workDir: '/tmp/x' }, args)), agent, env.parallel, env.pipeline, env.phase, m => logs.push(String(m)), env.budget)
  return { res, calls, logs, by: l => calls.find(c => c.label === l), labels: pre => calls.filter(c => c.label.startsWith(pre)).map(c => c.label) }
}

const FINAL = { model: 'claude-fable-5-2', effort: 'high' }
const checks = []
const check = (ok, name) => checks.push([name, !!ok])

;(async () => {
  {
    const r = await runCore({})
    const s = r.by('synth'), a = r.by('adversarial')
    check(s && s.agentType === 'jadlis-science-research:synth-opus' && !s.model && !s.effort, 'default: synth on synth-opus, no per-call model/effort')
    check(a && a.effort === 'xhigh' && !a.model, 'default: critic xhigh, no model override')
    check(r.res.aiModelActual === 'claude-opus-5-5', 'default: aiModelActual claude-opus-5-5')
  }
  {
    const r = await runCore({}, ['synth'])
    const s = r.by('synth→opus-high-retry')
    check(JSON.stringify(r.labels('synth')) === '["synth","synth→opus-high-retry"]', 'default + null: one retry, label synth→opus-high-retry')
    check(s && s.agentType === 'jadlis-science-research:synth-opus' && s.effort === 'high' && !s.model, 'default + null: retry on synth-opus at effort high (never synth-fable)')
  }
  {
    const r = await runCore({ finalOpts: FINAL })
    const s = r.by('synth→fable'), a = r.by('adversarial→final')
    check(s && s.agentType === 'jadlis-science-research:synth-fable' && s.model === 'claude-fable-5-2' && s.effort === 'high', 'finalOpts: synth on synth-fable with per-call model + effort')
    check(a && a.model === 'claude-fable-5-2' && a.effort === 'high', 'finalOpts: critic gets the per-call model + effort')
    check(r.res.aiModelActual === 'claude-fable-5-2', 'finalOpts: aiModelActual claude-fable-5-2')
    check(!r.calls.some(c => c.model && !/^(synth→fable|adversarial→final)$/.test(c.label)), 'finalOpts: no other agent gets a model override')
  }
  {
    const r = await runCore({ finalOpts: FINAL }, ['synth→fable', 'adversarial→final'])
    const s = r.by('synth→opus-retry'), a = r.by('adversarial→opus-retry')
    check(s && s.agentType === 'jadlis-science-research:synth-opus' && !s.model && !s.effort, 'finalOpts + null synth: retry on synth-opus (xhigh frontmatter), no Fable')
    check(a && a.effort === 'xhigh' && !a.model, 'finalOpts + null critic: retry on Opus 5.5 xhigh')
    check(r.res.aiModelActual === 'claude-opus-5-5', 'finalOpts + null synth: aiModelActual claude-opus-5-5')
  }
  for (const bad of [{ model: 'fable', effort: 'high' }, { model: 'claude-fable-5-2', effort: 'ultra' }, 'x', null]) {
    const r = await runCore({ finalOpts: bad })
    check(r.by('synth') && !r.by('synth').model && r.by('adversarial') && !r.by('adversarial').model, `invalid finalOpts ${JSON.stringify(bad)} → defaults`)
  }
  {
    const r = await runCore({ fableBridge: true })
    const s = r.by('synth→fable')
    check(s && s.agentType === 'jadlis-science-research:synth-fable' && !s.model && !s.effort && r.res.aiModelActual === 'claude-fable-5-2', 'fableBridge:true: synth-fable on its frontmatter, aiModelActual claude-fable-5-2')
    check(r.by('adversarial') && !r.by('adversarial').model, 'fableBridge:true without finalOpts: critic stays Opus')
  }
  const failed = checks.filter(([, ok]) => !ok)
  for (const [n, ok] of checks) console.log(`${ok ? 'ok  ' : 'FAIL'} ${n}`)
  console.log(failed.length ? `FINAL_OPTS_FAILED=${failed.length}` : 'FINAL_OPTS=ok')
  process.exit(failed.length ? 1 : 0)
})().catch(e => { console.log('RUN FAILED: ' + e.stack.split('\n').slice(0, 4).join(' | ')); process.exit(1) })
