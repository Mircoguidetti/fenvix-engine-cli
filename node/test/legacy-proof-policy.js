'use strict';
// TEST-ONLY reference: the Node session policy as it was in JavaScript (node/src/cache/proof.js on
// claude/all-runners b8c6333 + claude/node-cache-proof 8cd01e6a: UNCACHEABLE, uncacheable(), recordAll()'s
// observation and entry composition with its environment dependencies, verifyOne(), writeReceipts()). Changes
// (review R-032b nit): what it read from `this` and CAPTURE comes from the same input object the Rust policy
// takes (crates/detpy-core/src/node_session.rs); `envDep` reads only own string values of the environment
// (`hasOwnProperty` and `typeof === 'string'`), as the Rust policy's input is built by proof.js (all-runners had
// `curEnv[name] ?? null`, which also returned inherited properties such as `constructor`). Two inputs on which
// the policies differ and which real captures never produce (the flag set is fixed, its details are strings): a
// flag named after an Object.prototype property (`constructor`, `toString`) is a refusal here and not in Rust.
// (Object details inside an array detail were written as JSON by Rust: now `[object Object]`, as here.) Used by test/policy-equivalence.test.js
// and test/review-r032b-policy.test.js only; the engine calls Rust.
const native = require('../src/native');

const UNCACHEABLE = {
  spawn: 'subprocess',
  worker: 'worker thread',
  connect: 'network connection',
  udp: 'UDP socket',
  'net-record': 'network recording (--det-record)',
  proc: 'reads /proc, /sys or /dev',
  rw: 'reads a file another test file or the start-up code wrote',
  entropy: 'os entropy (not controlled; use --det-urandom)',
  'env-unobserved': 'environment reads not observable in this process',
  machine: 'reads a machine fact that changes between calls',
  stat: 'reads file metadata that is not keyed (times, inode, owner)',
  statfs: 'reads file system statistics',
  watch: 'watches the file system',
  sqlite: 'opens an SQLite database that cannot be keyed by its path',
  resolve: 'a module specifier that could not be resolved and is not keyed (bare or mapped)',
  'import-glob': 'an import.meta.glob call that cannot be keyed',
  'runtime-api': 'uses a runtime API whose inputs are not keyed',
  'dynamic-import': 'a dynamic import whose target is not known before the run',
  unobserved: 'the runtime reported an access the capture did not see',
  binding: 'reaches native bindings directly (process.binding): reads not observable',
  'clock-real': 'reads a clock Level 0 does not virtualize',
  keygen: 'OS randomness drawn in native crypto (key generation, randomized encryption or signatures)',
  preload: 'a preload module read the clock or OS entropy before Level 0 was installed',
  loader: 'an off-thread module loader (--loader, module.register): what it reads is not observable',
  // P-041 (policy change, mirrored here): native addons (row JS-09), Level 0 controls that could not be installed
  // (G-0181), and any flag the table does not know refuses reuse instead of being ignored
  native: 'loads a native addon (its reads are not observable)',
  'level0-gap': 'a Level 0 control could not be installed',
};
const UNKNOWN_FLAG = 'an input the engine cannot key';

function idOf(fileId, project) { return project ? `${fileId}@@${project}` : fileId; }
function testKey(testId, project) {
  if (!project) return testId;
  const i = testId.indexOf('::');
  return i < 0 ? `${testId}@@${project}` : `${testId.slice(0, i)}@@${project}${testId.slice(i)}`;
}

function uncacheable(o, outcome) {
  if (!['passed', 'skipped', 'todo'].includes(outcome)) return `outcome ${outcome}`;
  for (const [f, detail] of o.flags) {
    return `${Object.prototype.hasOwnProperty.call(UNCACHEABLE, f) ? UNCACHEABLE[f] : UNKNOWN_FLAG}: ${detail}`;
  }
  return null;
}

