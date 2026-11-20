'use strict';
// Jest test sequencer used under --det: files sorted by path relative to the
// root (fixed order) or shuffled with the seed; the executed order is written
// to <run dir>/order.json for the merge of the trace parts.
const path = require('node:path');
const native = require('../native');
const controls = require('../controls');

function baseSequencer() {
  const mod = require(require.resolve('@jest/test-sequencer', { paths: [process.cwd()] }));
  return mod.default || mod;
}

const Base = baseSequencer();

class DetSequencer extends Base {
  async sort(tests) {
    const c = controls.cfg();
    const root = process.env.DETJS_ROOT || process.cwd();
    const keyed = tests.map((t) => {
      const fileId = path.relative(root, t.path).split(path.sep).join('/');
      const cfg = t.context && t.context.config;
      const project = cfg && cfg.displayName ? cfg.displayName.name : '';
      return { t, fileId, project, key: project ? `${project}|${fileId}` : fileId };
    });
    keyed.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
    let ordered = keyed;
    if (c.shuffle && c.controls.has('order')) ordered = native.shuffleIndices(keyed.length, c.seed, '').map((i) => keyed[i]);
    const pc = globalThis[Symbol.for('detjs.cache.session')];
    if (pc) {
      if (!tests.length) pc.noTestsFound = true;
      // Jest applies a `__mocks__` file found anywhere under the roots (a root `__mocks__/<package>.js` replaces an
      // installed package without any jest.mock call): the mocks Jest's crawl found are an input of every file
      // (review r021 F7)
      const mocks = new Map();
      for (const t of tests) {
        const ctx = t.context;
        if (!ctx || !ctx.config || mocks.has(ctx.config)) continue;
        let list = null;
        try {
          const raw = ctx.moduleMap && typeof ctx.moduleMap.getRawModuleMap === 'function' ? ctx.moduleMap.getRawModuleMap() : null;
          if (raw && raw.mocks) list = [...raw.mocks.entries()].map(([k, v]) => [k, path.relative(root, v).split(path.sep).join('/')]).sort();
        } catch { /* below */ }
        mocks.set(ctx.config, list === null ? `unknown ${Date.now()}` : list);
      }
      pc.addGlobalPart('jest-mocks', [...mocks.values()].map((x) => JSON.stringify(x)).sort());
      const skip = await pc.decide(ordered.map((k) => ({ fileId: k.fileId, project: k.project, key: k.key })));
      ordered = ordered.filter((k) => !skip.has(k.key));
    }
    if (c.dir) {
      // the trace is merged in the serial order, whatever the lanes
      controls.writeJson(path.join(c.dir, 'order.json'),
        ordered.map((k) => ({ fileId: k.fileId, part: controls.partName(k.fileId, k.project), key: k.key })));
    }
    const workers = Number(process.env.DETJS_WORKERS || 1);
    if (workers > 1 && c.dir && ordered.length > 1) {
      // the fixed plan (src/parallel.js): lanes over the files that run, handed to Jest in planned start order; the
      // worker binding (src/jest/cli.js) sends each file to its lane's worker
      const parallel = require('../parallel');
      const plan = parallel.makePlan(root, ordered.map((k) => k.key), workers, { replay: process.env.DETJS_PLAN ? parallel.readReplay(process.env.DETJS_PLAN) : null });
      parallel.writeRunPlan(c.dir, plan, 'jest-workers');
      controls.writeJson(path.join(c.dir, 'plan-full.json'), plan);
      const byKey = new Map(ordered.map((k) => [k.key, k]));
      // Jest runs small suites in band when it has fast timings for them: none are given
      return plan.dispatch.map((key) => { const t = byKey.get(key).t; t.duration = undefined; return t; });
    }
    return ordered.map((k) => k.t);
  }
}

module.exports = DetSequencer;
