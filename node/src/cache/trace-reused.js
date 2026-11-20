'use strict';
// The reused tests of a --det-cache session in its trace (audit G-1402).
//
// A reused test does not run, so it has no events; its line in the trace carries what the cache proved: the outcome
// and the fingerprint recorded with the result it reuses (`events: []`, `truncated: true`, `n_events: 0`). The
// header lists them (`meta.reused_tests`), so `detjs verify` between a cached run and a full run compares their
// fingerprints with the fresh ones instead of reporting them missing, and says which side was reused when they
// differ. Each reused file is placed where the plan had it, between the parts of the files that ran.
const fs = require('node:fs');
const path = require('node:path');

// the trace format of crates/detpy-core/src/trace.rs (TRACE_FORMAT, TRACE_VERSION, ENCODING_VERSION)
const PART_HEADER = { type: 'header', format: 'detpy-trace', version: 1, encoding: 2, meta: { reused: true }, order: [] };

/**
 * Parts of the run in plan order, the reused files' parts included. `parts`: executed parts [{fileId, path}] in
 * execution order. Returns {paths, reusedTests}.
 */
function withReused(run, parts) {
  const ct = run.cacheTrace;
  if (!ct || !ct.reused || !ct.reused.length) return { paths: parts.map((p) => p.path), reusedTests: [] };
  const planIndex = new Map();
  ct.plan.forEach((f, i) => { if (!planIndex.has(f)) planIndex.set(f, i); });
  const items = parts.map((p, i) => ({ at: planIndex.has(p.fileId) ? planIndex.get(p.fileId) : Number.MAX_SAFE_INTEGER, n: i, path: p.path }));
  const reusedTests = [];
  ct.reused.forEach((f, k) => {
    const recs = (f.receipts || []).slice(1); // [0] is the file's own entry
    const lines = [JSON.stringify(PART_HEADER)];
    f.tests.forEach((t, i) => {
      const rc = recs[i] ? recs[i][1] : {};
      reusedTests.push(t);
      lines.push(JSON.stringify({
        type: 'test', nodeid: t, index: i, outcome: rc.outcome || 'passed', fingerprint: rc.fingerprint || '',
        n_events: 0, truncated: true, counts: {}, checkpoints: [], events: [],
      }));
    });
    const p = path.join(run.dir, 'parts', `~reused-${k}.jsonl`);
    fs.writeFileSync(p, `${lines.join('\n')}\n`);
    const at = planIndex.has(f.fileId) ? planIndex.get(f.fileId) : Number.MAX_SAFE_INTEGER;
    items.push({ at, n: -1, path: p });
  });
  // stable: executed parts keep their order among themselves; a reused part goes before the first executed part
  // that comes after it in the plan
  const out = [];
  const reusedItems = items.filter((x) => x.n < 0).sort((a, b) => a.at - b.at);
  let r = 0;
  for (const x of items.filter((y) => y.n >= 0)) {
    while (r < reusedItems.length && reusedItems[r].at < x.at) out.push(reusedItems[r++].path);
    out.push(x.path);
  }
  while (r < reusedItems.length) out.push(reusedItems[r++].path);
  return { paths: out, reusedTests };
}

module.exports = { withReused };
