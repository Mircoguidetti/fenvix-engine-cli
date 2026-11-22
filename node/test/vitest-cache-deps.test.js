'use strict';
// Vitest 5 writes its own cache under node_modules/.vitest-cache/ on every run. It is the runner's output, not
// installed code: `inputs.deps` (src/loaded.js) must not change because of it, and its content must not change
// what a --det run does (file order: DetSequencer in src/vitest/cli.js; outcomes).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./helpers');

const vitestMajor = Number(require('vitest/package.json').version.split('.')[0]);
const skip = !h.RUNNERS.includes('vitest') ? 'vitest not selected' : vitestMajor < 5 ? `vitest ${vitestMajor} (no .vitest-cache)` : false;

function withNodeModules(dir) {
  // a project with its own node_modules: one installed package
  fs.mkdirSync(path.join(dir, 'node_modules', 'tiny'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'node_modules', 'tiny', 'package.json'), JSON.stringify({ name: 'tiny', version: '1.0.0', main: 'index.js' }));
  fs.writeFileSync(path.join(dir, 'node_modules', 'tiny', 'index.js'), 'module.exports = 41;\n');
  return dir;
}

function deps(r) {
  assert.strictEqual(r.status, 0, `${r.stdout}\n${r.stderr}`);
  const d = r.trace && r.trace.header && r.trace.header.meta && r.trace.header.meta.inputs && r.trace.header.meta.inputs.deps;
  assert.ok(d, 'inputs.deps in the trace header');
  return d;
}

function listing(dir) {
  const out = [];
  const walk = (d, rel) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) walk(path.join(d, e.name), r);
      else out.push(`${r} ${fs.readFileSync(path.join(d, e.name)).toString('base64')}`);
    }
  };
  if (fs.existsSync(dir)) walk(dir, '');
  return out.sort().join('\n');
}

test('inputs.deps: two serial --det runs of a Vitest 5 project are equal (node_modules/.vitest-cache is not a dependency)', { skip }, () => {
  const dir = withNodeModules(h.project('vitest', 'vitest-cache-deps', {
    a: "import tiny from 'tiny';\ntest('a', () => { expect(tiny + 1).toBe(42); });",
    b: "test('b', () => { expect(2).toBe(2); });",
  }));
  const r1 = h.run('vitest', dir, ['--det']);
  const d1 = deps(r1);
  assert.ok(fs.existsSync(path.join(dir, 'node_modules', '.vitest-cache')), 'Vitest wrote node_modules/.vitest-cache');
  // only the installed package's two files are dependencies (not Vitest's cache files)
  assert.match(d1, /^2 files /, 'inputs.deps counts the installed files only');
  const r2 = h.run('vitest', dir, ['--det']);
  assert.strictEqual(deps(r2), d1, 'inputs.deps of the second serial run');
  // a test file edited and reverted between two runs: Vitest adds a cache entry for the edited content,
  // the sources and the installed packages are the same as in run 1
  const bFile = path.join(dir, 'tests', 'b.test.mjs');
  const bBody = fs.readFileSync(bFile, 'utf8');
  fs.writeFileSync(bFile, bBody.replace("expect(2).toBe(2)", "expect(2).toBe(2); expect(3).toBe(3)"));
  deps(h.run('vitest', dir, ['--det']));
  fs.writeFileSync(bFile, bBody);
  const r3 = h.run('vitest', dir, ['--det']);
  assert.strictEqual(deps(r3), d1, 'inputs.deps of a serial run after an edit-and-revert of a test file');
  // a real change to the installed packages still changes it
  fs.writeFileSync(path.join(dir, 'node_modules', 'tiny', 'index.js'), 'module.exports = 41; // patched\n');
  const d4 = deps(h.run('vitest', dir, ['--det']));
  assert.notStrictEqual(d4, d1, 'inputs.deps after a change to an installed package');
});

