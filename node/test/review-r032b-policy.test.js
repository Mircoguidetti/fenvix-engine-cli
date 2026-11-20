'use strict';
// Review R-032b: the Rust Node session policy against the JavaScript one it replaced (test/legacy-proof-policy.js),
// on inputs the branch's generator does not produce: unicode and separator characters in ids, paths and env names,
// '' labels (the start-up writer's label), duplicate file ids and test ids, `upto` out of range / fractional,
// numbers and nested objects as flag details, env names inherited from Object.prototype, hits under every key form.
// Run: cd node && node --test test/review-r032b-policy.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const native = require('../src/native');
const legacy = require('./legacy-proof-policy');

fs.mkdirSync(path.join(__dirname, '.tmp'), { recursive: true });
const TMP = fs.mkdtempSync(path.join(__dirname, '.tmp', 'r032b-policy-'));

function both(input, prior) {
  const dirs = ['js', 'rust'].map((n) => fs.mkdtempSync(path.join(TMP, `${n}-`)));
  const stores = dirs.map((d) => new native.ProofCache(d, '/project'));
  for (const s of stores) if (prior) s.addWritten(JSON.stringify(prior));
  let js; let jsErr = null;
  try { js = legacy.recordAll(input, stores[0]); } catch (e) { jsErr = String(e); }
  let rs; let rsErr = null;
  try { rs = JSON.parse(stores[1].recordSession(JSON.stringify(input))); } catch (e) { rsErr = String(e); }
  if (jsErr || rsErr) return { jsErr, rsErr };
  stores.forEach((s) => s.save());
  const text = dirs.map((d) => fs.readFileSync(path.join(d, 'proof-cache.json'), 'utf8'));
  return { js, rs, text };
}

function rng(seed) {
  let x = (seed * 2654435761) >>> 0 || 1;
  return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; };
}

function input(seed) {
  const r = rng(seed);
  const pick = (a) => a[Math.floor(r() * a.length)];
  const paths = ['a.txt', 'é/ü.txt', 'out/x', 'a\u0000b', 'sp ace', '@@x', 'x::y', '日本.txt', ''];
  const flags = [...Object.keys(legacy.UNCACHEABLE), 'note', ''];
  const details = ['d', '', 0, -1, 1.5, 1e21, null, false, [], ['x', 2], '\u2028']; // object details: reason text differs ([object Object] vs JSON), see report
  const labels = ['', 'L0', 'L1', 'é'];
  const envNames = ['A', 'toString', 'hasOwnProperty', '__proto__', 'valueOf', '*', '', 'Ü', 'PATH'];
  const item = () => {
    const k = pick(['data', 'data', 'code', 'env', 'clock', 'flag', 'flag', 'write', 'write']);
    if (k === 'data') return ['data', pick(paths), pick(['f:1', 'f:2', 'missing', '']), ...(r() < 0.3 ? [pick(['infra', 'plugin', 'user', ''])] : [])];
    if (k === 'code') return ['code', pick(paths), pick(['c1', ''])];
    if (k === 'env') return ['env', pick(envNames)];
    if (k === 'clock') return ['clock'];
    if (k === 'flag') return ['flag', pick(flags), pick(details)];
    return ['write', pick(paths)];
  };
  const fileIds = ['f.test.js', 'f.test.js', 'é.test.js', 'a::b.test.js', 'p@@q.test.js'];
  const captures = [];
  for (let i = 0, n = 1 + Math.floor(r() * 5); i < n; i++) {
    const items = Array.from({ length: Math.floor(r() * 14) }, item);
    const fileId = pick(fileIds);
    const tests = Array.from({ length: Math.floor(r() * 5) }, (_, j) => ({
      id: pick([`${fileId}::t${j}`, `${fileId}::t0`, fileId, `${fileId}::a::b`, `${fileId}::é`]),
      upto: pick([0, Math.floor(r() * (items.length + 3)), items.length + 10, items.length]),
      outcome: pick(['passed', 'skipped', 'todo', 'failed', 'cancelled', 'error', '']),
      ...(r() < 0.5 ? { fingerprint: pick(['fp', '', 'é']) } : {}), ...(r() < 0.5 ? { duration: pick([0, r(), 1e-9, 12345.6789]) } : {}),
    }));
    captures.push({ label: pick(labels), fileId, ...(r() < 0.4 ? { project: pick(['p1', 'p@@2', 'p::3', '']) } : {}),
      duration: pick([0, r(), 0.0005, 0.0015, 2.0005]), ok: r() < 0.6,
      notes: r() < 0.3 ? [pick(['process.env not replaceable: x', 'other note'])] : [], tests, items });
  }
  const hits = {};
  for (const c of captures) {
    const proj = c.project || '';
    if (r() < 0.6) hits[proj ? `${c.fileId}@@${proj}` : c.fileId] = pick(['passed', 'failed', 'skipped']);
    for (const t of c.tests) {
      if (r() < 0.6) {
        const i = t.id.indexOf('::');
        const key = !proj ? t.id : (i < 0 ? `${t.id}@@${proj}` : `${t.id.slice(0, i)}@@${proj}${t.id.slice(i)}`);
        hits[key] = pick(['passed', 'failed', 'todo']);
      }
    }
  }
  const curEnv = { A: '1', PATH: '/bin', Ü: 'ü', '': 'empty-name' };
  return {
    global: Array.from({ length: Math.floor(r() * 8) }, item), spec_keys: ['a.txt', 'f.test.js', 'é/ü.txt'], captures, cur_env: curEnv,
    urandom: r() < 0.5, epoch_ms: pick([null, 0, 1700000000000]), run_id: `run${seed}`, runtime: 'RT', startup: pick(['', 'S']),
    config_for: { '': 'C0', p1: 'C1', 'p@@2': 'C2' }, uncacheable_projects: r() < 0.2 ? [pick(['p1', ''])] : [], verify: r() < 0.6, hits,
  };
}

test('adversarial seeded inputs: Rust policy equals the JavaScript one (3000 inputs)', () => {
  const diffs = [];
  for (let seed = 1; seed <= 3000; seed++) {
    const inp = JSON.parse(JSON.stringify(input(seed)));
    const prior = seed % 4 ? null : { 'out/x': ['L1', ''], 'a.txt': ['é'], 'é/ü.txt': [''] };
    const o = both(inp, prior);
    if (o.jsErr || o.rsErr) { if (Boolean(o.jsErr) !== Boolean(o.rsErr)) diffs.push(`seed ${seed}: js error ${o.jsErr} / rust error ${o.rsErr}`); continue; }
    const { js, rs, text } = o;
    const what = [];
    if (rs.recorded !== js.recorded) what.push('recorded');
    try { assert.deepEqual(rs.not_cached, js.not_cached); } catch { what.push('not_cached'); }
    try { assert.deepEqual(rs.verified, js.verified); } catch { what.push('verified'); }
    try { assert.deepEqual(rs.ran_files, js.ran_files); } catch { what.push('ran_files'); }
    if (text[0] !== text[1]) what.push('store');
    if (what.length) diffs.push(`seed ${seed}: ${what.join(',')}`);
  }
  assert.deepEqual(diffs.slice(0, 30), [], `${diffs.length} differing inputs`);
});
