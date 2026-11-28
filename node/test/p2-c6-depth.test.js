'use strict';
// P2 C6: sites.resolve() captures the first frames of the stack and, when they decide nothing (every one is Node,
// detjs or code without a file), captures again with 30 frames. On agentsys (Jest) a third of the calls needed the
// second capture, nearly all of them decided at frame 8 or 9 (harness/p2/C6.md): a first capture of 10 frames
// decides those at once. Whatever the first depth (up to 30), the site is the first deciding frame within 30
// frames, so the result is the same: this checks it for a deciding frame at every position from 0 to 34.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const sites = require('../src/sites');

// frames without a file (a `new Function` body recursing into itself): resolveDepth skips them, as it skips Node's and
// detjs' frames. The resolver is called from the innermost one, so the first deciding frame is this test file's, after
// k + 2 file-less frames (the k + 1 recursion levels and the Function body itself).
const deep = new Function('k', 'resolver', 'arg', 'const g = (n) => (n === 0 ? resolver(arg) : g(n - 1)); return g(k);');
const at = (k, resolver, arg) => deep(k, resolver, arg);

test('resolve(): the same site with a first capture of 8 or 10 frames, at every depth of the deciding frame (C6)', () => {
  // protects= the first depth changes only the cost; fails_when= a call deciding at frame 8-30 (or beyond 30, or
  // nowhere) gets another site; no_claim= the speed
  assert.equal(typeof sites.resolveWith, 'function');
  const seen = new Set();
  for (let k = 0; k <= 34; k++) {
    const d8 = at(k, sites.resolveWith, 8); const d10 = at(k, sites.resolveWith, 10); const r = at(k, sites.resolve);
    seen.add(d8 === '<node>' ? '<node>' : 'site');
    assert.equal(d10, d8, `deciding frame after ${k + 2} file-less frames: first depth 10 vs 8`);
    assert.equal(r, d8, `deciding frame after ${k + 2} file-less frames: resolve() vs first depth 8`);
  }
  // both outcomes occur: a site (deciding frame within 30 frames) and '<node>' (none within 30)
  assert.deepEqual([...seen].sort(), ['<node>', 'site']);
});
