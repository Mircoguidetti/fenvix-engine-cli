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
