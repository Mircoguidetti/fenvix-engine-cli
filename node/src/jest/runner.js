'use strict';
// Jest test runner used under --det (set by `detjs jest` with --testRunner).
//
// It receives the environment Jest built for the test file (node, jsdom, a
// docblock @jest-environment or a custom one), installs the realm controls
// into that environment's global object, re-creates Jest's modern fake
// timers on top of them (so jest.useRealTimers() restores the virtual
// timers), adds a circus event handler that orders the tests of the file and
// brackets every test, then delegates to the project's own runner
// (jest-circus).
const path = require('node:path');
const controls = require('../controls');
const concur = require('../concur');
const parallel = require('../parallel');
const repro = require('../repro');

const { STATE } = controls;
// the session's capture (in band: the main process) or a worker's (parallel lanes: src/jest/worker.js)
const IN_WORKER = Boolean(globalThis[Symbol.for('detjs.cache.worker')]);
const CAP = globalThis[Symbol.for('detjs.cache.session')] || IN_WORKER ? require('../cache/capture').CAPTURE : null;

/** Modules Jest's runtime loaded for the current file (sources it read and its module registries). */
function runtimeModules(runtime) {
  const out = [];
  for (const k of ['_cacheFS', '_moduleRegistry', '_esmoduleRegistry', '_cjsNamedExports', '_isolatedModuleRegistry']) {
    const m = runtime && runtime[k];
    if (m && typeof m.keys === 'function') {
      try { for (const x of m.keys()) if (typeof x === 'string') out.push(x); } catch { /* ignore */ }
    }
  }
  return out;
}

function baseRunner(config) {
  const map = JSON.parse(process.env.DETJS_JEST_RUNNERS || '{}');
  const configured = map[`${config.rootDir}|${config.displayName ? config.displayName.name : ''}`] || map['*'];
  const target = configured && !/[\\/]src[\\/]jest[\\/]runner\.js$/.test(configured)
    ? configured
    : require.resolve('jest-circus/runner', { paths: [config.rootDir, process.cwd()] });
  const mod = require(target);
  const fn = mod.default || mod;
  if (/[\\/]jest-jasmine2[\\/]/.test(target)) Object.defineProperty(fn, '__detjsJasmine', { value: true, configurable: true });
  return fn;
}

/** Jasmine's spec status -> outcome. */
function jasmineOutcome(status) {
  return { passed: 'passed', failed: 'failed', todo: 'todo' }[status] || 'skipped';
}

/** Ids of a jasmine tree (suites and specs by object), declaration order, duplicates numbered. */
function jasmineIds(top, fileId) {
  const ids = new Map();
  const flat = [];
  const walk = (suite, prefix) => {
    for (const ch of suite.children || []) {
      const id = `${prefix}::${ch.description}`;
      if (Array.isArray(ch.children)) { ids.set(ch, id); walk(ch, id); } else flat.push([ch, id]);
    }
  };
  ids.set(top, fileId);
  walk(top, fileId);
  const unique = controls.uniqueIds(flat.map(([, id]) => id));
  flat.forEach(([t], i) => { ids.set(t, unique[i]); ids.set(t.id, unique[i]); });
  return ids;
}

/**
 * jest-jasmine2 has no circus events (audit G-1467): it assigns `jasmine` on the test file's global object before
 * the file is loaded; the setter installed here then adds a jasmine reporter (specStarted / specDone bracket every
 * test, beforeEach and afterEach included) and wraps env.execute (ids in declaration order; --det-seed shuffles the
 * suites and specs before jasmine walks the tree).
 */
function hookJasmine(g, onEnv) {
  let value;
  Object.defineProperty(g, 'jasmine', {
    configurable: true,
    enumerable: true,
    get() { return value; },
    set(v) {
      value = v;
      Object.defineProperty(g, 'jasmine', { value: v, writable: true, configurable: true, enumerable: true });
      let env = null;
      try { env = v && typeof v.getEnv === 'function' ? v.getEnv() : null; } catch { env = null; }
      if (env) onEnv(env);
      else process.stderr.write('detjs: WARNING: jest-jasmine2 environment not found: no per-test brackets for this file\n');
    },
  });
}

