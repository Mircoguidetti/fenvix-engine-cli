'use strict';
// `detjs mocha`: preloaded (`--require`) in the Mocha process (the driver) and in the per-file processes.
//
// Driver, single mode (--det without --det-cache): Mocha's usual single process. The files Mocha loads are the
// plan's (ordered by detjs: sorted, or shuffled with --det-seed; `--file` files first), Level 0 is installed, each
// file is seeded when Mocha requires it, the suite tree is shuffled with the seed, and Runner events bracket every
// test (`test` begins it; it ends when the next test begins or the run ends, so its afterEach hooks are inside).
//
// Driver, per-file mode (--det-cache): the driver only reports. Mocha's own parallel machinery replays the events
// of each file into the user's reporter (ParallelBufferedRunner), but the worker pool is replaced by one fresh
// process per file, run one after the other in the plan's order (src/mocha/child.js): skipping a file must not
// change the context another file runs in. Each file process loads the `--file` files and its spec, with the
// serial-mode options (no forced forbidOnly), and writes its events for the driver and its cache capture for detjs.
const fs = require('node:fs');
const path = require('node:path');

const env = process.env;
let role = null;
// worker threads of a test process inherit its execArgv and environment: they are part of that process
if (env.DETJS === '1' && !env.DETJS_MO_INNER && env.DETJS_MO_PLAN && require('node:worker_threads').isMainThread) {
  if (env.DETJS_MO_CHILD) role = 'file';
  else if (env.DETJS_MO_DRIVER === '1') role = 'driver';
}

const KEY = Symbol.for('detjs.mocha');

function fileIdOf(root, f) {
  return path.relative(root, path.resolve(f)).split(path.sep).join('/');
}

