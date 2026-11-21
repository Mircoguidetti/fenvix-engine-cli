'use strict';
// Vitest `projects` (workspaces): project configs do not inherit the runner
// from the command line; detjs sets it on every resolved project.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { run, failed, TMP } = require('./helpers');

test('vitest projects: every project runs under --det, failures set the exit code', { timeout: 120000 }, () => {
  const dir = path.join(TMP, 'vitest', 'projects');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), '{"name":"fixture-projects","private":true,"type":"module"}');
  fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { projects: ['packages/*'] } };\n");
  for (const x of ['a', 'b']) {
    fs.mkdirSync(path.join(dir, 'packages', x, 'test'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'packages', x, 'vitest.config.mjs'), `export default { test: { name: '${x}' } };\n`);
    fs.writeFileSync(path.join(dir, 'packages', x, 'test', 'x.test.mjs'),
      `import { test, expect } from 'vitest';\ntest('random ${x}', () => { expect(Math.random()).toBeLessThan(${x === 'a' ? 1 : 0}); });\n`);
  }
  const r = run('vitest', dir, ['--det']);
  assert.equal(r.status, 1);
  assert.equal(failed(r).length, 1);
  assert.equal(r.trace.tests.length, 2);
  assert.ok(r.trace.tests.every((t) => t.events.some((e) => e.o === 'Math.random')));
  assert.equal(r.trace.header.meta.runtime, 'node');
  assert.deepEqual(r.trace.header.meta.files, ['packages/a/test/x.test.mjs', 'packages/b/test/x.test.mjs']);
});

// exam F-03.probe.multi-project: one file run by two projects is two tests in the trace (`file@@project::name`),
// and verify compares each project's part on its own: a difference in one project only is reported for it
test('vitest projects running the same file: both parts are in the trace and each is compared', { timeout: 300000 }, () => {
  const native = require('../src/native');
  const dir = path.join(TMP, 'vitest', 'projects-same-file');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
  const flags = path.join(dir, 'flags');
  fs.mkdirSync(flags);
  fs.writeFileSync(path.join(dir, 'package.json'), '{"name":"fixture-projects-same","private":true,"type":"module"}');
  fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { projects: [\n"
    + "  { test: { name: 'one', include: ['test/v.test.mjs'], env: { MP: 'one' } } },\n"
    + "  { test: { name: 'two', include: ['test/v.test.mjs'], env: { MP: 'two' } } },\n] } };\n");
  fs.writeFileSync(path.join(dir, 'test', 'v.test.mjs'), "import { test, expect } from 'vitest';\nimport fs from 'node:fs';\n"
    + `test('value', () => { expect(fs.readFileSync(${JSON.stringify(flags)} + '/' + process.env.MP, 'utf8')).toBe('a'); });\n`);
  const runWith = (name, one, two) => {
    fs.writeFileSync(path.join(flags, 'one'), one);
    fs.writeFileSync(path.join(flags, 'two'), two);
    const r = run('vitest', dir, ['--det']);
    const dst = path.join(dir, `${name}.jsonl`);
    fs.copyFileSync(r.tracePath, dst);
    return [r, dst];
  };
  const [r, a] = runWith('a', 'a', 'a');
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.deepEqual(r.trace.tests.map((t) => t.nodeid).sort(), ['test/v.test.mjs@@one::value', 'test/v.test.mjs@@two::value']);
  const [, b] = runWith('b', 'a', 'a');
  const same = JSON.parse(native.verify([a, b]));
  assert.equal(same.summary.tests, 2, JSON.stringify(same.summary));
  assert.equal(same.summary.stable, 2, JSON.stringify(same.summary));
  const [, c] = runWith('c', 'a', 'b');
  const diff = JSON.parse(native.verify([a, c]));
  const by = Object.fromEntries(diff.tests.map((t) => [t.nodeid, t.status]));
  assert.equal(by['test/v.test.mjs@@one::value'], 'stable', JSON.stringify(diff.tests));
  assert.notEqual(by['test/v.test.mjs@@two::value'], 'stable', JSON.stringify(diff.tests));
});