test('--det: a different node_modules/.vitest-cache (and a recorded failure) changes neither file order nor outcomes', { skip }, () => {
  const PASS_C = "test('c1', () => { expect(3).toBe(3); });\ntest('c2', () => { expect('c').toBe('c'); });";
  const FAIL_C = "test('c1', () => { expect(3).toBe(4); });\ntest('c2', () => { expect('c').toBe('d'); });";
  const dir = withNodeModules(h.project('vitest', 'vitest-cache-order', {
    a: "test('a', () => { expect(1).toBe(1); });",
    b: "import tiny from 'tiny';\ntest('b', () => { expect(tiny).toBe(41); });",
    c: PASS_C,
  }));
  const nm = path.join(dir, 'node_modules');
  const cFile = path.join(dir, 'tests', 'c.test.mjs');
  const header = fs.readFileSync(cFile, 'utf8').split(`\n${PASS_C}`)[0];
  const observe = (r) => {
    assert.ok(r.trace, `${r.stdout}\n${r.stderr}`);
    return { order: r.trace.tests.map((t) => t.nodeid), digest: r.trace.header.order, outcomes: r.outcomes };
  };

  // run A: no Vitest cache at all
  fs.rmSync(path.join(nm, '.vitest-cache'), { recursive: true, force: true });
  fs.rmSync(path.join(nm, '.vite'), { recursive: true, force: true });
  const before = listing(path.join(nm, '.vitest-cache'));
  const rA = h.run('vitest', dir, ['--det']);
  assert.strictEqual(rA.status, 0, `${rA.stdout}\n${rA.stderr}`);
  const A = observe(rA);

  // a run where c fails: Vitest caches the failing module and records the failure (plain Vitest runs it first next time)
  fs.writeFileSync(cFile, `${header}\n${FAIL_C}\n`);
  const rF = h.run('vitest', dir, ['--det']);
  assert.notStrictEqual(rF.status, 0, 'the failing run fails');
  assert.deepStrictEqual(h.failed(rF).sort(), ['c.test.mjs > c1', 'c.test.mjs > c2']);
  fs.writeFileSync(cFile, `${header}\n${PASS_C}\n`);

  // precondition: the cache differs from run A's (proved, not assumed), and a failure of c is on record
  const cacheB = listing(path.join(nm, '.vitest-cache'));
  assert.notStrictEqual(cacheB, before, '.vitest-cache before run B differs from before run A');
  assert.ok(cacheB.length > 0, '.vitest-cache is not empty before run B');
  const results = fs.readdirSync(path.join(nm, '.vite', 'vitest'), { recursive: true }).filter((f) => String(f).endsWith('results.json'));
  assert.ok(results.length, 'Vitest results cache exists');
  const recorded = JSON.parse(fs.readFileSync(path.join(nm, '.vite', 'vitest', String(results[0])), 'utf8'));
  const files = Object.values(recorded.projects || {}).flatMap((p) => Object.entries(p.files || {}));
  assert.ok(files.some(([f, v]) => f.endsWith('c.test.mjs') && v.failed === true), 'the failure of c is recorded');

  // run B: same sources as run A, different Vitest cache
  const rB = h.run('vitest', dir, ['--det']);
  assert.strictEqual(rB.status, 0, `${rB.stdout}\n${rB.stderr}`);
  const B = observe(rB);
  assert.deepStrictEqual(B.order, A.order, 'test order');
  assert.deepStrictEqual(B.digest, A.digest, 'trace header order');
  assert.deepStrictEqual(B.outcomes, A.outcomes, 'every outcome');
  assert.deepStrictEqual(Object.values(A.outcomes), ['passed', 'passed', 'passed', 'passed']);
  const fileOrder = [...new Set(A.order.map((n) => n.split('::')[0]))];
  assert.deepStrictEqual(fileOrder.map((f) => path.basename(f)), ['a.test.mjs', 'b.test.mjs', 'c.test.mjs'], 'files by path');
});
