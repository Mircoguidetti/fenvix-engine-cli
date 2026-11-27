'use strict';
// P2 D6 (founder decision 2026-11-27, D6 = A): the trace header is the same for two identical runs. The footprint's
// skip dirs (meta.parallel.skip_dirs, parallel-proof-gaps) included the runner's per-run temporary directories by
// their real path (Vitest's `ctx._tmpDir` and each project's `tmpDir`: a random name under os.tmpdir()), so two
// identical runs wrote different headers. The engine now writes those directories by what they are, not by their
// random path; every other field of the header is compared as it is.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');

function fixture(runner) {
  const dir = path.join(TMP, 'p2-skipdirs', runner);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `p2-skipdirs-${runner}`, private: true }));
  if (runner === 'vitest') fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  else fs.writeFileSync(path.join(dir, 'jest.config.js'), "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n");
  const head = runner === 'vitest' ? "import { test, expect } from 'vitest';" : '';
  for (let i = 1; i <= 4; i++) {
    fs.writeFileSync(path.join(dir, 'tests', `s${i}.test.${runner === 'vitest' ? 'mjs' : 'js'}`),
      `${head}\ntest('s${i}', () => { expect(${i} + 1).toBe(${i + 1}); });\n`);
  }
  return dir;
}

function run(runner, dir, trace) {
  fs.rmSync(path.join(dir, '.detjs'), { recursive: true, force: true }); // the same cold state for both runs
  fs.rmSync(trace, { force: true });
  const e = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID',
    'DETJS_PHASES', 'DETJS_PHASES_FILE', 'DETJS_FOOTPRINT_SKIP_DIRS', 'DETJS_FOOTPRINT_SKIP_LABELS', 'DETJS_CACHE_SKIP_DIRS']) delete e[k];
  const args = runner === 'vitest' ? ['run'] : [`--cacheDirectory=${path.join(dir, '.jest-cache')}`];
  return spawnSync(process.execPath, [BIN, runner, ...args, '--det', '--det-workers=2', '--det-epoch=fixed', `--det-trace=${trace}`],
    { cwd: dir, env: e, encoding: 'utf8', timeout: 300000 });
}

/** The header, without the fields PREREG §6 names as timing (they are measured times, not results). */
function header(trace) {
  const h = JSON.parse(fs.readFileSync(trace, 'utf8').split('\n')[0]);
  const p = h.meta && h.meta.parallel;
  if (p) {
    delete p.timing;
    if (p.placement) { delete p.placement.spans; delete p.placement.waited_seconds; }
  }
  return h;
}

for (const runner of RUNNERS) {
  test(`${runner}: two identical runs write the same trace header, skip_dirs included (P2 D6)`, T, () => {
    // protects= the header is a function of the run's inputs; fails_when= a skip dir is written by a random
    // per-run path (two runs differ); no_claim= which dirs the footprint skips (parallel-proof-gaps tests)
    const dir = fixture(runner);
    const a = path.join(dir, 'a.jsonl'); const b = path.join(dir, 'b.jsonl');
    for (const t of [a, b]) { const r = run(runner, dir, t); assert.equal(r.status, 0, r.stdout + r.stderr); }
    const ha = header(a); const hb = header(b);
    assert.ok(ha.meta.parallel && Array.isArray(ha.meta.parallel.skip_dirs), JSON.stringify(ha.meta.parallel));
    // no entry is a path under the temporary directory with a name the run chose at random
    const tmp = fs.realpathSync.native(os.tmpdir());
    const stable = /^(jiti|node-jiti|tsx-\d*|v8-compile-cache(-\d*)?|swc-node-\d*|detjs-probe-\d*)$/;
    for (const d of ha.meta.parallel.skip_dirs) {
      if (d.startsWith(tmp + path.sep)) assert.match(d.slice(tmp.length + 1).split(path.sep)[0], stable, `skip_dirs entry ${d}`);
    }
    assert.deepEqual(hb.meta.parallel.skip_dirs, ha.meta.parallel.skip_dirs);
    assert.deepEqual(hb, ha);
  });
}