function childrenOf(block) {
  // Jest >= 27: `children` mixes describe blocks and tests; older: tests + children.
  if (!block) return [];
  const children = block.children || [];
  if (!Array.isArray(block.tests)) return children;
  const known = new Set(children);
  if (block.tests.every((t) => known.has(t))) return children;
  return [...block.tests, ...children];
}

function testIds(root, fileId) {
  const ids = new Map();
  const flat = [];
  const walk = (block, prefix) => {
    for (const ch of childrenOf(block)) {
      const id = `${prefix}::${ch.name}`;
      if (ch.type === 'describeBlock') { ids.set(ch, id); walk(ch, id); } else flat.push([ch, id]);
    }
  };
  ids.set(root, fileId);
  walk(root, fileId);
  const unique = controls.uniqueIds(flat.map(([, id]) => id));
  flat.forEach(([t], i) => ids.set(t, unique[i]));
  return ids;
}

function outcomeOf(test) {
  return test.errors && test.errors.length ? 'failed' : 'passed';
}

/**
 * Jest's modern fake timers start their clock at `Date.now()` of Jest's own realm (the real clock): start it at the
 * virtual clock instead (recorded: the epoch becomes an input of the test), unless the test or the configuration
 * gives `now` (audit G-0122, G-0142). `getRealSystemTime()` returns the virtual clock as well. `advanceTimers` lets
 * the fake clock follow real time: that is a real-clock read (never cached).
 */
function virtualFakeClock(ft, config) {
  const clock = require('../clock');
  if (!ft || ft.__detjsVirtual || typeof ft.useFakeTimers !== 'function') return;
  const use = ft.useFakeTimers;
  ft.useFakeTimers = function useFakeTimers(cfg) {
    const merged = { ...((config && config.fakeTimers) || {}), ...(cfg || {}) };
    if (merged.advanceTimers && STATE.onRealClock) STATE.onRealClock('fake timers with advanceTimers (real time)');
    if (merged.now === undefined && clock.CLOCK) cfg = { ...(cfg || {}), now: clock.fakeNow() };
    return use.call(this, cfg);
  };
  if (typeof ft.getRealSystemTime === 'function') {
    const real = ft.getRealSystemTime;
    ft.getRealSystemTime = function getRealSystemTime() {
      return clock.CLOCK ? clock.fakeNow('getRealSystemTime') : real.call(this);
    };
  }
  Object.defineProperty(ft, '__detjsVirtual', { value: true });
}

/**
 * --det-order / --det-collect (src/repro.js): reduce and order the file's describe tree to the plan (run_start, after
 * the shuffle); returns the ids that will run, in order. Collection only: every block and test is skipped (no hook
 * runs: jest-circus runs the hooks of a block only when it has an enabled test).
 */
function reproPlan(rootBlock, ids) {
  const p = repro.plan();
  // Jest >= 27 runs `children` (describe blocks and tests mixed; Jest 30 still keeps a `tests` list beside it); older
  // Jest has tests and describe blocks in separate lists. Decided once, before the tree changes.
  const modern = !Array.isArray(rootBlock.tests) || childrenOf(rootBlock) === rootBlock.children;
  const kids = (b) => (modern ? b.children || [] : childrenOf(b));
  const idOf = (t) => (t.type === 'describeBlock' ? null : ids.get(t) || null);
  const kidsOf = (b) => (b.type === 'describeBlock' ? kids(b) : null);
  if (p && modern) repro.filterTree(rootBlock.children, idOf, kidsOf, p);
  else if (p) {
    const reduce = (block) => {
      repro.filterTree(block.tests, idOf, () => null, p);
      for (const ch of block.children) reduce(ch);
      const first = (b) => Math.min(...repro.flatIds(kids(b), idOf, kidsOf).map((id) => p.index.get(id)));
      const kept = block.children.filter((b) => repro.flatIds(kids(b), idOf, kidsOf).length).sort((x, y) => first(x) - first(y));
      block.children.splice(0, block.children.length, ...kept);
    };
    reduce(rootBlock);
  }
  const out = repro.flatIds(kids(rootBlock), idOf, kidsOf);
  if (process.env.DETJS_COLLECT === '1') {
    const skip = (b) => { for (const ch of kids(b)) { ch.mode = 'skip'; if (ch.type === 'describeBlock') skip(ch); } };
    skip(rootBlock);
  }
  return out;
}

