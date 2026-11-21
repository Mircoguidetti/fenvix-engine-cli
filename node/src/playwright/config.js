'use strict';
// The configuration a `detjs playwright --det` run gives Playwright Test: the project's own configuration with one
// worker, no parallel mode, no retries, and the detjs reporter added to the project's reporters (src/playwright/
// reporter.js orders, filters and records the tests). Loaded by the wrapper configuration file cli.js writes next to
// the project's configuration (so that its relative paths keep their meaning).
const path = require('node:path');

function reporters(r) {
  if (r === undefined || r === null) return [[process.env.CI ? 'dot' : 'list']];
  if (typeof r === 'string') return [[r]];
  if (Array.isArray(r)) return r.map((x) => (Array.isArray(x) ? x : [x]));
  return [[r]];
}

function wrap(base) {
  const cfg = base && base.default && !base.projects && !base.testDir && !base.use ? base.default : (base || {});
  const out = { ...cfg, workers: 1, fullyParallel: false, retries: 0 };
  out.reporter = [...reporters(cfg.reporter), [path.join(__dirname, 'reporter.js'), {}]];
  if (Array.isArray(cfg.projects)) out.projects = cfg.projects.map((p) => ({ ...p, fullyParallel: false, retries: 0 }));
  return out;
}

module.exports = { wrap, reporters };
