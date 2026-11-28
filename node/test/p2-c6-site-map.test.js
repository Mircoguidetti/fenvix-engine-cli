'use strict';
// P2 C6 / D7 = B (founder decision 2026-11-28): a site is the source line of the test's call, by construction. Under
// Vitest the stack's raw positions are those of the code Vite transformed; the site lookup (src/sites.js
// resolveFormatted) took the source line from the realm's formatted stack, through whatever Error.prepareStackTrace
// was installed. A setup file that loads ts-node (alakajam: `ts-node/register/transpile-only`, for Knex's migrations)
// replaces Vite's stack interceptor with @cspotcode/source-map-support, which has no map for a module Vite evaluated:
// the line came out right only when an earlier formatting (the outside-files recorder at import) had warmed its cache,
// and wrong otherwise (alakajam server/core/forms.ts: 238 for the `new Date()` on line 255). The recorded site of a
// `Date` call must be its source line whether or not the module was imported before the test.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { project, run } = require('./helpers');

const T = { timeout: 600000 };
// a module whose `new Date()` is far below its first line once the types are stripped: Vite's transform drops the
// interface, so the transformed line differs from the source line
const WHEN = `export interface Shape {
  a: number;
  b: number;
  c: number;
  d: number;
  e: number;
  f: number;
  g: number;
  h: number;
  i: number;
  j: number;
  k: number;
  l: number;
  m: number;
}
export function when(): number {
  return new Date().getTime();
}
`;
const DATE_LINE = WHEN.split('\n').findIndex((l) => l.includes('new Date()')) + 1;

function fixture(name, testBody) {
  const dir = project('vitest', name, { a: testBody }, { vitest: { setupFiles: ['setup.mjs'] } });
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'src', 'when.ts'), WHEN);
  // what alakajam's server/scripts/vitest-setup.ts does
  fs.writeFileSync(path.join(dir, 'setup.mjs'), "import { createRequire } from 'node:module';\nconst r = createRequire(import.meta.url);\nr('ts-node/register/transpile-only');\n");
  fs.writeFileSync(path.join(dir, 'tsconfig.json'), JSON.stringify({ compilerOptions: { module: 'commonjs', target: 'es2020' } }));
  return dir;
}

function dateSites(r) {
  const out = [];
  for (const t of r.trace.tests) for (const e of t.events || []) if (e.s === 'time' && e.o === 'Date') out.push(e.at);
  return out;
}

for (const [name, body] of [
  // imported inside the test: nothing formats a stack of this module before the test calls it (no warm-up)
  ['imported in the test', "test('when', async () => { const { when } = await import('../src/when.ts'); expect(when()).toBeGreaterThan(0); });"],
  // imported at the top of the test file
  ['imported at the top', "import { when } from '../src/when.ts';\ntest('when', () => { expect(when()).toBeGreaterThan(0); });"],
]) {
  test(`vitest with ts-node's source-map support installed: a Date call's site is its source line (${name}) (D7)`, T, () => {
    // protects= the recorded site is the source line of the call, whatever stack formatter the project installed and
    // whatever was formatted before; fails_when= the site is the transformed line (or another), as on alakajam
    const dir = fixture(`p2-site-map-${name.split(' ').pop()}`, body);
    const r = run('vitest', dir, ['--det', '--det-workers=1', '--det-epoch=fixed']);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const sites = dateSites(r);
    assert.ok(sites.length > 0, JSON.stringify(r.trace.tests.map((t) => t.events)));
    for (const s of sites) assert.equal(s, `src/when.ts:${DATE_LINE}`, JSON.stringify(sites));
  });
}
