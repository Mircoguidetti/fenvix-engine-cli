'use strict';
// claude/all-runners-2: review R-032 F6 (a nested package.json appears) and F7 (OS randomness drawn in native
// crypto) for every Node runner the review's own files do not cover: F7 under tap, AVA, Jasmine and uvu (three
// forms each: WebCrypto subtle.generateKey, crypto.generateKeyPairSync, createECDH().generateKeys), the other two
// F7 forms and F6 under bun test and deno test. node --test and Mocha: test/review-r032.test.js; F6 under tap, AVA,
// Jasmine, uvu: test/review-r032-runners-b.test.js.
// Run: cd node && DETJS_DENO=<deno> node --test --test-concurrency=1 test/all-runners-2-f6f7.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const B = require('./runner-b-cases');
const H = require('./runtime-helpers');

const T = { timeout: 900000 };
const KEYGEN = [
  ['subtle', "const k = await globalThis.crypto.subtle.generateKey({ name: 'HMAC', hash: 'SHA-256', length: 256 }, true, ['sign']); expect(new Uint8Array(await globalThis.crypto.subtle.exportKey('raw', k)).length).toBe(32);"],
  ['keypair', "const { publicKey } = require('node:crypto').generateKeyPairSync('ec', { namedCurve: 'P-256' }); expect(publicKey.asymmetricKeyType).toBe('ec');"],
  ['ecdh', "expect(require('node:crypto').createECDH('prime256v1').generateKeys().length).toBe(65);"],
];

for (const runner of ['tap', 'ava', 'jasmine', 'uvu']) {
  const F = (n) => B.RUNNERS[runner].file(n);
  describe(`${runner}: R-032 F7`, () => {
    for (const [name, body] of KEYGEN) {
      test(`F7 OS randomness in native crypto (${name}) makes the file not cached`, T, () => {
        const dir = B.fixture(runner, `ar2-f7-${name}`, { ...B.tfile(runner, 'en', `test('en', async () => { ${body} });`) });
        B.neverCached(runner, dir, F('en'), /OS randomness drawn in native crypto/);
      });
    }
  });
}

function entropyNotReused(rt, dir, file) {
  const r1 = H.crun(rt, dir);
  assert.equal(r1.status, 0, H.show(r1));
  const r2 = H.crun(rt, dir);
  assert.equal(r2.status, 0, H.show(r2));
  assert.ok(!H.reused(r2).includes(file), `a file that drew OS randomness in native crypto was reused\n${H.show(r2)}`);
}

/** F6 under a runtime: the cached run agrees with a fresh run after a nested package.json appears. */
function agreesAfter(rt, dir, change) {
  const r1 = H.crun(rt, dir);
  assert.equal(r1.status, 0, H.show(r1));
  H.write(dir, change);
  const fresh = H.crun(rt, dir, { cache: false });
  const cached = H.crun(rt, dir);
  assert.equal(cached.status, fresh.status, `cached run must agree with the fresh run\n${H.show(cached)}\n${H.show(fresh)}`);
}

describe('bun: R-032 F6/F7', { skip: H.BINARY.bun ? false : 'no bun' }, () => {
  const RT = 'bun';
  const tf = (n, body) => ({ [`test/${n}.test.js`]: `import { test, expect } from 'bun:test';\nimport { createRequire } from 'node:module';\nconst require = createRequire(import.meta.url);\n${body}\n` });
  const F = (n) => `test/${n}.test.js`;
  for (const [name, body] of KEYGEN.slice(1)) {
    test(`F7 OS randomness in native crypto (${name})`, T, () => {
      const dir = H.fixture(RT, `ar2-f7-${name}`, { ...tf('k', `test('k', async () => { ${body} });`) });
      entropyNotReused(RT, dir, F('k'));
    });
  }
  test('F6 a nested package.json with "type": "module" appears (lib/x.js)', T, () => {
    const dir = H.fixture(RT, 'ar2-f6', { 'lib/x.js': 'exports.v = 1;\n',
      ...tf('nt', "test('nt', () => { expect(require('../lib/x.js').v).toBe(1); });") });
    agreesAfter(RT, dir, { 'lib/package.json': JSON.stringify({ type: 'module' }) });
  });
});

describe('deno: R-032 F6/F7', { skip: H.BINARY.deno ? false : 'no deno' }, () => {
  const RT = 'deno';
  const tf = (n, body) => ({ [`tests/${n}_test.ts`]: `import { createRequire } from 'node:module';\nconst require = createRequire(import.meta.url);\nconst expect = (a: unknown) => ({ toBe: (b: unknown) => { if (a !== b) throw new Error(String(a) + ' !== ' + String(b)); } });\n${body}\n` });
  const F = (n) => `tests/${n}_test.ts`;
  for (const [name, body] of KEYGEN.slice(1)) {
    test(`F7 OS randomness in native crypto (${name})`, T, () => {
      const dir = H.fixture(RT, `ar2-f7-${name}`, { ...tf('k', `Deno.test('k', async () => { ${body} });`) });
      entropyNotReused(RT, dir, F('k'));
    });
  }
  test('F6 a nested package.json with "type": "module" appears (lib/x.js)', T, () => {
    const dir = H.fixture(RT, 'ar2-f6', { 'lib/x.js': 'exports.v = 1;\n',
      ...tf('nt', "Deno.test('nt', () => { expect(require('../lib/x.js').v).toBe(1); });") });
    agreesAfter(RT, dir, { 'lib/package.json': JSON.stringify({ type: 'module' }) });
  });
});
