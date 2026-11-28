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

function fixture(name, testBody, { tsNode = true } = {}) {
  const dir = project('vitest', name, { a: testBody }, { vitest: tsNode ? { setupFiles: ['setup.mjs'] } : {} });
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'src', 'when.ts'), WHEN);
  // what alakajam's server/scripts/vitest-setup.ts does
  fs.writeFileSync(path.join(dir, 'setup.mjs'), "import { createRequire } from 'node:module';\nconst r = createRequire(import.meta.url);\nr('ts-node/register/transpile-only');\n");
  fs.writeFileSync(path.join(dir, 'tsconfig.json'), JSON.stringify({ compilerOptions: { module: 'commonjs', target: 'es2020' } }));
  // codex-multi-auth's pattern: the mock factory gets the actual module through a helper (test/helpers/cli-test-fixtures.ts)
  // a module of the project that imports the mocked one (codex-multi-auth: lib/codex-manager.ts imports lib/storage.js)
  fs.writeFileSync(path.join(dir, 'src', 'user.ts'), "import { when } from './when.js';\nexport const use = (): number => when();\n");
  fs.writeFileSync(path.join(dir, 'tests', 'helper.mjs'), "import { vi } from 'vitest';\nexport async function whenMock() { return { ...(await vi.importActual('../src/when.js')) }; }\n");
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
  // mocked with the actual implementation kept (codex-multi-auth's lib/storage.ts): Vitest's mocker replaces the
  // module node's code with the mock's, which carries no source map, after the actual module was evaluated
  ['mocked, actual kept', "import { vi } from 'vitest';\nvi.mock('../src/when.ts', async () => ({ ...(await vi.importActual('../src/when.ts')) }));\nimport { when } from '../src/when.ts';\ntest('when', () => { expect(when()).toBeGreaterThan(0); });"],
]) {
  test(`vitest with ts-node's source-map support installed: a Date call's site is its source line (${name}) (D7)`, T, () => {
    // protects= the recorded site is the source line of the call, whatever stack formatter the project installed and
    // whatever was formatted before; fails_when= the site is the transformed line (or another), as on alakajam
    const dir = fixture(`p2-site-map-${name.replace(/[^a-z]+/g, '-')}`, body);
    const r = run('vitest', dir, ['--det', '--det-workers=1', '--det-epoch=fixed']);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const sites = dateSites(r);
    assert.ok(sites.length > 0, JSON.stringify(r.trace.tests.map((t) => t.events)));
    for (const s of sites) assert.equal(s, `src/when.ts:${DATE_LINE}`, JSON.stringify(sites));
  });
}

test('vitest, Vite\'s own interceptor: a Date call in a mocked module\'s actual code has its source line (D7)', T, () => {
  // protects= the site of a call in the actual code of a module that a test mocks (vi.importActual, a .js specifier for
  // the .ts file, imported through a project module: codex-multi-auth's lib/storage.ts) is its source line; the actual
  // module is evaluated first, then the mocked one is fetched: Vitest's mocker then gives the same module node the
  // mock's meta (no code, no source map); fails_when= that makes the site the transformed line
  const body = "import { vi } from 'vitest';\nvi.mock('../src/when.js', async () => (await import('./helper.mjs')).whenMock());\ntest('when', async () => {\n  await vi.importActual('../src/when.js');\n  const { use } = await import('../src/user.ts');\n  expect(use()).toBeGreaterThan(0);\n});";
  const dir = fixture('p2-site-map-mock-vite', body, { tsNode: false });
  const r = run('vitest', dir, ['--det', '--det-workers=1', '--det-epoch=fixed']);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const sites = dateSites(r);
  assert.ok(sites.length > 0, JSON.stringify(r.trace.tests.map((t) => t.events)));
  for (const s of sites) assert.equal(s, `src/when.ts:${DATE_LINE}`, JSON.stringify(sites));
});