/** recordAll(captures) on `store` (a native ProofCache) with the session state from `input`. */
function recordAll(input, store) {
  const S = {
    hits: new Map(Object.entries(input.hits || {}).map(([k, v]) => [k, { outcome: v }])),
    verify: input.verify, notCached: new Map(), recorded: 0, verified: [], ranFiles: {},
    uncacheableProjects: new Set(input.uncacheable_projects || []), specKeys: new Set(input.spec_keys || []),
  };
  const verifyOne = (nid, outcome) => {
    if (!S.verify || !S.hits.has(nid)) return;
    const rc = S.hits.get(nid);
    S.verified.push({ nodeid: nid, cached: rc.outcome, fresh: outcome, same: rc.outcome === outcome });
  };
  const configFor = (proj) => (input.config_for || {})[proj] || '';
  const captures = input.captures;
  const curEnv = input.cur_env;
  const envAll = native.envAllDigest(curEnv);
  const envDep = (name) => (name === '*' ? envAll : native.envValueDigest(Object.prototype.hasOwnProperty.call(curEnv, name) && typeof curEnv[name] === 'string' ? curEnv[name] : null));
  const global = input.global.filter((it) => !(it[0] === 'data' && (it[3] === 'infra' || it[3] === 'plugin') && S.specKeys.has(it[1])));
  const writers = new Map();
  const addW = (k, l) => { let s = writers.get(k); if (!s) writers.set(k, (s = new Set())); s.add(l); };
  for (const it of input.global) if (it[0] === 'write') addW(it[1], '');
  for (const c of captures) for (const it of c.items) if (it[0] === 'write') addW(it[1], c.label);
  let past = {};
  try { past = JSON.parse(store.written()); } catch { /* none */ }
  for (const [k, ls] of Object.entries(past)) for (const l of ls) addW(k, l);
  const sessionWritten = {};
  for (const [k, s] of writers) sessionWritten[k] = [...s];
  const startup = input.startup;
  const fileIx = new Map();
  const codeIndex = (rel, d) => {
    const k = `${rel}\u0000${d}`;
    let i = fileIx.get(k);
    if (i === undefined) { i = store.addFile(rel, d); fileIx.set(k, i); }
    return i;
  };
  const globalItems = global;
  const urandom = Boolean(input.urandom);
  const newObservation = (label, base) => {
    const flags = new Map();
    const env = new Map();
    const data = new Map();
    const content = new Set();
    let clock = false;
    let rwFirst = null;
    const take = (it) => {
      switch (it[0]) {
        case 'data': {
          const dk = `${it[1]}\u0000${it[2]}`;
          if (!data.has(dk)) {
            data.set(dk, [it[1], it[2]]);
            if (rwFirst === null) {
              const ws = writers.get(it[1]);
              if (ws && [...ws].some((w) => w !== label)) rwFirst = `${it[1]} written by ${[...ws].filter((w) => w !== label).join(',') || 'start-up'}`;
            }
          }
          break;
        }
        case 'code': content.add(codeIndex(it[1], it[2])); break;
        case 'env': if (!env.has(it[1])) env.set(it[1], envDep(it[1])); break;
        case 'clock': clock = true; break;
        case 'flag': if (!flags.has(it[1])) flags.set(it[1], it[2]); break;
        default:
      }
    };
    for (const it of globalItems) take(it);
    let pos = 0;
    return {
      at(items, upto) {
        for (; pos < upto && pos < items.length; pos++) take(items[pos]);
        const f = new Map(flags);
        if (base) for (const it of base) if (it[0] === 'flag' && !f.has(it[1])) f.set(it[1], it[2]);
        if (rwFirst !== null && !f.has('rw')) f.set('rw', rwFirst);
        if (f.has('entropy') && urandom) f.delete('entropy');
        return { flags: f, env: [...env.entries()], data: [...data.values()], content: [...content], clock };
      },
    };
  };
  for (const c of captures) {
    const proj = c.project || '';
    const mid = idOf(c.fileId, proj);
    S.ranFiles[mid] = { duration: Math.round((c.duration || 0) * 1000) / 1000, tests: c.tests.length, ok: Boolean(c.ok) };
    if (S.uncacheableProjects.has(proj)) continue;
    const notes = c.notes || [];
    const extraFlags = notes.some((n) => n.startsWith('process.env not replaceable')) ? [['flag', 'env-unobserved', 'process.env']] : [];
    const ids = [];
    const obs = newObservation(c.label, extraFlags);
    const order = c.tests.map((t, i) => [t, i]).sort((x, y) => (x[0].upto - y[0].upto) || (x[1] - y[1]));
    const byTest = new Map();
    for (const [t] of order) byTest.set(t, obs.at(c.items, t.upto));
    for (const t of c.tests) {
      const nid = testKey(t.id, proj);
      ids.push(t.id);
      const o = byTest.get(t);
      const why = uncacheable(o, t.outcome);
      verifyOne(nid, t.outcome);
      if (why) {
        store.remove(nid);
        S.notCached.set(nid, why);
        continue;
      }
      store.record(nid, JSON.stringify({
        outcome: t.outcome, report: { outcome: t.outcome }, fingerprint: t.fingerprint || '', duration: t.duration || 0,
        run: input.run_id, config: configFor(proj), runtime: input.runtime, epoch: o.clock ? input.epoch_ms : null,
        env: o.env, data: o.data, content: o.content, startup,
      }));
      S.recorded++;
    }
    const o = obs.at(c.items, c.items.length);
    const outcome = c.ok ? 'passed' : 'failed';
    verifyOne(mid, outcome);
    const why = uncacheable(o, outcome);
    if (why) {
      store.remove(mid);
      S.notCached.set(mid, why);
      continue;
    }
    store.record(mid, JSON.stringify({
      outcome, report: { kind: 'file', file: c.fileId, project: proj || null, tests: ids }, fingerprint: '',
      duration: c.duration || 0, run: input.run_id, config: configFor(proj), runtime: input.runtime,
      epoch: o.clock ? input.epoch_ms : null, env: o.env, data: o.data, content: o.content, startup,
    }));
  }
  store.addWritten(JSON.stringify(sessionWritten));
  return { recorded: S.recorded, not_cached: [...S.notCached.entries()], verified: S.verified, ran_files: S.ranFiles };
}

/** writeReceipts(): the file's text. `hits`: [[nodeid, receipt object]], `misses`: [[nodeid, why]]. */
function receipts(hits, misses, verify) {
  const lines = [];
  for (const [nid, r] of hits) lines.push(JSON.stringify({ nodeid: nid, reused: !verify, ...(verify ? { would_reuse: true } : {}), ...r }));
  for (const [nid, why] of misses) lines.push(JSON.stringify({ nodeid: nid, reused: false, why }));
  return lines.length ? `${lines.join('\n')}\n` : '';
}

module.exports = { UNCACHEABLE, uncacheable, recordAll, receipts };
