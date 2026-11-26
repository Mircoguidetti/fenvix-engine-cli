'use strict';
// P2 C4: hazards() finds the paths a listing sees through an index by parent directory instead of a scan of every
// written path. The result must be identical: the same pairs, the same kind and path for each pair (the first one
// found is kept, so the order of the search matters too), the same sort. This compares the engine's hazards() with
// the algorithm as it was at 6e79a62 (copied here verbatim) on generated footprints built to exercise every rule.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { hazards } = require('../src/parallel');

/** hazards() at 6e79a62, unchanged. */
function reference(markers, laneOf) {
  const writers = new Map();
  const listeners = new Map();
  for (const [label, m] of markers) {
    const f = m.footprint;
    if (!f) continue;
    for (const w of f.w) { if (!writers.has(w)) writers.set(w, []); writers.get(w).push(label); }
    for (const p of f.listen) { if (!listeners.has(p)) listeners.set(p, []); listeners.get(p).push(label); }
  }
  const out = new Map();
  const lane = (l) => (laneOf.has(l) ? laneOf.get(l) : null);
  const addH = (a, b, kind, what) => {
    if (a === b) return;
    const la = lane(a); const lb = lane(b);
    if (la === null || lb === null || la === lb) return;
    const [x, y] = a < b ? [a, b] : [b, a];
    const k = `${x}\u0000${y}`;
    if (!out.has(k)) out.set(k, { a: x, b: y, kind, what });
  };
  for (const [label, m] of markers) {
    const f = m.footprint;
    if (!f) continue;
    for (const r of f.r) for (const w of writers.get(r) || []) addH(label, w, 'read-write', r);
    for (const r of f.w) for (const w of writers.get(r) || []) addH(label, w, 'write-write', r);
    for (const d of f.l) {
      const pre = d.endsWith('/') ? d : `${d}/`;
      for (const [p, ws] of writers) if (p.startsWith(pre) && !p.slice(pre.length).includes('/')) for (const w of ws) addH(label, w, 'list-write', d);
    }
    for (const p of f.listen) for (const o of listeners.get(p) || []) addH(label, o, 'port', p);
    for (const p of f.connect) for (const o of listeners.get(p) || []) addH(label, o, 'port', p);
  }
  return [...out.values()].sort((x, y) => (x.a < y.a ? -1 : x.a > y.a ? 1 : x.b < y.b ? -1 : x.b > y.b ? 1 : 0));
}

/** A small deterministic generator (no Math.random: the test is the same on every run). */
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32; };
}

// paths chosen so that every listing edge case occurs: a directory and a file with a common prefix (/t/a, /t/ab),
// nested children (must not be seen by a listing of the parent), a written path ending in '/', a written path that
// equals the listed directory, a relative path without '/', the root, and listings given with and without '/'
const PATHS = ['/t/a', '/t/ab', '/t/a/x', '/t/a/x/y', '/t/a/', '/t/b', '/t', '/', '/x', 'rel', 'rel/x', '/t/a/z', '/t/ab/q'];
const DIRS = ['/t', '/t/', '/t/a', '/t/a/', '/t/ab', '/', '', 'rel', '/t/a/x', '/none'];
const PORTS = ['tcp:1', 'tcp:2', 'tcp:3'];

function generate(seed, files, lanes) {
  const R = rng(seed);
  const pick = (xs, n) => { const o = []; for (let i = 0; i < n; i++) o.push(xs[Math.floor(R() * xs.length)]); return o; };
  const markers = new Map();
  const laneOf = new Map();
  for (let i = 0; i < files; i++) {
    const label = `f${String(i).padStart(3, '0')}`;
    if (R() < 0.9) laneOf.set(label, Math.floor(R() * lanes)); // some files are outside the plan
    const fp = R() < 0.1 ? null : {
      w: pick(PATHS, Math.floor(R() * 4)), r: pick(PATHS, Math.floor(R() * 4)), l: pick(DIRS, Math.floor(R() * 3)),
      listen: pick(PORTS, R() < 0.3 ? 1 : 0), connect: pick(PORTS, R() < 0.3 ? 1 : 0),
    };
    markers.set(label, { label, footprint: fp });
  }
  return { markers, laneOf };
}

test('hazards(): identical to the 6e79a62 algorithm on 300 generated footprint sets (C4)', () => {
  // protects= the faster listing lookup finds the same hazards with the same kind and path per pair;
  // fails_when= any pair, kind, path or the order differs from the reference algorithm; no_claim= the speed
  let nonEmpty = 0; let listWrite = 0;
  for (let seed = 1; seed <= 300; seed++) {
    const { markers, laneOf } = generate(seed, 5 + (seed % 40), 1 + (seed % 4));
    const want = reference(markers, laneOf);
    assert.deepEqual(hazards(markers, laneOf), want, `seed ${seed}`);
    if (want.length) nonEmpty++;
    listWrite += want.filter((h) => h.kind === 'list-write').length;
  }
  // the generated sets do exercise the rules (otherwise the comparison proves nothing)
  assert.ok(nonEmpty > 200, `only ${nonEmpty} sets with hazards`);
  assert.ok(listWrite > 100, `only ${listWrite} list-write hazards`);
});

test('hazards(): the listing rule at its edges (C4)', () => {
  // protects= a listing sees exactly the direct children of the listed directory; fails_when= a nested path, a
  // sibling with a common prefix, or the directory itself is matched differently from the reference
  const laneOf = new Map([['L', 0], ['W', 1]]);
  for (const d of DIRS) {
    for (const p of PATHS) {
      const markers = new Map([
        ['L', { label: 'L', footprint: { w: [], r: [], l: [d], listen: [], connect: [] } }],
        ['W', { label: 'W', footprint: { w: [p], r: [], l: [], listen: [], connect: [] } }],
      ]);
      assert.deepEqual(hazards(markers, laneOf), reference(markers, laneOf), `listing ${JSON.stringify(d)}, written ${JSON.stringify(p)}`);
    }
  }
});