if (role) {
  const plan = JSON.parse(fs.readFileSync(env.DETJS_MO_PLAN, 'utf8'));
  const root = env.DETJS_ROOT || process.cwd();
  env.DETJS_MO_INNER = '1'; // processes the tests start do not take part
  if (env.DETJS_MO_NODE_OPTIONS !== undefined && (role === 'file' || JSON.parse(fs.readFileSync(env.DETJS_MO_PLAN, 'utf8')).mode !== 'perfile')) env.NODE_OPTIONS = env.DETJS_MO_NODE_OPTIONS;
  const perFile = plan.mode === 'perfile';
  const testsHere = role === 'file' || !perFile;
  const { FileProcess } = testsHere ? require('../fileproc') : {};
  const fp = testsHere ? new FileProcess(root) : null;
  const { load, mochaClass } = require('./mod');
  const Mocha = mochaClass(plan.mochaDir);
  const c = fp ? fp.c : null;
  const shuffle = Boolean(c && c.shuffle && c.controls.has('order'));
  const results = { files: {}, globalFixtures: false };
  globalThis[KEY] = { role, plan, fp, results };

  if (role === 'file') fp.open(fileIdOf(root, env.DETJS_MO_CHILD));
  else if (fp) fp.open('<mocha>');

  // -- the files Mocha loads ---------------------------------------------------------------------------------
  const planned = () => (perFile && role === 'driver' ? plan.specs : role === 'file' ? [...plan.fileArgs, env.DETJS_MO_CHILD] : [...plan.fileArgs, ...plan.specs]);
  const seedOnRequire = (mocha) => {
    if (!fp || role === 'file' || mocha.__detjsSeed) return;
    mocha.__detjsSeed = true;
    // single mode: module-level randomness of each file starts from that file's own seed
    mocha.suite.on('pre-require', (_ctx, file) => { try { require('../seeds').seedFile(fileIdOf(root, file)); } catch { /* ignore */ } });
  };
  for (const name of ['loadFiles', 'loadFilesAsync']) {
    const real = Mocha.prototype[name];
    if (typeof real !== 'function') continue;
    Mocha.prototype[name] = function detjsLoad(...a) {
      this.files = planned();
      if (perFile && role === 'driver') return name === 'loadFilesAsync' ? Promise.resolve() : undefined; // the file processes load them
      seedOnRequire(this);
      return real.apply(this, a);
    };
  }

  // -- per-file mode: the driver's pool runs each file in a fresh process ---------------------------------------
  if (perFile && role === 'driver') {
    const { BufferedWorkerPool } = load(plan.mochaDir, 'lib/nodejs/buffered-worker-pool');
    const { deserialize } = load(plan.mochaDir, 'lib/nodejs/serializer');
    const { spawnSync } = require('node:child_process');
    const childJs = path.join(__dirname, 'child.js');
    let n = 0;
    BufferedWorkerPool.create = () => ({
      async run(file, options) {
        const k = n++;
        const optsPath = path.join(plan.dir, `mocha-opts-${k}.js`);
        const outPath = path.join(plan.dir, `mocha-result-${k}.json`);
        fs.writeFileSync(optsPath, BufferedWorkerPool.serializeOptions(options));
        const r = spawnSync(process.execPath, [...process.execArgv, childJs],
          { stdio: 'inherit', env: { ...env, DETJS_MO_INNER: '', DETJS_MO_CHILD: file, DETJS_MO_OPTS: optsPath, DETJS_MO_OUT: outPath } });
        const fid = fileIdOf(root, file);
        let res = null;
        try { res = JSON.parse(fs.readFileSync(outPath, 'utf8')); } catch { /* below */ }
        results.files[fid] = { status: r.status, signal: r.signal, failures: res ? res.failureCount : null };
        if (!res) throw new Error(`detjs mocha: ${fid} ended without results (exit ${r.status}${r.signal ? `, signal ${r.signal}` : ''})`);
        // a process that failed after its tests (an exception at exit, a signal) fails like Mocha's single process
        if ((r.status !== 0 && !(res.failureCount > 0)) || r.signal) throw new Error(`detjs mocha: ${fid}: the file's process exited with ${r.signal || r.status} after its tests`);
        return deserialize(res);
      },
      async terminate() {},
      stats() { return {}; },
    });
    const realRun = Mocha.prototype.run;
    Mocha.prototype.run = function detjsRun(...a) {
      this.files = plan.specs;
      if (typeof this.parallelMode === 'function') this.parallelMode(true);
      results.globalFixtures = Boolean((this.options.globalSetup && this.options.globalSetup.length)
        || (this.options.globalTeardown && this.options.globalTeardown.length));
      return realRun.apply(this, a);
    };
  }

  // -- test processes: order and brackets -----------------------------------------------------------------------
  if (testsHere) {
    const Runner = Mocha.Runner;
    const shuffleSuite = (suite) => {
      const native = require('../native');
      const key = `${suite.file ? fileIdOf(root, suite.file) : ''}::${suite.titlePath().join('::')}`;
      for (const k of ['tests', 'suites']) {
        const list = suite[k];
        if (!Array.isArray(list) || list.length < 2) continue;
        const perm = native.shuffleIndices(list.length, c.seed, `${key}\u0000${k}`);
        const out = perm.map((i) => list[i]);
        list.splice(0, list.length, ...out);
      }
      for (const s of suite.suites || []) shuffleSuite(s);
    };
    const fileOf = (r) => { for (let x = r; x; x = x.parent) if (x.file) return fileIdOf(root, x.file); return role === 'file' ? fp.fileId : '<mocha>'; };
    const realRunnerRun = Runner.prototype.run;
    Runner.prototype.run = function detjsRunnerRun(...a) {
      if (this.__detjs) return realRunnerRun.apply(this, a);
      this.__detjs = true;
      if (shuffle && this.suite) shuffleSuite(this.suite);
      let cur = null; // {test, base}
      const outcomeOf = (t) => (t.state === 'passed' ? 'passed' : t.state === 'failed' ? 'failed' : t.isPending && t.isPending() ? 'skipped' : t.state === 'pending' ? 'skipped' : 'failed');
      const endCur = () => {
        if (!cur) return;
        const o = outcomeOf(cur.test);
        cur = null;
        fp.end(o);
      };
      this.on('test', (t) => {
        const names = t.titlePath();
        const file = fileOf(t);
        const base = `${file}::${names.join('::')}`;
        if (cur && cur.base === base && typeof t.currentRetry === 'function' && t.currentRetry() > 0) { cur.test = t; return; } // a retry
        endCur();
        fp.begin(fp.idFor(names, file));
        cur = { test: t, base };
      });
      this.on('pending', (t) => {
        if (cur && cur.test === t) return; // skipped from inside (this.skip()): its outcome says so
        endCur();
        fp.skipped(fp.idFor(t.titlePath(), fileOf(t)));
      });
      this.on('fail', (r) => {
        const f = fileOf(r);
        results.files[f] = results.files[f] || {};
        results.files[f].failed = true;
      });
      this.on('end', () => endCur());
      return realRunnerRun.apply(this, a);
    };
  }

  if (fp) {
    // the file (single mode: the run) ends after every other 'exit' listener ran
    const realEmit = process.emit;
    let closed = false;
    process.emit = function emit(ev, ...a) {
      if (ev !== 'exit' || closed) return realEmit.call(this, ev, ...a);
      let r;
      try { r = realEmit.call(this, ev, ...a); } finally {
        closed = true;
        const code = process.exitCode !== undefined && process.exitCode !== null ? Number(process.exitCode) : Number(a[0] || 0);
        fp.close({ ok: code === 0 && !Object.values(results.files).some((x) => x.failed) });
      }
      return r;
    };
  }
  if (role === 'driver') {
    process.on('exit', () => { try { fs.writeFileSync(path.join(plan.dir, 'mocha-results.json'), JSON.stringify(results)); } catch { /* none */ } });
  }
}
