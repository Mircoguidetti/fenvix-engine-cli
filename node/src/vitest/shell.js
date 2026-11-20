'use strict';
// Vitest shell: custom test runner (worker side) and sequencer (main side).
//
// Worker side (runner.mjs -> makeRunner): installs the controls before any
// test file is imported, opens one trace part per test file, orders the
// tests of a file (fixed: declaration order; --det-seed: hierarchical
// shuffle file -> describe -> test) and brackets every test with
// begin/end (reseed, clock reset, network counters, fingerprint).
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const controls = require('../controls');
const parallel = require('../parallel');
const repro = require('../repro');

const { STATE } = controls;
const CACHE = process.env.DETJS_CACHE === '1';
const CAP = CACHE ? require('../cache/capture').CAPTURE : null;

/** Write the cache capture of a finished test file (read by the main process, src/cache/proof.js). */
function writeCapture(file, det, project) {
  const fileId = fileIdOf(file, det.root);
  const label = project ? `${project}|${fileId}` : fileId;
  const r = file.result || {};
  const ok = r.state !== 'fail' && !(r.errors && r.errors.length) && !(file.errors && file.errors.length);
  const dur = ['collectDuration', 'setupDuration', 'prepareDuration', 'environmentLoad'].reduce((a, k) => a + (Number(file[k]) || 0), 0) + (Number(r.duration) || 0);
  // tests that never reached the runner hooks (skipped by a failing hook, filtered) count as skipped
  const ended = new Set(CAP.tests.map((t) => t.id));
  for (const [task, id] of det.ids) {
    if (task.type === 'test' && !ended.has(id) && det.fileOf.get(task) === file) CAP.tests.push({ id, outcome: outcomeOf(task) === 'unknown' ? 'skipped' : outcomeOf(task), duration: 0, fingerprint: '', upto: CAP.log.length });
  }
  const capture = CAP.fileCapture({ fileId, project: project || '', label, ok, duration: dur / 1000 });
  const dir = path.join(process.env.DETJS_DIR, 'cache');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${controls.partName(fileId, project).replace(/\.jsonl$/, '')}-${process.pid}.json`), JSON.stringify(capture));
  CAP.beginFileTests();
}

/** Absolute file of a package export (`exports[sub]`), for ESM-only packages. */
function exportFile(pkgDir, sub) {
  const pkg = JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'), 'utf8'));
  let e = pkg.exports && pkg.exports[sub];
  if (!e) return null;
  for (let i = 0; i < 5 && typeof e === 'object'; i++) e = e.import || e.default || e.node || e.require;
  return typeof e === 'string' ? fs.realpathSync(path.join(pkgDir, e)) : null;
}

function vitestDir() {
  const dir = process.env.DETJS_VITEST_DIR;
  if (!dir) throw new Error('detjs: DETJS_VITEST_DIR is not set (run vitest through `detjs vitest`)');
  return dir;
}

/** The default runner class of the project's Vitest (v1-v4: vitest/runners, v5: vitest). */
async function loadBaseRunner(imp = (url) => import(url)) {
  const dir = vitestDir();
  const runners = exportFile(dir, './runners');
  if (runners) {
    const m = await imp(pathToFileURL(runners).href);
    if (m.VitestTestRunner) return m.VitestTestRunner;
  }
  const main = exportFile(dir, '.');
  const m = await imp(pathToFileURL(main).href);
  if (m.TestRunner) return m.TestRunner;
  throw new Error(`detjs: cannot find the default test runner of vitest in ${dir}`);
}

function fileIdOf(file, root) {
  return path.relative(root, file.filepath).split(path.sep).join('/');
}

function outcomeOf(test) {
  const s = test.result && test.result.state;
  return { pass: 'passed', fail: 'failed', skip: 'skipped', todo: 'todo' }[s] || (test.mode === 'todo' ? 'todo' : test.mode === 'skip' ? 'skipped' : 'unknown');
}

/**
 * The worker's command line as Vitest gives it (audit G-2164): detjs' own worker preloads (the cache's early capture,
 * the vm pools' preload) are not shown to test code in process.execArgv.
 */
function hideOwnExecArgv() {
  const own = (f) => typeof f === 'string' && f.startsWith(require('../sites').SHELL_DIR);
  const a = process.execArgv;
  for (let i = a.length - 2; i >= 0; i--) if ((a[i] === '--require' || a[i] === '-r') && own(a[i + 1])) a.splice(i, 2);
  for (let i = a.length - 1; i >= 0; i--) if (/^(?:--require|-r)=/.test(a[i]) && own(a[i].replace(/^[^=]*=/, ''))) a.splice(i, 1);
}

/**
 * detjs' runner class extending `Base` (Vitest's default runner, or the project's own runner composed with it, G-1437).
 * `realm`: the global object test files run in (the worker's, or a vm context's in the vm pools, G-0461).
 */
function makeRunner(Base, realm = globalThis) {
  return class DetRunner extends Base {
    constructor(config) {
      super(config);
      const c = controls.cfg();
      this.__det = { active: c.active, ids: new Map(), fileOf: new Map(), root: process.env.DETJS_ROOT || config.root, opened: null };
      if (c.active) {
        controls.installProcess();
        controls.installRealm(realm, { sameRealm: realm === globalThis });
        // Vitest 5's vm pools: their own copies of Node's modules' named exports, re-synced after the controls
        const req = realm !== globalThis && realm.__vitest_required__;
        if (req && typeof req.syncBuiltinESMExports === 'function') { try { req.syncBuiltinESMExports(); } catch { /* the preload covers it */ } }
        hideOwnExecArgv();
        if (CAP) CAP.install({ role: 'worker', root: this.__det.root });
        // parallel lanes: the paths and ports each file touches (cross-worker hazards, src/parallel.js)
        if (Number(process.env.DETJS_WORKERS || 1) > 1) parallel.installFootprint(this.__det.root);
      }
    }

    __open(filepath, project) {
      const fileId = path.relative(this.__det.root, filepath).split(path.sep).join('/');
      if (this.__det.opened === fileId) return;
      this.__det.opened = fileId;
      // a lane runs one file at a time, in plan order (waits for the lane's previous file); pool id = lane
      parallel.enter(project ? `${project}|${fileId}` : fileId, { runner: 'vitest' });
      controls.openFile(fileId, project);
      if (CAP) CAP.setCtx('f', project ? `${project}|${fileId}` : fileId);
    }

    /** Failed module fetches and the mocker's `__mocks__` lookups of this file's module runner (cache capture). */
    __hookModules() {
      if (!CAP) return;
      const mr = this.moduleRunner;
      const root = (this.config && this.config.root) || this.__det.root;
      CAP.hookModuleRunner(mr, [root]);
      CAP.hookVitestMocker((mr && mr.mocker) || globalThis.__vitest_mocker__);
    }

    async onBeforeCollect(paths) {
      if (this.__det.active) this.__hookModules();
      if (this.__det.active && paths && paths.length) {
        const p = typeof paths[0] === 'string' ? paths[0] : paths[0].filepath;
        this.__open(p, this.config.name);
      }
      if (super.onBeforeCollect) await super.onBeforeCollect(paths);
    }

    async onCollected(files) {
      if (super.onCollected) await super.onCollected(files);
      if (!this.__det.active) return;
      const c = controls.cfg();
      for (const file of files) {
        const fileId = fileIdOf(file, this.__det.root);
        const label = this.config.name ? `${this.config.name}|${fileId}` : fileId;
        // ids in declaration order (duplicates numbered before any shuffle)
        const flat = [];
        const walk = (suite, prefix) => {
          for (const t of suite.tasks || []) {
            const id = `${prefix}::${t.name}`;
            if (t.type === 'suite') { this.__det.ids.set(t, id); walk(t, id); } else { flat.push([t, id]); this.__det.fileOf.set(t, file); }
          }
        };
        this.__det.ids.set(file, fileId);
        walk(file, fileId);
        const unique = controls.uniqueIds(flat.map(([, id]) => id));
        flat.forEach(([t], i) => this.__det.ids.set(t, unique[i]));
        if (c.controls.has('order') && c.shuffle && file.tasks) {
          const keyOf = (t) => (t === file ? label : `${label}${this.__det.ids.get(t).slice(fileId.length)}`);
          const shuffled = controls.shuffleTree(file.tasks, c.orderSeed, label, keyOf, (t) => (t.type === 'suite' ? t.tasks : null));
          file.tasks.splice(0, file.tasks.length, ...shuffled);
        }
        reproCollected(file, this.__det);
      }
    }

    async onBeforeRunSuite(suite) {
      if (this.__det.active) this.__hookModules();
      if (this.__det.active && suite.type !== 'test' && suite.file === suite) this.__open(suite.filepath, this.config.name);
      if (super.onBeforeRunSuite) await super.onBeforeRunSuite(suite);
    }

    async onBeforeRunTask(test) {
      if (super.onBeforeRunTask) await super.onBeforeRunTask(test);
      if (!this.__det.active) return;
      const id = this.__det.ids.get(test) || `${test.file ? fileIdOf(test.file, this.__det.root) : '?'}::${test.name}`;
      if (STATE.testId === id) return; // retry/repeat of the running test
      STATE.beginTest(id);
      if (CAP) CAP.setCtx('t');
      if (test.mode !== 'run' && test.mode !== 'queued') this.__end(test, id, test.mode === 'todo' ? 'todo' : 'skipped');
      else if (test.result && test.result.state === 'fail') this.__end(test, id, 'failed');
    }

    __end(test, id, outcome) {
      const fp = STATE.endTest(outcome);
      if (CAP) {
        CAP.testEnd(id, outcome, ((test.result && test.result.duration) || 0) / 1000, fp);
        CAP.setCtx('f');
      }
    }

    onAfterRunTask(test) {
      if (this.__det.active && STATE.testId !== null) this.__end(test, STATE.testId, outcomeOf(test));
      if (super.onAfterRunTask) return super.onAfterRunTask(test);
      return undefined;
    }

    async onAfterRunFiles(files) {
      if (this.__det.active) {
        controls.closeFile();
        this.__det.opened = null;
        for (const f of files || []) {
          const fileId = fileIdOf(f, this.__det.root);
          parallel.leave(this.config.name ? `${this.config.name}|${fileId}` : fileId);
        }
        for (const f of files || []) reproSide(f, this.__det, this.config.name);
        if (CAP && process.env.DETJS_DIR) {
          for (const f of files || []) {
            try { writeCapture(f, this.__det, this.config.name); } catch (e) { process.stderr.write(`detjs cache: capture of ${f.filepath} not written: ${e && e.stack}\n`); }
          }
        }
      }
      if (super.onAfterRunFiles) await super.onAfterRunFiles(files);
    }
  };
}

// --det-order / --det-collect / --det-outcomes (src/repro.js): the file's tree reduced and ordered to the plan, the
// ids it will run, and (collection only) nothing run at all.
function reproCollected(file, det) {
  const p = repro.plan();
  const idOf = (t) => (t.type === 'suite' ? null : det.ids.get(t) || null);
  const kidsOf = (t) => (t.type === 'suite' ? t.tasks || [] : null);
  if (p && file.tasks && repro.filterTree(file.tasks, idOf, kidsOf, p) === 0) file.mode = 'skip';
  det.collected = det.collected || new Map();
  det.collected.set(file, file.mode === 'skip' && p ? [] : repro.flatIds(file.tasks || [], idOf, kidsOf));
  if (process.env.DETJS_COLLECT === '1') file.mode = 'skip';
}

function reproSide(file, det, project) {
  const c = controls.cfg();
  const fileId = fileIdOf(file, det.root);
  const states = {};
  const exceptions = {};
  const walk = (suite, inherited) => {
    const err = suite.result && suite.result.errors && suite.result.errors.length && suite !== file ? suite.result.errors[0] : inherited;
    for (const t of suite.tasks || []) {
      if (t.type === 'suite') { walk(t, err); continue; }
      const id = det.ids.get(t);
      if (!id) continue;
      let o = outcomeOf(t);
      const own = t.result && t.result.errors && t.result.errors[0];
      if (own) exceptions[id] = repro.exceptionOf(own, 'call', det.root);
      else if (err && o !== 'passed') { exceptions[id] = repro.exceptionOf(err, 'setup', det.root); o = 'error'; }
      states[id] = o;
    }
  };
  const fileErr = file.result && file.result.errors && file.result.errors.length ? file.result.errors[0] : null;
  walk(file, fileErr);
  repro.writeSide(c.dir, controls.partName(fileId, project), {
    file: fileId, project: project || '', collected: (det.collected && det.collected.get(file)) || [],
    states, exceptions, file_error: fileErr ? repro.exceptionOf(fileErr, 'collect', det.root) : null,
  });
}

module.exports = { makeRunner, loadBaseRunner, exportFile, fileIdOf };
