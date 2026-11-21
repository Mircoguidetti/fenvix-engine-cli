'use strict';
// Wraps a project's Playwright config for a Level 2 browser run
// (imported by the generated playwright.detjs.config.* next to it).
function wrap(base) {
  const cfg = { ...(base && base.default ? base.default : base) };
  cfg.workers = 1;
  cfg.fullyParallel = false;
  cfg.retries = 0;
  const reporter = process.env.DETJS_PW_REPORTER;
  if (reporter) {
    let list = cfg.reporter || 'list';
    if (typeof list === 'string') list = [[list]];
    list = list.map((r) => (Array.isArray(r) ? r : [r]))
      .filter(([name]) => name !== 'html'); // the html reporter would try to open a browser
    if (!list.length) list.push(['list']);
    cfg.reporter = [...list, [reporter]];
  }
  if (Array.isArray(cfg.projects)) {
    cfg.projects = cfg.projects.map((p) => ({ ...p, fullyParallel: false, retries: 0 }));
  }
  return cfg;
}
module.exports = { wrap };
