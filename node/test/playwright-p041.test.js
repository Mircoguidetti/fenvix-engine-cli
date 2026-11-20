'use strict';
// `detjs playwright` (audit G-0406, G-0455): Playwright Test under --det with per-test brackets and one trace, the
// repro options (--det-order, --det-outcomes, --det-collect) and the order seed (G-1459). Tests that open a page
// need Chromium (PLAYWRIGHT_BROWSERS_PATH or Playwright's cache); they are skipped, with the reason, without it.
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { TMP, BIN, NODE_DIR } = require('./helpers');

const T = { timeout: 600000 };

function chromium() {
  try {
    const pw = require(require.resolve('playwright-core', { paths: [NODE_DIR] }));
    const exe = pw.chromium.executablePath();
    return fs.existsSync(exe) ? null : `Chromium not installed (${exe})`;
  } catch (e) {
    return `playwright not installed in node/ (${e.message})`;
  }
}
const NO_BROWSER = chromium();
let HAVE_PW = true;
try { require.resolve('@playwright/test/package.json', { paths: [NODE_DIR] }); } catch { HAVE_PW = false; }

const A = `import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const cache = new Map();
function mark(n) { fs.appendFileSync(path.join(__dirname, '..', 'ran'), n + '\\n'); }
test('victim', async () => { mark('victim'); expect(cache.size).toBe(0); });
test.describe('g', () => {
  test.beforeAll(() => mark('beforeAll-g'));
  test('polluter', async () => { mark('polluter'); cache.set('k', 1); });
  test('f2', async () => { mark('f2'); });
});
test('draw', async () => { mark('draw'); fs.writeFileSync(path.join(__dirname, '..', 'draw-' + process.env.DETJS_SEED + '-' + (process.env.DETJS_ORDER_SEED || '-')), String(Math.random())); });
test('fails', async () => { mark('fails'); expect(1).toBe(2); });
test('after-failure', async () => { mark('after-failure'); });
`;
const B = `import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
test('b1', async () => { fs.appendFileSync(path.join(__dirname, '..', 'ran'), 'b1\\n'); });
`;
const PAGE = `import { test, expect } from '@playwright/test';
test('page', async ({ page }) => {
  await page.setContent('<p id="x">' + (Math.random() < 2 ? 'hi' : 'no') + '</p>');
  await expect(page.locator('#x')).toHaveText('hi');
});
`;

function project(name, files) {
  const dir = path.join(TMP, 'playwright', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `pw-${name}`, private: true }));
  fs.writeFileSync(path.join(dir, 'playwright.config.ts'),
    "import { defineConfig } from '@playwright/test';\nexport default defineConfig({ testDir: './tests', reporter: 'list', retries: 2, workers: 3, fullyParallel: true });\n");
  for (const [f, body] of Object.entries(files)) fs.writeFileSync(path.join(dir, 'tests', `${f}.spec.ts`), body);
  return dir;
}

function det(dir, args) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
  const r = spawnSync(process.execPath, [BIN, 'playwright', 'test', '--det', ...args], { cwd: dir, encoding: 'utf8', env, timeout: 300000 });
  return { status: r.status, out: `${r.stdout}\n${r.stderr}` };
}

