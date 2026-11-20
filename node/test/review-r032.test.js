'use strict';
// Review R-032 (claude/all-runners): adversarial wrong-reuse attacks on the Node runner adapters.
// Shape (runner-helpers.noWrongReuse): run 1 records, run 2 reuses the file, ONE input changes so that a fresh run
// fails, run 3 (cached) must not reuse the file. Run: cd node && node --test --test-concurrency=1 test/review-r032.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { write, fixture, crun, show, reused, noWrongReuse } = require('./runner-helpers');

const T = { timeout: 600000 };
const NT_HEAD = "import { test } from 'node:test'; import assert from 'node:assert/strict'; import fs from 'node:fs'; import os from 'node:os'; import crypto from 'node:crypto'; import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);";
const MO_HEAD = "import assert from 'node:assert/strict'; import fs from 'node:fs'; import os from 'node:os'; import crypto from 'node:crypto'; import { createRequire } from 'node:module'; const require = createRequire(import.meta.url); const test = (n, f) => it(n, f);";
const RUNNERS = {
  'node-test': { file: (n) => `tests/${n}.test.mjs`, head: NT_HEAD },
  mocha: { file: (n) => `test/${n}.spec.mjs`, head: MO_HEAD },
};
const proj = (r, name, files) => fixture('review-r032', `${r}-${name}`, files);

/** Like noWrongReuse, but a file the engine refuses to cache (never reused) also passes: sound, coarse. */
function noWrongReuseOrUncached(R, dir, f, change, o = {}) {
  const r1 = crun(R, dir, o.args || [], { env: o.env });
  assert.equal(r1.status, 0, show(r1));
  const r2 = crun(R, dir, o.args || [], { env: o.env });
  if (!reused(r2).includes(f)) return 'uncached';
  return noWrongReuse(R, dir, f, change, o);
}

for (const [R, { file, head }] of Object.entries(RUNNERS)) {
  const tf = (n, body) => ({ [file(n)]: `${head}\n${body}\n` });

  describe(`${R}: absent inputs resolved by Node in C++ (package.json)`, () => {
    test('N1 workspace package "exports" retargeted (both targets exist)', T, () => {
      const dir = proj(R, 'exports', {
        'packages/foo/package.json': JSON.stringify({ name: 'foo', exports: { './x': './a.js' } }),
        'packages/foo/a.js': 'exports.v = 1;\n', 'packages/foo/b.js': 'exports.v = 2;\n',
        ...tf('e', "test('e', () => { assert.equal(require('foo/x').v, 1); });"),
      });
      fs.mkdirSync(path.join(dir, 'node_modules'), { recursive: true });
      fs.symlinkSync('../packages/foo', path.join(dir, 'node_modules', 'foo'));
      noWrongReuse(R, dir, file('e'), { 'packages/foo/package.json': JSON.stringify({ name: 'foo', exports: { './x': './b.js' } }) });
    });

    test('N2 nested package.json "imports" (#alias) retargeted', T, () => {
      const dir = proj(R, 'imports', {
        'lib/package.json': JSON.stringify({ name: 'lib', imports: { '#v': './one.js' } }),
        'lib/one.js': 'exports.v = 1;\n', 'lib/two.js': 'exports.v = 2;\n',
        'lib/index.js': "exports.v = require('#v').v;\n",
        ...tf('i', "test('i', () => { assert.equal(require('../lib/index.js').v, 1); });"),
      });
      noWrongReuse(R, dir, file('i'), { 'lib/package.json': JSON.stringify({ name: 'lib', imports: { '#v': './two.js' } }) });
    });

    test('N3 a nested package.json with "type": "module" appears (module format of lib/x.js changes)', T, () => {
      const dir = proj(R, 'type-appears', {
        'lib/x.js': 'exports.v = 1;\n',
        ...tf('t', "test('t', () => { assert.equal(require('../lib/x.js').v, 1); });"),
      });
      noWrongReuse(R, dir, file('t'), { 'lib/package.json': JSON.stringify({ type: 'module' }) });
    });

    test('N4 an optional module appears inside an existing node_modules', T, () => {
      const dir = proj(R, 'optional-nm', {
        'node_modules/.keep': '',
        ...tf('o', "test('o', () => { let v = 'none'; try { v = require('optdep-r032').v; } catch {} assert.equal(v, 'none'); });"),
      });
      noWrongReuseOrUncached(R, dir, file('o'), { 'node_modules/optdep-r032/package.json': '{"name":"optdep-r032","main":"i.js"}', 'node_modules/optdep-r032/i.js': 'exports.v = 1;\n' });
    });

    test('N5 require.resolve probe of an optional module', T, () => {
      const dir = proj(R, 'resolve-probe', {
        'node_modules/.keep': '',
        ...tf('p', "test('p', () => { let ok = true; try { require.resolve('optdep2-r032'); ok = false; } catch {} assert.ok(ok); });"),
      });
      noWrongReuseOrUncached(R, dir, file('p'), { 'node_modules/optdep2-r032/index.js': 'exports.v = 1;\n' });
    });
  });

  describe(`${R}: environment read in C (libuv), entropy`, () => {
    test('N8b entropy through WebCrypto subtle.generateKey (OS randomness in C++) makes the file not cached', T, () => {
      const dir = proj(R, 'entropy-subtle', tf('r', "test('r', async () => { const k = await globalThis.crypto.subtle.generateKey({ name: 'HMAC', hash: 'SHA-256', length: 256 }, true, ['sign']); const raw = new Uint8Array(await globalThis.crypto.subtle.exportKey('raw', k)); console.log('KEY', raw[0]); assert.equal(raw.length, 32); });"));
      const r1 = crun(R, dir, []);
      assert.equal(r1.status, 0, show(r1));
      const r2 = crun(R, dir, []);
      assert.ok(!reused(r2).includes(file('r')), `a test that drew OS entropy (subtle.generateKey) was reused\n${show(r2)}`);
    });

    test('N6 os.homedir() reads HOME through libuv, not process.env', T, () => {
      const dir = proj(R, 'homedir', tf('h', "test('h', () => { assert.equal(fs.existsSync(os.homedir() + '/.r032flag'), false); });"));
      const home2 = path.join(dir, 'home2');
      write(home2, { '.r032flag': '' });
      noWrongReuse(R, dir, file('h'), null, { env: { HOME: '/root' }, env3: { HOME: home2 } });
    });

    test('N7 os.userInfo().homedir (passwd database, not HOME) — machine fact', T, () => {
      const dir = proj(R, 'userinfo', tf('u', "test('u', () => { assert.ok(os.userInfo().username.length > 0); });"));
      const r1 = crun(R, dir, []);
      assert.equal(r1.status, 0, show(r1));
    });

    // getRandomValues / randomUUID are seeded by Level 0 (src/seeds.js): reuse is sound for them
    for (const [name, expr] of [
      ['randomBytes', 'crypto.randomBytes(1)[0]'],
      ['randomInt', 'crypto.randomInt(256)'],
      ['randomFillSync', 'crypto.randomFillSync(Buffer.alloc(1))[0]'],
    ]) {
      test(`N8 entropy (${name}) makes the file not cached`, T, () => {
        const dir = proj(R, `entropy-${name}`, tf('r', `test('r', () => { assert.ok(${expr} >= 0); });`));
        const r1 = crun(R, dir, []);
        assert.equal(r1.status, 0, show(r1));
        const r2 = crun(R, dir, []);
        assert.ok(!reused(r2).includes(file('r')), `a test that drew real entropy was reused\n${show(r2)}`);
      });
    }
  });
}

