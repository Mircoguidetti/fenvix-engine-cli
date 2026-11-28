'use strict';
// P2 D7 = B (founder decision 2026-11-28): sites are source lines by construction. Vitest's mocker gives a mocked
// module's node the mock's meta (`{ code: '', mockedModule: true }`, no source map) on the same node that
// vi.importActual evaluated the actual code on, so when the mock's fetch comes last the node no longer carries the map
// of the code that runs (codex-multi-auth lib/storage.ts, `vi.mock` + `importActual` + `vi.resetModules()`). A site
// in that code must still be its source line: the engine keeps, per module file, the code (with its inline map) a node
// carried when the runner set it (sites.watchViteModules), and maps from it when the node no longer has one.
// This drives a real Vite EvaluatedModules graph (the one in Vitest's worker state) directly, so the order is fixed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');

// a TypeScript module whose call is far below its first line once the types are stripped
const TS = `export interface Shape {
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
}
export function where(): string {
  return (globalThis as any).__p2site();
}
`;
const LINE = TS.split('\n').findIndex((l) => l.includes('__p2site')) + 1;

async function moduleOf(file) {
  const esbuild = require('esbuild');
  const r = await esbuild.transform(TS, { loader: 'ts', format: 'cjs', sourcemap: 'inline', sourcefile: file });
  return r.code;
}

test('a site in a module whose node later gets the mocker\'s meta (no map) is its source line (D7)', async () => {
  // protects= the site does not depend on the order in which Vitest's mocker and importActual set the node's meta;
  // fails_when= after the mock's meta replaces the actual code's, the site is the transformed line
  const { EvaluatedModules } = await import('vite/module-runner');
  const sites = require('../src/sites');
  const root = path.join(__dirname, '.tmp', 'p2-vite-map');
  sites.setRoot(root);
  const em = new EvaluatedModules();
  const prevWorker = globalThis.__vitest_worker__;
  globalThis.__vitest_worker__ = { evaluatedModules: em };
  try {
    sites.watchViteModules();
    const out = {};
    for (const [name, mockAfter] of [['kept.ts', false], ['mocked.ts', true]]) {
      const file = path.join(root, 'src', name);
      const node = em.ensureModule(file, `/src/${name}`);
      node.file = file;
      const code = await moduleOf(file);
      node.meta = { code, file, id: file, url: `/src/${name}`, invalidate: false };
      const mod = { exports: {} };
      vm.runInThisContext(`(function (exports, module) {${code}\n})`, { filename: file })(mod.exports, mod);
      // what the mocker does on the same node when the mock's fetch comes after the actual code was evaluated
      if (mockAfter) node.meta = { code: '', file: null, id: file, url: `/src/${name}`, invalidate: false, mockedModule: true };
      globalThis.__p2site = sites.resolve; // the deciding frame is then the module's own
      out[name] = mod.exports.where();
    }
    assert.equal(out['kept.ts'], `src/kept.ts:${LINE}`, JSON.stringify(out));
    assert.equal(out['mocked.ts'], `src/mocked.ts:${LINE}`, JSON.stringify(out));
  } finally {
    globalThis.__vitest_worker__ = prevWorker;
    delete globalThis.__p2site;
  }
});
