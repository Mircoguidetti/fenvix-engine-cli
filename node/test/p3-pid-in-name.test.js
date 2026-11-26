'use strict';
// P3 (spec "classify and remove the outcome flips under --det alone", step C): a virtual pid that is only part of a
// name the test made (`/tmp/ironcurtain-arg-validation-${process.pid}`) reaches a child process unchanged; a
// virtual pid standing as its own token (`kill -0 <pid>`, `-p <pid>`, `/proc/<pid>`, an env value) is still mapped
// to the real one (P1 C, test/p1-c-pid-boundaries.test.js). Found on ironcurtain (harness/p3_flips: the 10
// skipped-in-det cases, second layer after the node_modules/.bin fix: the MCP server got the real-pid path,
// "Cannot access directory /tmp/ironcurtain-arg-validation-<real pid>"; clears with --det-disable=seeds).
//
// protects: a path or name built from process.pid by the test and handed to a child names the same thing in the
//   child (argument list, command string, environment).
// fails_when: the child gets the name with the real pid in place of the virtual one, so the path does not exist.
// no_claim: a pid glued to other text that IS a process reference for the child (e.g. `pid=<n>` parsed by a child
//   program): left virtual, as any number in a name; /proc/<pid> and whole-token pids stay mapped (P1 C suite).
// Run: cd node && node --test --test-concurrency=1 test/p3-pid-in-name.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const helpers = require('./helpers');

const body = `import cp from 'node:child_process'; import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
const V = () => expect(process.pid > 4194304).toBe(true);
const mk = (tag) => { const d = path.join(os.tmpdir(), 'p3-pid-name-' + tag + '-' + process.pid); fs.mkdirSync(d, { recursive: true }); return d; };
test('argument list', () => { V(); const d = mk('a'); expect(cp.spawnSync('test', ['-d', d]).status).toBe(0); });
test('command string', () => { V(); const d = mk('c'); cp.execSync('test -d ' + d); });
test('child environment', () => { V(); const d = mk('e'); expect(cp.spawnSync('sh', ['-c', 'test -d "$P3_DIR"'], { env: { ...process.env, P3_DIR: d } }).status).toBe(0); });
test('whole-token pid is still the real process', () => { V(); expect(cp.spawnSync('kill', ['-0', String(process.pid)]).status).toBe(0); });
`;

test('P3: a virtual pid inside a name reaches the child unchanged; a whole-token pid is still mapped', { timeout: 300000 }, () => {
  const dir = helpers.project('vitest', 'p3-pid-name', { a: body });
  const r = helpers.run('vitest', dir, ['--det', '--det-workers=1', '--det-epoch=fixed']);
  const by = Object.fromEntries(Object.entries(r.outcomes).map(([k, s]) => [k.replace(/^.*::|^.* > /, ''), s]));
  for (const n of ['argument list', 'command string', 'child environment', 'whole-token pid is still the real process']) {
    assert.equal(by[n], 'passed', `${n}: ${JSON.stringify(by)}\n${(r.stdout || '').slice(-2500)}\n${(r.stderr || '').slice(-1500)}`);
  }
});
