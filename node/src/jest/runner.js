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

const { STATE } = controls;
const CAP = globalThis[Symbol.for('detjs.cache.session')] ? require('../cache/capture').CAPTURE : null;

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
  return mod.default || mod;
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

module.exports = async function detjsJestRunner(globalConfig, config, environment, runtime, testPath, sendMessageToJest) {
  const run = baseRunner(config);
  const c = controls.cfg();
  if (!c.active) return run(globalConfig, config, environment, runtime, testPath, sendMessageToJest);
  controls.installProcess();
  if (CAP) {
    CAP.reinstall();
    // Jest <= 29: runtime._resolver; Jest 30: runtime._resolution.resolver
    CAP.hookJestResolver(runtime && (runtime._resolver || (runtime._resolution && runtime._resolution.resolver)), config);
  }
  controls.installRealm(environment.global, { sameRealm: environment.global === globalThis });
  if (environment.fakeTimersModern) {
    try {
      environment.fakeTimersModern = new environment.fakeTimersModern.constructor({ config, global: environment.global });
    } catch { /* keep Jest's instance */ }
  }
  const root = process.env.DETJS_ROOT || process.cwd();
  const fileId = path.relative(root, testPath).split(path.sep).join('/');
  const project = config.displayName ? config.displayName.name : '';
  const label = project ? `${project}|${fileId}` : fileId;
  controls.openFile(fileId, project);

  let ids = new Map();
  let pending = null; // test whose last attempt finished (retries reuse the id)
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
              const out = controls.shuffleTree(block.children, c.seed, keyOf(block), keyOf, (b) => (b.type === 'describeBlock' ? b.children : null));
              block.children.splice(0, block.children.length, ...out);
            } else {
              // Jest < 27: tests and describe blocks are separate lists
              for (const k of ['tests', 'children']) {
                if (!block[k] || !block[k].length) continue;
                const perm = require('../native').shuffleIndices(block[k].length, c.seed, `${keyOf(block)}\0${k}`);
                const out = perm.map((i) => block[k][i]);
                block[k].splice(0, block[k].length, ...out);
              }
              for (const ch of block.children || []) shuffleBlock(ch);
            }
          };
          if (rootKids.length) shuffleBlock(state.rootDescribeBlock);
        }
        break;
      }
      case 'test_start': {
        const id = ids.get(event.test) || `${fileId}::${event.test.name}`;
        if (STATE.testId !== id) begin(id);
        break;
      }
      case 'test_done': {
        const id = ids.get(event.test) || `${fileId}::${event.test.name}`;
        if (STATE.testId === id) pending = { id, outcome: outcomeOf(event.test), test: event.test };
        break;
      }
      case 'test_skip':
      case 'test_todo': {
        const id = ids.get(event.test) || `${fileId}::${event.test.name}`;
        if (STATE.testId !== id) begin(id);
        pending = null;
        endTest(id, event.name === 'test_todo' ? 'todo' : 'skipped', event.test);
        break;
      }
      case 'run_finish':
        endPending();
        break;
      default:
    }
  };
  const prev = environment.handleTestEvent;
  environment.handleTestEvent = function handleTestEvent(event, state) {
    handler(event, state);
    return prev ? prev.call(this, event, state) : undefined;
  };
  if (CAP) {
    CAP.beginFileTests();
    if (CAP.label !== label) { CAP.resetFile(); CAP.setCtx('f', label); }
  }
  const t0 = Date.now();
  let result;
  try {
    result = await run(globalConfig, config, environment, runtime, testPath, sendMessageToJest);
    return result;
  } finally {
    endPending();
    controls.closeFile();
    if (CAP && c.dir) {
      try {
        const ok = Boolean(result) && !result.testExecError && !(result.numFailingTests > 0);
        // tests the circus events never bracketed (a failing beforeAll skips them)
        const ended = new Set(CAP.tests.map((t) => t.id));
        for (const [t, id] of ids) if (t && t.type === 'test' && !ended.has(id)) CAP.tests.push({ id, outcome: 'skipped', duration: 0, fingerprint: '', upto: CAP.log.length });
        const capture = CAP.fileCapture({ fileId, project, label, ok, duration: (Date.now() - t0) / 1000 }, runtimeModules(runtime));
        controls.writeJson(path.join(c.dir, 'cache', `${controls.partName(fileId, project).replace(/\.jsonl$/, '')}-${process.pid}.json`), capture);
      } catch (e) {
        process.stderr.write(`detjs cache: capture of ${fileId} not written: ${e && e.stack}\n`);
      }
      CAP.resetFile();
      CAP.setCtx('', '');
    }
  }
};