describe('mocha: configuration file absent then present', () => {
  const MO = (n, body) => ({ [`test/${n}.spec.mjs`]: `${MO_HEAD}\n${body}\n` });
  test('N9 .mocharc.json appears (adds a --require setup that sets a global)', T, () => {
    const dir = proj('mocha', 'mocharc-appears', {
      'setup.cjs': "globalThis.LEVEL = 'b';\n",
      ...MO('m', "test('m', () => { assert.equal(globalThis.LEVEL, undefined); });"),
    });
    noWrongReuse('mocha', dir, 'test/m.spec.mjs', { '.mocharc.json': JSON.stringify({ require: ['./setup.cjs'] }) });
  });
  test('N10 .mocharc.yml appears next to an existing .mocharc.json? (precedence: .mocharc.js wins)', T, () => {
    const dir = proj('mocha', 'mocharc-precedence', {
      '.mocharc.json': JSON.stringify({ spec: ['test/*.spec.mjs'] }),
      'setup.cjs': "globalThis.LEVEL = 'b';\n",
      ...MO('m', "test('m', () => { assert.equal(globalThis.LEVEL, undefined); });"),
    });
    noWrongReuse('mocha', dir, 'test/m.spec.mjs', { '.mocharc.js': "module.exports = { spec: ['test/*.spec.mjs'], require: ['./setup.cjs'] };\n" });
  });
});

// "failed tests are never reused": a file whose tests all pass but whose process fails afterwards
describe('failure outside a test body', () => {
  const cases = {
    'exitCode set at module level': 'process.exitCode = 3;',
    'late uncaught exception': "setTimeout(() => { throw new Error('late'); }, 50);",
    'late unhandled rejection': "setTimeout(() => { Promise.reject(new Error('late')); }, 50);",
    'process.exit(2) on beforeExit': "process.once('beforeExit', () => process.exit(2));",
  };
  for (const [R, { file, head }] of Object.entries(RUNNERS)) {
    for (const [name, code] of Object.entries(cases)) {
      test(`${R}: ${name}`, T, () => {
        const dir = proj(R, `late-${name.replace(/\W+/g, '-')}`, { [file('f')]: `${head}\n${code}\ntest('f', () => {});\n` });
        const fresh = crun(R, dir, [], { cache: false });
        if (fresh.status === 0) { console.log(`R032-LATE ${R} ${name}: runner ignores it`); return; }
        console.log(`R032-LATE ${R} ${name}: fresh run fails`);
        const r1 = crun(R, dir, []);
        assert.notEqual(r1.status, 0, show(r1));
        const r2 = crun(R, dir, []);
        assert.ok(!reused(r2).includes(file('f')), `WRONG REUSE: a file whose process fails was reused\n${show(r2)}`);
        assert.notEqual(r2.status, 0, `the cached run exits 0 where every fresh run fails\n${show(r2)}`);
      });
    }
  }
});