const read = (dir, f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
function ran(dir) {
  const f = path.join(dir, 'ran');
  const out = fs.existsSync(f) ? fs.readFileSync(f, 'utf8').split('\n').filter(Boolean) : [];
  fs.rmSync(f, { force: true });
  return out;
}
function trace(dir) {
  return fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter((l) => l.startsWith('{"type":"test"')).map((l) => JSON.parse(l));
}

describe('detjs playwright', { skip: HAVE_PW ? false : '@playwright/test not installed in node/ (npm ci)' }, () => {
  test('--det: one worker, no retries, per-test brackets and fingerprints in one trace; the run after a failure is traced too', T, () => {
    const dir = project('trace', { a: A, b: B });
    const r = det(dir, ['--det-outcomes=o.json']);
    assert.equal(r.status, 1, r.out);
    const ids = ['victim', 'g::polluter', 'g::f2', 'draw', 'fails', 'after-failure'].map((t) => `tests/a.spec.ts::${t}`).concat(['tests/b.spec.ts::b1']);
    assert.deepEqual(trace(dir).map((t) => t.nodeid), ids);
    assert.deepEqual(ran(dir), ['victim', 'beforeAll-g', 'polluter', 'f2', 'draw', 'fails', 'after-failure', 'b1'], 'not serial, or retried');
    const o = read(dir, 'o.json');
    assert.deepEqual(o.order, ids);
    assert.equal(o.outcomes['tests/a.spec.ts::fails'], 'failed');
    assert.equal(o.outcomes['tests/a.spec.ts::after-failure'], 'passed');
    assert.deepEqual(o.exceptions['tests/a.spec.ts::fails'].slice(0, 2), ['Error', 'call']);
    assert.match(o.exceptions['tests/a.spec.ts::fails'][2], /^expect\(received\)\.toBe\(expected\)/);
    assert.equal(o.exceptions['tests/a.spec.ts::fails'][3], 'tests/a.spec.ts:13');
    for (const t of trace(dir)) assert.equal(o.fingerprints[t.nodeid], t.fingerprint);
    const draw = trace(dir).find((t) => t.nodeid === 'tests/a.spec.ts::draw');
    assert.ok(draw.events.some((e) => e.o === 'Math.random' && e.at === 'tests/a.spec.ts:12'), JSON.stringify(draw.events));
    assert.ok(r.out.includes('    fenvix repro tests/a.spec.ts::fails --runner=playwright\n'), r.out);
    assert.ok(r.out.includes('rerun the failing file with the same seeds and order: detjs playwright test --det tests/a.spec.ts'), r.out);
    // the same run again: the same fingerprints (Math.random is seeded per test)
    det(dir, ['--det-outcomes=o2.json']);
    ran(dir);
    assert.deepEqual(read(dir, 'o2.json').fingerprints, o.fingerprints);
  });

  test('--det-order: exactly the listed tests, in the listed order inside a file too; --det-collect gives the order of a seed', T, () => {
    const dir = project('order', { a: A, b: B });
    fs.writeFileSync(path.join(dir, 'order.txt'), ['tests/b.spec.ts::b1', 'tests/a.spec.ts::g::polluter', 'tests/a.spec.ts::victim'].join('\n'));
    det(dir, ['--det-order=order.txt', '--det-outcomes=o.json']);
    assert.deepEqual(ran(dir), ['b1', 'beforeAll-g', 'polluter', 'victim']);
    const o = read(dir, 'o.json');
    assert.equal(o.outcomes['tests/a.spec.ts::victim'], 'failed', 'module state left by the polluter');
    assert.deepEqual(trace(dir).map((t) => t.nodeid), ['tests/b.spec.ts::b1', 'tests/a.spec.ts::g::polluter', 'tests/a.spec.ts::victim']);
    for (const seed of [3, 8]) {
      const c = det(dir, [`--det-seed=${seed}`, '--det-collect', '--det-outcomes=c.json']);
      assert.equal(c.status, 0, c.out);
      assert.deepEqual(ran(dir), [], 'a test ran during collection');
      det(dir, [`--det-seed=${seed}`, '--det-outcomes=f.json']);
      ran(dir);
      assert.deepEqual(read(dir, 'c.json').order, read(dir, 'f.json').order);
      assert.deepEqual(trace(dir).map((t) => t.nodeid), read(dir, 'f.json').order, `seed ${seed}: the run did not follow the order`);
    }
  });

  test('--det-order-seed: a new order with the same generator values (G-1459)', T, () => {
    const dir = project('orderseed', { a: A, b: B });
    det(dir, ['--det-seed=4', '--det-outcomes=s4.json']);
    det(dir, ['--det-seed=4', '--det-order-seed=9', '--det-outcomes=s4o9.json']);
    det(dir, ['--det-seed=9', '--det-collect', '--det-outcomes=c9.json']);
    ran(dir);
    assert.deepEqual(read(dir, 's4o9.json').order, read(dir, 'c9.json').order, 'the order follows --det-order-seed');
    assert.notDeepEqual(read(dir, 's4o9.json').order, read(dir, 's4.json').order);
    assert.equal(fs.readFileSync(path.join(dir, 'draw-4-9'), 'utf8'), fs.readFileSync(path.join(dir, 'draw-4--'), 'utf8'),
      'Math.random follows --det-seed, not the order');
  });

  test('a test that opens a page in Chromium is controlled and traced in the test process', { ...T, skip: NO_BROWSER || false }, () => {
    const dir = project('page', { p: PAGE });
    const r = det(dir, ['--det-outcomes=o.json']);
    assert.equal(r.status, 0, r.out);
    const [t] = trace(dir);
    assert.equal(t.nodeid, 'tests/p.spec.ts::page');
    assert.equal(t.outcome, 'passed');
    assert.ok(t.events.some((e) => e.o === 'Math.random' && e.at === 'tests/p.spec.ts:3'), JSON.stringify(t.events));
    det(dir, ['--det-outcomes=o2.json']);
    assert.equal(read(dir, 'o2.json').fingerprints['tests/p.spec.ts::page'], t.fingerprint);
  });
});
