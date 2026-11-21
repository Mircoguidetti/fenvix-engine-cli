'use strict';
// Review R-050, re-check of the Node findings of claude/review-p1-verifier (#1) on PR #8 (claude/node @ 888b2ca5).
// N1: finding #1 listed "file: a file outside the project, A vs B" among the values that differ while `verify` says
// IDENTICAL, but its test (review-p1-verifier.test.js, "F-03: no test whose observed value differs ...") has no such
// probe. On 888b2ca5 a test that reads a file outside the project, "A" in run 1 and "B" in run 2, is still reported
// stable: `fenvix verify` exit 0, "IDENTICAL: all 1 tests ran with the same inputs" (Node 22, 24, 26). Python records
// such reads (os control: "other files read ... recorded") and reports the same pair DIVERGENT.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../src/native');
const { fixture, crun, show } = require('./runner-helpers');

test('N1: a file outside the project read with different contents in two --det runs is not reported identical', { timeout: 900000 }, () => {
  const ext = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'r050-outside-')), 'outside.txt');
  const seen = `${ext}.seen`;
  const dir = fixture('review-r050', 'outside-file', {
    'tests/p.test.mjs': "import { test } from 'node:test'; import fs from 'node:fs';\n"
      + `test('outside file', () => { fs.appendFileSync(${JSON.stringify(seen)}, fs.readFileSync(${JSON.stringify(ext)}, 'utf8') + '\\n'); });\n`,
  });
  const traces = [];
  for (const [i, content] of [[1, 'A'], [2, 'B']]) {
    fs.writeFileSync(ext, content);
    const r = crun('node-test', dir, [], { cache: false, env: { TZ: 'UTC' } });
    assert.equal(r.status, 0, show(r));
    const t = path.join(path.dirname(ext), `run${i}.jsonl`);
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), t);
    traces.push(t);
  }
  assert.deepEqual(fs.readFileSync(seen, 'utf8').trim().split('\n'), ['A', 'B'], 'precondition: the two runs read different contents');
  const rep = JSON.parse(native.verify(traces));
  const st = rep.tests.find((t) => t.nodeid.endsWith('outside file'));
  assert.ok(st, JSON.stringify(rep.tests));
  assert.notEqual(st.status, 'stable', `verify reported the test identical although it read "A" and then "B": ${JSON.stringify(rep.summary)}`);
});