async function detjsJestRunner(globalConfig, config, environment, runtime, testPath, sendMessageToJest) {
  const run = baseRunner(config);
  const c = controls.cfg();
  if (!c.active) return run(globalConfig, config, environment, runtime, testPath, sendMessageToJest);
  controls.installProcess();
  if (CAP) {
    CAP.reinstall();
    // Jest <= 29: runtime._resolver; Jest 30: runtime._resolution.resolver
    CAP.hookJestResolver(runtime && (runtime._resolver || (runtime._resolution && runtime._resolution.resolver)), config);
  }
  const root = process.env.DETJS_ROOT || process.cwd();
  const fileId = path.relative(root, testPath).split(path.sep).join('/');
  const project = config.displayName ? config.displayName.name : '';
  const label = project ? `${project}|${fileId}` : fileId;
  if (Number(process.env.DETJS_WORKERS || 1) > 1) parallel.installFootprint(root);
  // a lane runs one file at a time, in plan order (src/parallel.js); then the process-wide state that earlier files
  // of this process left changed (a worker, or the in-band process, runs many files): reported, and not cached
  parallel.enter(label, { runner: 'jest' });
  const carried = parallel.carriedBefore();
  // the wrapped test environment (src/jest/environment.js) installed the controls before setupFiles ran (G-1312)
  const early = require('./environment').opened(environment, fileId);
  if (!early) {
    controls.installRealm(environment.global, { sameRealm: environment.global === globalThis });
    // legacy fake timers restore the virtual timers on useRealTimers() (G-1468)
    if (c.controls.has('timers')) require('../realmx').virtualLegacyTimers(environment.fakeTimers, environment.global);
    if (environment.fakeTimersModern) {
      try {
        environment.fakeTimersModern = new environment.fakeTimersModern.constructor({ config, global: environment.global });
      } catch { /* keep Jest's instance */ }
      if (c.controls.has('time')) virtualFakeClock(environment.fakeTimersModern, config);
    }
    if (config.setupFiles && config.setupFiles.length) {
      // never silent: an environment detjs could not wrap (loaded as native ESM) ran setupFiles uncontrolled
      process.stderr.write(`detjs: WARNING: the test environment of ${fileId} was not wrapped: its setupFiles ran before the Level 0 controls\n`);
      STATE.notes.push(`setupFiles of ${fileId} ran before the controls`);
    }
    controls.openFile(fileId, project);
    if (config.setupFiles && config.setupFiles.length) {
      STATE.onTestStart.push(() => {
        if (STATE.fileId !== fileId) return;
        require('../uncovered').mark('setupFiles ran before the controls');
      });
    }
  }

  let ids = new Map();
  let collected = [];
  const exceptions = {};
  let fileError = null;
  let pending = null; // test whose last attempt finished (retries reuse the id)
  const ctxOf = new Map(); // a concurrent test -> its Level 0 context (src/concur.js)
  // test.concurrent: each test its own Level 0 context, carried by its test function and what it starts. Wrapped when
  // the run starts: Jest 29 starts every concurrent test of the file before their test_start events (Jest 30 runs
  // them from the test_start of each)
  const wrapConcurrent = (test, id) => {
    if (ctxOf.has(test)) return;
    const ctx = concur.create(id, () => { STATE.initConcurrent(id); if (CAP) CAP.setCtx('t'); });
    ctxOf.set(test, ctx);
    const fn = test.fn;
    if (typeof fn === 'function') {
      const w = function concurrentTest(...a) { return concur.within(ctx, () => fn.apply(this, a)); };
      Object.defineProperty(w, 'length', { value: fn.length });
      test.fn = w;
    }
  };
  const endConcurrent = (test, id, outcome) => {
    const ctx = ctxOf.get(test);
    if (!ctx || ctx.done) return;
    concur.within(ctx, () => endTest(id, outcome, test));
    concur.finish(ctx);
  };
  const endTest = (id, outcome, test) => {
    const fp = STATE.endTest(outcome);
    if (CAP) {
      CAP.testEnd(id, outcome, test && typeof test.duration === 'number' ? test.duration / 1000 : 0, fp, runtimeModules(runtime));
      CAP.setCtx('f');
    }
  };
  const endPending = () => {
    if (pending !== null) {
      if (STATE.testId === pending.id) endTest(pending.id, pending.outcome, pending.test);
      pending = null;
    }
  };
  const begin = (id) => {
    if (pending && pending.id === id) { pending = null; return; } // retry
    endPending();
    STATE.beginTest(id);
    if (CAP) CAP.setCtx('t');
  };
  const handler = (event, state) => {
    switch (event.name) {
      case 'setup':
        if (c.controls.has('order')) state.randomize = false;
        break;
      case 'run_start': {
        if (c.controls.has('order')) state.randomize = false;
        ids = testIds(state.rootDescribeBlock, fileId);
        if (c.controls.has('order') && c.shuffle) {
          const rootKids = childrenOf(state.rootDescribeBlock);
          const keyOf = (b) => (b === state.rootDescribeBlock ? label : `${label}${ids.get(b).slice(fileId.length)}`);
          const shuffleBlock = (block) => {
            if (!Array.isArray(block.tests) || childrenOf(block) === block.children) {
              const out = controls.shuffleTree(block.children, c.orderSeed, keyOf(block), keyOf, (b) => (b.type === 'describeBlock' ? b.children : null));
              block.children.splice(0, block.children.length, ...out);
            } else {
              // Jest < 27: tests and describe blocks are separate lists
              for (const k of ['tests', 'children']) {
                if (!block[k] || !block[k].length) continue;
                const perm = require('../native').shuffleIndices(block[k].length, c.orderSeed, `${keyOf(block)}\0${k}`);
                const out = perm.map((i) => block[k][i]);
                block[k].splice(0, block[k].length, ...out);
              }
              for (const ch of block.children || []) shuffleBlock(ch);
            }
          };
          if (rootKids.length) shuffleBlock(state.rootDescribeBlock);
        }
        collected = reproPlan(state.rootDescribeBlock, ids);
        for (const [t, tid] of ids) if (t && t.type === 'test' && t.concurrent) wrapConcurrent(t, tid);
        break;
      }
      case 'test_start': {
        const id = ids.get(event.test) || `${fileId}::${event.test.name}`;
        if (event.test.concurrent) { wrapConcurrent(event.test, id); break; }
        if (STATE.testId !== id) begin(id);
        break;
      }
      case 'test_done': {
        const id = ids.get(event.test) || `${fileId}::${event.test.name}`;
        if (ctxOf.has(event.test)) endConcurrent(event.test, id, outcomeOf(event.test));
        else if (STATE.testId === id) pending = { id, outcome: outcomeOf(event.test), test: event.test };
        if (event.test.errors && event.test.errors.length) exceptions[id] = repro.exceptionOf(event.test.errors[0], 'call', root);
        else delete exceptions[id]; // a retry passed
        break;
      }
      case 'test_skip':
      case 'test_todo': {
        const id = ids.get(event.test) || `${fileId}::${event.test.name}`;
        if (ctxOf.has(event.test)) { endConcurrent(event.test, id, event.name === 'test_todo' ? 'todo' : 'skipped'); break; }
        if (STATE.testId !== id) begin(id);
        pending = null;
        endTest(id, event.name === 'test_todo' ? 'todo' : 'skipped', event.test);
        break;
      }
      case 'run_finish':
        endPending();
        // concurrent tests that never ran (filtered by name): their contexts end with the file
        for (const ctx of ctxOf.values()) if (!ctx.done) concur.finish(ctx);
        break;
      default:
    }
  };
  if (run.__detjsJasmine) {
    hookJasmine(environment.global, (env) => {
      let jids = new Map();
      const exec = env.execute;
      env.execute = function execute(...a) {
        const top = env.topSuite();
        jids = jasmineIds(top, fileId);
        ids = jids;
        if (c.controls.has('order') && c.shuffle) {
          const keyOf = (b) => (b === top ? label : `${label}${jids.get(b).slice(fileId.length)}`);
          const out = controls.shuffleTree(top.children, c.seed, label, keyOf, (b) => (Array.isArray(b.children) ? b.children : null));
          top.children.splice(0, top.children.length, ...out);
        }
        return exec.apply(this, a);
      };
      const idOf = (r) => jids.get(r.id) || `${fileId}::${r.description}`;
      env.addReporter({
        specStarted(r) {
          const id = idOf(r);
          if (STATE.testId !== id) begin(id);
        },
        specDone(r) {
          const id = idOf(r);
          if (STATE.testId !== id) begin(id);
          pending = null;
          endTest(id, jasmineOutcome(r.status), { duration: typeof r.duration === 'number' ? r.duration : 0 });
        },
      });
    });
  }
  const prev = environment.handleTestEvent;
  environment.handleTestEvent = function handleTestEvent(event, state) {
    handler(event, state);
    return prev ? prev.call(this, event, state) : undefined;
  };
  if (CAP) {
    CAP.beginFileTests();
    if (CAP.label !== label) { CAP.resetFile(); CAP.setCtx('f', label); }
    if (carried.length) CAP.add(['flag', 'carried', carried.slice(0, 3).map((x) => `${x.key} changed by ${x.by}`).join('; ')], false);
  }
  const t0 = Date.now();
  let result;
  try {
    result = await run(globalConfig, config, environment, runtime, testPath, sendMessageToJest);
    return result;
  } catch (e) {
    fileError = repro.exceptionOf(e, 'collect', root);
    throw e;
  } finally {
    endPending();
    // B5 (spec "Engine P0: no false green"): tests the circus events never bracketed (a failing beforeAll skips them
    // without a test_start/test_skip, a filter) are written as `skipped` before the part closes, cache on or off.
    // The cache capture below adds them to its own list as before.
    // Only tests still in the run: --det-order removes the others from the tree (reproPlan), and they are not
    // reported by Jest at all; a collection-only run (--det-collect) records nothing more.
    try {
      const inRun = new Set(collected);
      if (process.env.DETJS_COLLECT !== '1') {
        controls.recordNeverStarted([...ids].filter(([t, id]) => t && t.type === 'test' && inRun.has(repro.wf(id))).map(([, id]) => id));
      }
    } catch (e) { process.stderr.write(`detjs: never-started tests of ${fileId} not recorded: ${e && e.message}\n`); }
    controls.closeFile();
    parallel.carriedAfter(label);
    parallel.leave(label, carried.length ? { carried } : {});
    if (!fileError && result && result.testExecError) fileError = repro.exceptionOf(result.testExecError, 'collect', root);
    repro.writeSide(c.dir, controls.partName(fileId, project), { file: fileId, project, collected, states: {}, exceptions, durations: controls.STATE.takeDurations(), file_error: fileError });
    if (CAP && c.dir) {
      try {
        const ok = Boolean(result) && !result.testExecError && !(result.numFailingTests > 0);
        // tests the circus events never bracketed (a failing beforeAll skips them)
        const ended = new Set(CAP.tests.map((t) => t.id));
        for (const [t, id] of ids) if (t && t.type === 'test' && !ended.has(id)) CAP.tests.push({ id, outcome: 'skipped', duration: 0, fingerprint: '', upto: CAP.log.length });
        const capture = CAP.fileCapture({ fileId, project, label, ok, duration: (Date.now() - t0) / 1000 }, runtimeModules(runtime));
        // a worker's own items outside any file (src/jest/worker.js): global inputs, as the main process's in band
        if (IN_WORKER) capture.worker_global = CAP.global;
        controls.writeJson(path.join(c.dir, 'cache', `${controls.partName(fileId, project).replace(/\.jsonl$/, '')}-${process.pid}.json`), capture);
      } catch (e) {
        process.stderr.write(`detjs cache: capture of ${fileId} not written: ${e && e.stack}\n`);
      }
      CAP.resetFile();
      CAP.setCtx('', '');
    }
  }
}

module.exports = detjsJestRunner;
module.exports.virtualFakeClock = virtualFakeClock;
