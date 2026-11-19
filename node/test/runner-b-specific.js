'use strict';
// Runner-specific wrong-reuse tests of the tap, AVA, Jasmine and uvu shells: configuration files, setup / helper
// files, snapshot files, the runners' own fixture and mock helpers, plugins, loaders (tsx and tsconfig), test-name
// filters, file isolation of shared-process runners.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { fixture, tfile, write, crun, show, reused, noWrongReuse, neverCached, RUNNERS } = require('./runner-b-cases');

/** A plain (no detjs) run of the runner's CLI in a fixture, to create or update snapshots. */
function plain(dir, args, env = {}) {
  const e = { ...process.env, ...env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT']) delete e[k];
  const r = spawnSync(process.execPath, args, { cwd: dir, encoding: 'utf8', env: e, timeout: 300000 });
  assert.equal(r.status, 0, `plain run ${args.join(' ')}: ${r.stdout.slice(-2000)}\n${r.stderr.slice(-2000)}`);
  return r;
}

const bin = (dir, rel) => path.join(dir, 'node_modules', rel);
const TSCONFIG = (target) => JSON.stringify({ compilerOptions: { baseUrl: '.', paths: { '@lib/*': [`src/${target}/*`] } } });
const LIB = { 'src/one/v.ts': "export const v: number = 1;\n", 'src/two/v.ts': "export const v: number = 2;\n" };

// -- tap -------------------------------------------------------------------------------------------------------------
const TAPHEAD = "const t = require('tap'); const fs = require('node:fs');";
const tap = [
  ['.taprc: test-env changes', () => {
    const dir = fixture('tap', 'taprc', { 'test/env.test.js': `${TAPHEAD}\nt.equal(process.env.RB_TAPENV, 'a');\n` }, { config: 'test-env:\n  - RB_TAPENV=a\n' });
    noWrongReuse('tap', dir, 'test/env.test.js', { '.taprc': 'allow-incomplete-coverage: true\ntest-env:\n  - RB_TAPENV=b\n' });
  }],
  ['setup module preloaded with node-arg: its content changes', () => {
    const dir = fixture('tap', 'node-arg', {
      'setup.js': "globalThis.RB_SETUP = 'one';\n",
      'test/setup.test.js': `${TAPHEAD}\nt.equal(globalThis.RB_SETUP, 'one');\n`,
    }, { config: 'node-arg:\n  - --require=./setup.js\n' });
    noWrongReuse('tap', dir, 'test/setup.test.js', { 'setup.js': "globalThis.RB_SETUP = 'two';\n" });
  }],
  ['snapshot file (tap-snapshots/) changes', () => {
    const dir = fixture('tap', 'snapshot', {
      'data/v.txt': 'one',
      'test/snap.test.js': `${TAPHEAD}\nt.test('snap', async (t) => { t.matchSnapshot(fs.readFileSync('data/v.txt', 'utf8')); });\n`,
    });
    const tapBin = bin(dir, 'tap/dist/esm/run.mjs');
    plain(dir, [tapBin, '--snapshot', '--disable-coverage']);
    assert.ok(fs.existsSync(path.join(dir, 'tap-snapshots', 'test', 'snap.test.js.test.cjs')), 'snapshot written');
    noWrongReuse('tap', dir, 'test/snap.test.js', () => {
      write(dir, { 'data/v.txt': 'two' });
      plain(dir, [tapBin, '--snapshot', '--disable-coverage']);
      write(dir, { 'data/v.txt': 'one' });
    });
  }],
  ['t.testdir fixture: written and read by the test itself, keyed by what it was made from', () => {
    const dir = fixture('tap', 'testdir', {
      'data/v.txt': 'one',
      'test/fx.test.js': `${TAPHEAD}\nconst path = require('node:path');\nt.test('fx', async (t) => { const d = t.testdir({ 'a.txt': fs.readFileSync('data/v.txt', 'utf8') }); t.equal(fs.readFileSync(path.join(d, 'a.txt'), 'utf8'), 'one'); t.equal(fs.readdirSync(d).length, 1); });\n`,
    });
    noWrongReuse('tap', dir, 'test/fx.test.js', { 'data/v.txt': 'two' });
  }],
  ['t.mockRequire: the module loaded through tap\'s mock loader changes', () => {
    const dir = fixture('tap', 'mock', {
      'src/a.js': "const b = require('./b.js'); module.exports = () => b.v * 10;\n",
      'src/b.js': 'module.exports = { v: 1 };\n',
      'test/mock.test.js': `${TAPHEAD}\nt.test('mock', async (t) => { const a = t.mockRequire('../src/a.js', { '../src/b.js': { v: 2 } }); t.equal(a(), 20); });\n`,
    });
    noWrongReuse('tap', dir, 'test/mock.test.js', { 'src/a.js': "const b = require('./b.js'); module.exports = () => b.v * 100;\n" });
  }],
  ['loader: tsx with tsconfig paths, the tsconfig changes', () => {
    const dir = fixture('tap', 'tsx', {
      ...LIB, 'tsconfig.json': TSCONFIG('one'),
      'test/ts.test.js': `${TAPHEAD}\nt.equal(require('@lib/v').v, 1);\n`,
    }, { config: 'node-arg:\n  - --import=tsx\n' });
    noWrongReuse('tap', dir, 'test/ts.test.js', { 'tsconfig.json': TSCONFIG('two') });
  }],
  ['test-name filter (--grep) changes', () => {
    const dir = fixture('tap', 'grep', { 'test/g.test.js': `${TAPHEAD}\nt.test('first', async (t) => t.pass());\nt.test('second', async (t) => t.fail('second fails'));\n` });
    noWrongReuse('tap', dir, 'test/g.test.js', () => {}, { args: ['--grep=first'], args3: ['--grep=second'] });
  }],
  ['never cached: a tap before script', () => {
    const dir = fixture('tap', 'before', { 'before.js': "require('node:fs').writeFileSync('data.txt', 'x');\n", 'test/b.test.js': `${TAPHEAD}\nt.equal(fs.readFileSync('data.txt', 'utf8'), 'x');\n` },
      { config: 'before: before.js\n' });
    const r1 = crun('tap', dir);
    assert.equal(r1.status, 0, show(r1));
    const r2 = crun('tap', dir);
    assert.ok(!reused(r2).includes('test/b.test.js'), show(r2));
    assert.match(JSON.stringify(r2.summary.misses), /before\/after script/);
  }],
  ['plugin set (.taprc plugin) changes', () => {
    const dir = fixture('tap', 'plugin', { 'test/p.test.js': `${TAPHEAD}\nt.test('p', async (t) => { t.equal(typeof t.testdir, 'function'); });\n` });
    try {
      noWrongReuse('tap', dir, 'test/p.test.js', { '.taprc': 'allow-incomplete-coverage: true\nplugin:\n  - "!@tapjs/fixture"\n' });
    } finally {
      // the plugin build is shared by every fixture (node_modules link): rebuild the default set
      write(dir, { '.taprc': 'allow-incomplete-coverage: true\n' });
      plain(dir, [bin(dir, 'tap/dist/esm/run.mjs'), 'build']);
    }
  }],
];

// -- AVA -------------------------------------------------------------------------------------------------------------
const AVAHEAD = "import test from 'ava'; import fs from 'node:fs';";
const ava = [
  ['ava.config.mjs: environmentVariables change', () => {
    const dir = fixture('ava', 'config', { 'test/env.test.mjs': `${AVAHEAD}\ntest('env', (t) => { t.is(process.env.RB_AVA, 'a'); });\n` }, { config: " environmentVariables: { RB_AVA: 'a' } " });
    noWrongReuse('ava', dir, 'test/env.test.mjs', { 'ava.config.mjs': "export default { environmentVariables: { RB_AVA: 'b' } };\n" });
  }],
  ['require (setup file) content changes', () => {
    const dir = fixture('ava', 'require', {
      'setup.mjs': "globalThis.RB_SETUP = 'one';\n",
      'test/setup.test.mjs': `${AVAHEAD}\ntest('setup', (t) => { t.is(globalThis.RB_SETUP, 'one'); });\n`,
    }, { config: " require: ['./setup.mjs'] " });
    noWrongReuse('ava', dir, 'test/setup.test.mjs', { 'setup.mjs': "globalThis.RB_SETUP = 'two';\n" });
  }],
  ['snapshot file (snapshots/*.snap) changes', () => {
    const dir = fixture('ava', 'snapshot', {
      'data/v.txt': 'one',
      'test/snap.test.mjs': `${AVAHEAD}\ntest('snap', (t) => { t.snapshot(fs.readFileSync('data/v.txt', 'utf8')); });\n`,
    });
    const avaBin = bin(dir, 'ava/entrypoints/cli.js');
    plain(dir, [avaBin]);
    noWrongReuse('ava', dir, 'test/snap.test.mjs', () => {
      write(dir, { 'data/v.txt': 'two' });
      plain(dir, [avaBin, '--update-snapshots']);
      write(dir, { 'data/v.txt': 'one' });
    });
  }],
  ['loader: nodeArguments --import=tsx with tsconfig paths, the tsconfig changes', () => {
    const dir = fixture('ava', 'tsx', {
      ...LIB, 'tsconfig.json': TSCONFIG('one'),
      'test/ts.test.mjs': `${AVAHEAD}\nimport { v } from '@lib/v';\ntest('ts', (t) => { t.is(v, 1); });\n`,
    }, { config: " nodeArguments: ['--import=tsx'] " });
    noWrongReuse('ava', dir, 'test/ts.test.mjs', { 'tsconfig.json': TSCONFIG('two') });
  }],
  ['test-name filter (--match) changes', () => {
    const dir = fixture('ava', 'match', { 'test/m.test.mjs': `${AVAHEAD}\ntest('first', (t) => t.pass());\ntest('second', (t) => t.fail());\n` });
    noWrongReuse('ava', dir, 'test/m.test.mjs', () => {}, { args: ['--match=first'], args3: ['--match=second'] });
  }],
  ['worker processes (--no-worker-threads): a data file read changes', () => {
    const dir = fixture('ava', 'processes', { 'data/msg.txt': 'hello', ...tfile('ava', 'proc', "test('proc', () => { expect(fs.readFileSync('data/msg.txt', 'utf8')).toBe('hello'); });") });
    noWrongReuse('ava', dir, 'test/proc.test.mjs', { 'data/msg.txt': 'bye' }, { args: ['--no-worker-threads'] });
  }],
  ['worker threads: a worker thread started by the test is never cached', () => {
    const dir = fixture('ava', 'thread', { ...tfile('ava', 'wt', "const { Worker } = require('node:worker_threads');\ntest('wt', async () => { const w = new Worker('require(\"node:worker_threads\").parentPort.postMessage(1)', { eval: true }); expect(await new Promise((r) => w.once('message', r))).toBe(1); await w.terminate(); });") });
    neverCached('ava', dir, 'test/wt.test.mjs', /worker thread/);
  }],
];

// -- Jasmine ---------------------------------------------------------------------------------------------------------
const jasmine = [
  ['jasmine.json: env option changes', () => {
    const dir = fixture('jasmine', 'config', { 'spec/noexpSpec.js': "it('no expectations', () => {});\n" }, { config: { env: { random: true, failSpecWithNoExpectations: false } } });
    noWrongReuse('jasmine', dir, 'spec/noexpSpec.js', { 'spec/support/jasmine.json': JSON.stringify({ spec_dir: 'spec', spec_files: ['**/*Spec.js'], helpers: ['helpers/**/*.js'], env: { random: true, failSpecWithNoExpectations: true } }) });
  }],
  ['helper file content changes', () => {
    const dir = fixture('jasmine', 'helper', {
      'spec/helpers/setup.js': "globalThis.RB_SETUP = 'one';\n",
      'spec/hSpec.js': "it('helper', () => { expect(globalThis.RB_SETUP).toBe('one'); });\n",
    });
    noWrongReuse('jasmine', dir, 'spec/hSpec.js', { 'spec/helpers/setup.js': "globalThis.RB_SETUP = 'two';\n" });
  }],
  ['a new helper file matching the helpers glob', () => {
    const dir = fixture('jasmine', 'new-helper', { 'spec/helpers/a.js': "globalThis.RB_H = 'a';\n", 'spec/nhSpec.js': "it('nh', () => { expect(globalThis.RB_H).toBe('a'); });\n" });
    noWrongReuse('jasmine', dir, 'spec/nhSpec.js', { 'spec/helpers/b.js': "globalThis.RB_H = 'b';\n" });
  }],
  ['test-name filter (--filter) changes', () => {
    const dir = fixture('jasmine', 'filter', { 'spec/fSpec.js': "it('first', () => { expect(1).toBe(1); });\nit('second', () => { expect(1).toBe(2); });\n" });
    noWrongReuse('jasmine', dir, 'spec/fSpec.js', () => {}, { args: ['--filter=first'], args3: ['--filter=second'] });
  }],
  ['random: true (Jasmine\'s default) is replaced by declaration order under --det', () => {
    const dir = fixture('jasmine', 'order', { 'spec/oSpec.js': Array.from({ length: 8 }, (_, i) => `it('s${i}', () => { globalThis.n = (globalThis.n || 0) + 1; expect(globalThis.n).toBe(${i + 1}); });`).join('\n') });
    for (let i = 0; i < 3; i++) {
      const r = crun('jasmine', dir, { cache: false });
      assert.equal(r.status, 0, show(r));
    }
  }],
  ['--det-cache runs each spec file in its own process: cross-file state is reported, never reused', () => {
    const dir = fixture('jasmine', 'isolation', {
      'spec/aSpec.js': "it('sets', () => { globalThis.RB_SHARED = 1; expect(1).toBe(1); });\n",
      'spec/bSpec.js': "it('reads', () => { expect(globalThis.RB_SHARED).toBe(1); });\n",
    });
    const single = crun('jasmine', dir, { cache: false });
    assert.equal(single.status, 0, `one process: b sees a's global\n${show(single)}`);
    const r1 = crun('jasmine', dir);
    assert.notEqual(r1.status, 0, `process per file: b fails and is reported\n${show(r1)}`);
    const r2 = crun('jasmine', dir);
    assert.ok(!reused(r2).includes('spec/bSpec.js'), show(r2));
  }],
];

// -- uvu -------------------------------------------------------------------------------------------------------------
const UVUHEAD = "const { test } = require('uvu'); const assert = require('uvu/assert');";
const uvu = [
  ['-r setup module content changes', () => {
    const dir = fixture('uvu', 'require', {
      'setup.js': "globalThis.RB_SETUP = 'one';\n",
      'tests/setup.js': `${UVUHEAD}\ntest('setup', () => { assert.is(globalThis.RB_SETUP, 'one'); });\ntest.run();\n`,
    });
    noWrongReuse('uvu', dir, 'tests/setup.js', { 'setup.js': "globalThis.RB_SETUP = 'two';\n" }, { args: ['-r', path.join(dir, 'setup.js')] });
  }],
  ['command line: the -r module is dropped', () => {
    const dir = fixture('uvu', 'args', {
      'setup.js': "globalThis.RB_SETUP = 'one';\n",
      'tests/args.js': `${UVUHEAD}\ntest('args', () => { assert.is(globalThis.RB_SETUP, 'one'); });\ntest.run();\n`,
    });
    noWrongReuse('uvu', dir, 'tests/args.js', () => {}, { args: ['-r', path.join(dir, 'setup.js')], args3: [] });
  }],
  ['loader: -r tsx/cjs with tsconfig paths, the tsconfig changes', () => {
    const dir = fixture('uvu', 'tsx', {
      ...LIB, 'tsconfig.json': TSCONFIG('one'),
      'tests/ts.js': `${UVUHEAD}\ntest('ts', () => { assert.is(require('@lib/v').v, 1); });\ntest.run();\n`,
    });
    noWrongReuse('uvu', dir, 'tests/ts.js', { 'tsconfig.json': TSCONFIG('two') }, { args: ['-r', 'tsx/cjs'] });
  }],
  ['suites: a named suite\'s data input changes', () => {
    const dir = fixture('uvu', 'suite', {
      'data/v.txt': 'one',
      'tests/suite.js': "const { suite } = require('uvu'); const assert = require('uvu/assert'); const fs = require('node:fs');\nconst S = suite('S');\nS('reads', () => { assert.is(fs.readFileSync('data/v.txt', 'utf8'), 'one'); });\nS.run();\n",
    });
    noWrongReuse('uvu', dir, 'tests/suite.js', { 'data/v.txt': 'two' });
  }],
  ['--det-cache runs each file in its own process: cross-file state is reported, never reused', () => {
    const dir = fixture('uvu', 'isolation', {
      'tests/a.js': `${UVUHEAD}\nglobalThis.RB_SHARED = 1;\ntest('sets', () => { assert.ok(true); });\ntest.run();\n`,
      'tests/b.js': `${UVUHEAD}\ntest('reads', () => { assert.is(globalThis.RB_SHARED, 1); });\ntest.run();\n`,
    });
    const single = crun('uvu', dir, { cache: false });
    assert.equal(single.status, 0, `one process: b sees a's global\n${show(single)}`);
    const r1 = crun('uvu', dir);
    assert.notEqual(r1.status, 0, `process per file: b fails and is reported\n${show(r1)}`);
    const r2 = crun('uvu', dir);
    assert.ok(!reused(r2).includes('tests/b.js'), show(r2));
  }],
];

module.exports = { tap, ava, jasmine, uvu, RUNNERS };
