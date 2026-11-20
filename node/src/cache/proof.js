'use strict';
// Cache with proof for detjs (`detjs vitest|jest --det --det-cache=DIR|URL`): main-process side.
//
// A test file's previous results are reused, and the file is not run, only when every input its tests depended
// on is unchanged; each reused result comes with a receipt (same store, keys, receipts and reuse check as the
// Python shell, crates/detpy-core/src/proof.rs). What counts as an input is recorded while the tests run
// (src/cache/capture.js):
//
// * code: every module loaded in the test's process (project modules by content; installed packages through the
//   runtime identity) and the nearest package.json of each project module;
// * files read (content, missing paths, listings, existence, link targets), native addons;
// * environment variables read and machine facts read through `os`;
// * runtime identity (src/cache/runtime-id.js): node binary and versions, shared libraries, time zone, locale,
//   CPU level, lockfiles and every installed file under node_modules;
// * configuration: detjs and its Level 0 options, the runner and its resolved configuration, the configuration
//   files of the repository (tsconfig, babel, swc, postcss, browserslist, vite/vitest/jest configs, .env);
// * start-up: what the main process read before the tests started (configuration modules, globalSetup and what
//   it read), the processes it ran and what they gave back;
// * the clock's epoch, only for tests that read the clock.
//
// The unit of reuse is the test file: all of its tests are reused or all run, so in-memory state shared by the
// tests of a file can never mix a reused result with a fresh one. The inputs of a test are cumulative (its
// file's collection and every earlier test of its process are inputs too). Never reused: a failure (a failed
// test, or a file-level error); a test that started a process or a worker thread, opened a socket (loopback
// included), used OS entropy without --det-urandom, read /proc, /sys or /dev, recorded the network, or read a file
// that another test file or the start-up code wrote.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const native = require('../native');
const { CAPTURE, machineFacts } = require('./capture');
const { runtimeIdentity, startPackages } = require('./runtime-id');

const VERSION = require('../../package.json').version;
const CONFIG_FILES = /^(tsconfig.*\.json|jsconfig.*\.json|babel\.config\.[cm]?[jt]s(on)?|\.babelrc(\.[cm]?[jt]s(on)?)?|\.swcrc|postcss\.config\.[cm]?[jt]s|\.postcssrc(\.[a-z]+)?|\.browserslistrc|browserslist|vite\.config\.[cm]?[jt]s|vitest\.config\.[cm]?[jt]s|vitest\.(workspace|projects)\.[cm]?[jt]s(on)?|jest\.config\.[cm]?[jt]s(on)?|jest\.preset\.[cm]?js|\.env(\..+)?|\.swcrc|\.nvmrc|\.node-version)$/;
const SKIP_DIRS = new Set(['node_modules', '.git', '.detjs', '.hg', '.svn', 'coverage', '.nx', '.turbo']);
// the flags that make a result not cached: Rust (crates/detpy-core/src/node_session.rs), as the rest of the session
// policy (review R-032 claim 3, DECISIONS 2026-11-18)
const UNCACHEABLE = native.uncacheableTable();

function digest(x) {
  return native.digest(typeof x === 'string' ? x : JSON.stringify(x));
}

// detjs' own per-session values inside a runner configuration (runner shim path, sequencer, the run's seed)
const OWN_STRING = /[\\/]node_modules[\\/]\.detjs[\\/]runner-\d+\.mjs$/;
// output and selection settings never change a result; the resolved configuration repeats them at several depths
const ANY_VOLATILE = new Set(['webSocketToken', 'tokenCreated', 'outputFile', 'reporters', 'reporter', 'shard', 'changed',
  'passWithNoTests', 'filters', 'cliExclude', 'related',
  // worker counts, wherever Vitest repeats them (resolved projects, CLI options): serial and parallel lanes give the
  // same results (a placement that could change one is refused or not cached: src/parallel.js)
  'maxWorkers', 'minWorkers', 'fileParallelism', 'maxThreads', 'minThreads', 'maxForks', 'minForks']);
const NESTED_VOLATILE = new Set(['api.token', 'sequence.seed', 'sequence.sequencer', 'sequence.shuffle', 'sequence.concurrent']);

/** Deterministic, cycle-safe digestable form of a configuration value (`volatile`: top-level keys left out). */
function stable(v, volatile, depth = 0, seen = new WeakSet(), parent = '') {
  if (v === null || v === undefined) return v ?? null;
  const t = typeof v;
  if (t === 'string') return OWN_STRING.test(v) ? '<detjs-runner>' : v;
  if (t === 'number' || t === 'boolean') return v;
  if (t === 'bigint') return `${v}n`;
  if (t === 'symbol') return String(v);
  if (t === 'function') return `fn:${v.name}:${native.digest(Function.prototype.toString.call(v))}`;
  if (v instanceof RegExp) return `re:${v.source}/${v.flags}`;
  if (depth > 7) return '<deep>';
  if (seen.has(v)) return '<cycle>';
  seen.add(v);
  try {
    if (Array.isArray(v)) return v.map((x) => stable(x, volatile, depth + 1, seen, parent));
    if (v instanceof Map) return [...v.entries()].map(([k, x]) => [String(k), stable(x, volatile, depth + 1, seen, String(k))]);
    if (v instanceof Set) return [...v].map((x) => stable(x, volatile, depth + 1, seen, parent));
    const out = {};
    for (const k of Object.keys(v).sort()) {
      if (depth === 0 && volatile && volatile.has(k)) continue;
      if (NESTED_VOLATILE.has(`${parent}.${k}`) || ANY_VOLATILE.has(k)) continue;
      let x;
      try { x = v[k]; } catch { x = '<getter error>'; }
      out[k] = stable(x, volatile, depth + 1, seen, k);
    }
    return out;
  } finally {
    seen.delete(v);
  }
}

/** Configuration files of the repository (outside node_modules): [[relative path, digest]]. */
// Vite / Vitest configuration files below the root: with Vitest, keyed through the project that loads them (its
// configuration file, the files it imports and its resolved configuration), not as a configuration of every file.
const NESTED_VITE_CONFIG = /^(vite|vitest)\.config\.[cm]?[jt]s$/;

function configFiles(root, { nestedViteConfigs = true, extra = null } = {}, limit = 200000) {
  const out = [];
  let n = 0;
  const walk = (dir, rel) => {
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      if (n++ > limit) return;
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name) || (e.name.startsWith('.') && e.name !== '.config' && e.name !== '.storybook')) continue;
        walk(path.join(dir, e.name), r);
      } else if (!nestedViteConfigs && rel && NESTED_VITE_CONFIG.test(e.name)) {
        continue;
      } else if (CONFIG_FILES.test(e.name) || (r === 'package.json') || (extra && extra.test(e.name))) {
        out.push([r, native.fileDigest(path.join(dir, e.name)) || 'unreadable']);
      }
    }
  };
  walk(root, '');
  return out.sort();
}

/**
 * Adds a project's configuration part as `project:<name>`. Two projects with the same name (Jest projects without a
 * displayName) both stay in the digest, as `project:<name>#2`, ...; such a name is not split per project (below).
 */
function projectPart(out, name, value) {
  let key = `project:${name}`;
  for (let n = 2; Object.prototype.hasOwnProperty.call(out, key); n++) key = `project:${name}#${n}`;
  out[key] = value;
}

/** The core's miss texts name the Python shell's terms. */
function neutral(text) {
  if (text.startsWith('config:')) return 'config: runner configuration, detjs options or configuration files changed';
  if (text.startsWith('runtime:')) return 'runtime: node, native libraries, time zone, locale, CPU level or installed packages changed';
  return text;
}

/**
 * The variables that name a test process's placement and whose value is not the serial one (`placementVars`): in a
 * parallel run the runner's worker / pool id is the lane; serially Jest's `JEST_WORKER_ID` and Vitest's
 * `VITEST_POOL_ID` are 1 (keyed as such: `SERIAL_PLACEMENT`), while `VITEST_WORKER_ID` counts the files before it.
 */
const SERIAL_PLACEMENT = { jest: { JEST_WORKER_ID: '1' }, vitest: { VITEST_POOL_ID: '1' } };
function placementVars(runner, parallelRun) {
  if (runner === 'vitest') return new Set(parallelRun ? ['VITEST_POOL_ID', 'VITEST_WORKER_ID'] : ['VITEST_WORKER_ID']);
  if (runner === 'jest') return new Set(parallelRun ? ['JEST_WORKER_ID'] : []);
  return new Set();
}

/**
 * Flags that depend on placement, added to a capture before the session policy records it (positions: a flag
 * applies to the tests that end after it): a read of a variable in `vars` right after the read, unless the read is
 * part of a copy of the whole environment (contiguous reads after an enumeration, keyed as the whole environment:
 * docs/NODE-CACHE.md); a file that touched a path or port another lane touched, or that ran after a file that left
 * process-wide state changed (src/parallel.js `collect`), from the start.
 */
function placementFlags(c, fileFlags, vars) {
  const items = c.items || [];
  const ins = []; // [position, item]
  const f = fileFlags && fileFlags.get(c.label);
  if (f) ins.push([0, ['flag', f[0], f[1]]]);
  let burst = false; // inside a run of environment reads that started with an enumeration
  items.forEach((it, i) => {
    if (it[0] !== 'env') { burst = false; return; }
    if (it[1] === '*') { burst = true; return; }
    if (!burst && vars && vars.has(it[1])) ins.push([i + 1, ['flag', 'placement', it[1]]]);
  });
  if (!ins.length) return;
  const out = [];
  const shift = new Array(items.length + 1).fill(0);
  let k = 0;
  for (let i = 0; i <= items.length; i++) {
    while (k < ins.length && ins[k][0] === i) { out.push(ins[k][1]); k++; }
    shift[i] = k;
    if (i < items.length) out.push(items[i]);
  }
  c.items = out;
  // a test's inputs are the first `upto` items: the items inserted at or before that position are its own too
  for (const t of c.tests || []) t.upto = (t.upto || 0) + shift[Math.min(t.upto || 0, items.length)];
}

function ownFile(nodeid) {
  return nodeid.split('::', 1)[0].split('@@', 1)[0];
}

class ProofSession {
  /**
   * @param opts parsed detjs options (opts.cache = directory or service URL)
   * @param root project root; @param runner 'vitest' | 'jest'; @param run session.prepare() result
   */
  constructor(opts, root, runner, run, env0) {
    this.opts = opts;
    this.root = root;
    this.runner = runner;
    this.run = run;
    this.env0 = {};
    for (const [k, v] of Object.entries(env0)) if (!/^(DETJS($|_)|FENVIX_CACHE_)/.test(k)) this.env0[k] = v;
    this.runId = `${new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)}-${crypto.randomBytes(4).toString('hex')}`;
    this.remote = null;
    let dir = opts.cache;
    if (/^https?:\/\//.test(dir)) {
      const { RemoteCache } = require('./remote');
      this.remote = new RemoteCache(dir, this);
      dir = this.remote.localDir;
    } else {
      dir = path.resolve(root, dir);
    }
    this.dir = dir;
    fs.mkdirSync(dir, { recursive: true });
    this.store = new native.ProofCache(dir, root);
    this.receiptsPath = path.resolve(root, opts.cacheReceipts || path.join('.detjs', 'receipts.jsonl'));
    this.summaryPath = path.resolve(root, opts.cacheSummary || path.join('.detjs', 'cache-summary.json'));
    this.verify = Boolean(opts.cacheVerify);
    this.hits = new Map(); // nodeid -> receipt
    this.misses = new Map(); // nodeid -> why
    this.notCached = new Map(); // nodeid -> why
    this.reusedFiles = new Map(); // key -> {fileId, project, tests, duration}
    this.decided = false;
    this.disabled = null; // reason the cache is off for this session
    this.uncacheableProjects = new Map(); // project name -> reason
    this.t = { identity: 0, check: 0, record: 0 };
    this.recorded = 0;
    this.specKeys = new Set();
    this.configParts = {};
    this.epochMs = Number(run.cfg.epochNs / 1000000n);
  }

  /** Start capturing in the main process (before the runner loads its configuration). */
  installMain({ mainAnyReads }) {
    process.env.DETJS_CACHE = '1';
    CAPTURE.install({ role: 'main', root: this.root, mainAnyReads });
    CAPTURE.phase = 'startup';
    CAPTURE.setCtx('', '');
    // the installed packages' digest runs on a background thread while the runner starts (decide() awaits it)
    if (process.env.DETJS_CACHE_IDENTITY !== 'sync') {
      try {
        this.quiet(() => { this.pkgPending = startPackages(this.root, this.env0); });
        CAPTURE.watchInstalled(this.pkgPending.roots);
      } catch { this.pkgPending = null; }
    }
  }

  quiet(fn) {
    CAPTURE.busy++;
    try { return fn(); } finally { CAPTURE.busy--; }
  }

  /** Configuration digest from the runner's resolved configuration (parts: name -> digestable value). */
  setConfig(parts, scan = {}) {
    this.quiet(() => {
      const c = this.run.cfg;
      const level0 = {
        seed: String(c.seed), shuffle: c.shuffle, controls: [...c.controls].sort(), tick: c.tickNs, tickAdapt: c.tickAdapt,
        timerBudget: c.timerBudget, timers: c.timers, net: this.run.netMode, allow: c.allowHosts, urandom: c.urandom, sites: c.sites,
      };
      const engineDir = path.resolve(__dirname, '..', '..');
      const engine = JSON.parse(native.treeDigest([['src', path.join(engineDir, 'src')], ['bin', path.join(engineDir, 'bin')]], '/', [], null, 10000, 2)).digest
        + (native.fileDigest(path.join(engineDir, 'package.json')) || '');
      Object.assign(this.configParts, {
        detjs: VERSION,
        engine,
        addon: native.fileDigest(native.__path) || '',
        level0: digest(level0),
        cassette: this.run.netMode === 'replay' ? (native.fileDigest(this.run.cassette) || 'missing') : '',
        cwd: path.relative(this.root, process.cwd()),
        files: digest(configFiles(this.root, scan)),
      });
      for (const [k, v] of Object.entries(parts)) this.configParts[k] = typeof v === 'string' ? v : digest(v);
      if (process.env.DETJS_CACHE_DEBUG) {
        fs.mkdirSync(path.join(this.root, '.detjs'), { recursive: true });
        fs.writeFileSync(path.join(this.root, '.detjs', `cache-config-${process.env.DETJS_CACHE_DEBUG}.json`), JSON.stringify(parts, null, 1));
      }
      this.digests();
    });
  }

  /** A configuration part every file is keyed by, known only once the runner found its files (Jest's mocks). */
  addGlobalPart(name, value) {
    this.quiet(() => {
      this.configParts[name] = typeof value === 'string' ? value : digest(value);
      if (this.configDigest !== undefined) this.digests();
    });
  }

  digests() {
    {
      const keys = Object.keys(this.configParts).sort();
      this.configDigest = digest(keys.map((k) => [k, this.configParts[k]]));
      // Per project: a test file runs with its own project's resolved configuration and the global parts (detjs,
      // Level 0, runner version and options, configuration files by content), not with another project's. A file
      // of a project whose name is not unique, or that has no part, is keyed by the whole digest.
      const global = digest(keys.filter((k) => !k.startsWith('project:')).map((k) => [k, this.configParts[k]]));
      this.projectConfig = new Map();
      for (const k of keys) {
        if (!k.startsWith('project:') || k.includes('#')) continue;
        const name = k.slice('project:'.length);
        if (keys.some((x) => x.startsWith(`${k}#`))) continue;
        this.projectConfig.set(name, digest(['project', global, this.configParts[k]]));
      }
    }
  }

  /** The configuration digest a file of `project` is keyed by. */
  configFor(project) {
    return (this.projectConfig && this.projectConfig.get(project || '')) || this.configDigest;
  }

  /** The identity with the package digest started at session start, unless the package trees may have changed since. */
  async identityAsync() {
    if (this.runtimeDigest || !this.pkgPending) return this.identity();
    const t0 = process.hrtime.bigint();
    let pre = null;
    try { pre = await this.pkgPending.promise; } catch { pre = null; }
    this.pkgPending.waited = Number(process.hrtime.bigint() - t0) / 1e9;
    // something wrote into an installed package tree, or a start-up process ran (it may have installed): again
    const stale = CAPTURE.installedTouched || CAPTURE.startup.length > 0;
    this.pkgPending.used = Boolean(pre && !stale);
    this.t.identity += Number(process.hrtime.bigint() - t0) / 1e9;
    return this.identity(pre && !stale ? pre.json : null);
  }

  identity(packages = null) {
    if (this.runtimeDigest) return;
    const t0 = process.hrtime.bigint();
    this.quiet(() => {
      this.rid = runtimeIdentity(this.root, this.env0, packages);
      this.runtimeDigest = this.rid.digest;
      this.machine = machineFacts();
      // the runner's placement variables as a serial run gives them to every test (parallel reads are flagged)
      this.curEnv = { ...this.env0, ...this.machine, ...(SERIAL_PLACEMENT[this.runner] || {}) };
    });
    this.t.identity += Number(process.hrtime.bigint() - t0) / 1e9;
  }

  startupDigest() {
    const s = CAPTURE.startup;
    return s.length ? digest(s) : '';
  }

  noteProject(name, reason) {
    if (reason) this.uncacheableProjects.set(name || '', reason);
  }

  idOf(fileId, project) {
    return project ? `${fileId}@@${project}` : fileId;
  }

  testKey(testId, project) {
    if (!project) return testId;
    const i = testId.indexOf('::');
    return i < 0 ? `${testId}@@${project}` : `${testId.slice(0, i)}@@${project}${testId.slice(i)}`;
  }

  /**
   * Reuse decision at the end of start-up (the runner's file ordering), for `files` = [{fileId, project, key}].
   * Returns the set of keys of the files that are not run.
   */
  async decide(files) {
    const skip = new Set();
    if (this.decided) {
      for (const k of this.reusedFiles.keys()) skip.add(k);
      return this.verify ? new Set() : skip;
    }
    this.decided = true;
    for (const f of files) this.specKeys.add(f.fileId);
    CAPTURE.scanModules();
    CAPTURE.phase = 'run';
    await this.identityAsync();
    if (this.disabled) return skip;
    const t0 = process.hrtime.bigint();
    this.quiet(() => {
      this.store.begin(this.configDigest, this.runtimeDigest, this.epochMs, this.curEnv);
      this.store.setStartup(this.startupDigest());
    });
    if (this.remote) {
      try { await this.remote.pull(files); } catch (e) { this.remote.fail('pull', e); }
    }
    this.quiet(() => {
      for (const f of files) {
        const proj = f.project || '';
        if (this.uncacheableProjects.has(proj)) {
          this.misses.set(this.idOf(f.fileId, proj), `uncacheable-project: ${this.uncacheableProjects.get(proj)}`);
          continue;
        }
        this.store.setConfig(this.configFor(proj));
        const r = this.checkFile(f.fileId, proj);
        if (r.ok) {
          this.reusedFiles.set(f.key, { fileId: f.fileId, project: proj, tests: r.tests, duration: r.duration });
          for (const [nid, rc] of r.receipts) this.hits.set(nid, rc);
          skip.add(f.key);
        } else {
          this.misses.set(this.idOf(f.fileId, proj), r.why);
        }
      }
    });
    this.t.check += Number(process.hrtime.bigint() - t0) / 1e9;
    return this.verify ? new Set() : skip;
  }

  /** {ok, receipts, tests, duration} or {ok: false, why}. */
  checkFile(fileId, project) {
    const mid = this.idOf(fileId, project);
    const m = this.store.check(mid);
    if (!m.ok) return { ok: false, why: neutral(m.text) };
    const entry = JSON.parse(this.store.entry(mid));
    const tests = (entry.report && entry.report.tests) || [];
    const receipts = [[mid, { ...JSON.parse(m.text), kind: 'file' }]];
    for (const t of tests) {
      const nid = this.testKey(t, project);
      const r = this.store.check(nid);
      if (!r.ok) return { ok: false, why: `${neutral(r.text)} [${t}]` };
      receipts.push([nid, JSON.parse(r.text)]);
    }
    return { ok: true, receipts, tests, duration: entry.duration || 0 };
  }

  // -- end of session ---------------------------------------------------------------------------------------------
  readCaptures() {
    const dir = path.join(this.run.dir, 'cache');
    const out = [];
    let names = [];
    try { names = fs.readdirSync(dir).sort(); } catch { return out; }
    for (const n of names) {
      let c;
      try { c = JSON.parse(fs.readFileSync(path.join(dir, n), 'utf8')); } catch { continue; /* truncated: not recorded */ }
      placementFlags(c, this.parallelFlags, placementVars(this.runner, Number(process.env.DETJS_WORKERS || 1) > 1));
      // a shell whose test processes cannot see the runner's verdict on the file (node:test, Mocha per-file
      // processes) corrects `ok` from the runner's own results
      out.push(this.captureFilter ? this.captureFilter(c) : c);
    }
    return out;
  }

  /** Record the entries of the files that ran; write receipts and the summary (synchronous part). */
  finishSync(extraCaptures = []) {
    if (this.finished) return this.lines(this.summary());
    this.finished = true;
    const t0 = process.hrtime.bigint();
    let captures = [];
    this.quiet(() => {
      captures = [...this.readCaptures(), ...extraCaptures];
      if (!this.disabled) this.identity();
    });
    if (!this.disabled && this.runtimeDigest && this.configDigest) {
      this.quiet(() => this.recordAll(captures));
    }
    this.t.record += Number(process.hrtime.bigint() - t0) / 1e9;
    this.quiet(() => {
      try { this.store.save(); } catch (e) { this.error = `save: ${e.message}`; }
      this.writeReceipts();
    });
    if (this.remote && this.exiting && !this.pushed) {
      // the process is exiting (Jest --forceExit): push from a child process, synchronously
      this.pushed = true;
      this.quiet(() => require('./remote').pushSync(this.remote));
    }
    return this.writeSummary();
  }

  writeSummary() {
    const s = this.summary();
    this.quiet(() => {
      try {
        fs.mkdirSync(path.dirname(this.summaryPath), { recursive: true });
        fs.writeFileSync(this.summaryPath, JSON.stringify(s, null, 1));
        fs.writeFileSync(path.join(path.dirname(this.summaryPath), 'cache-identity.json'),
          JSON.stringify({ runtime: this.rid, config: this.configParts }, null, 1));
      } catch { /* report only */ }
    });
    return this.lines(s);
  }

  /** finishSync, then push to the shared cache service (if any). */
  async finish(extraCaptures = []) {
    this.finishSync(extraCaptures);
    if (this.remote && !this.pushed) {
      this.pushed = true;
      try { await this.remote.push(); } catch (e) { this.remote.fail('push', e); }
    }
    return this.writeSummary();
  }

  /**
   * Record the entries of the files that ran: the observation of each capture log, the entries, the reasons a result
   * is not cached, the verified comparisons and the written paths are the Rust session policy
   * (`detpy_core::node_session::record_session`, review R-032 claim 3); here the inputs are gathered.
   */
  recordAll(captures) {
    const curEnv = {};
    // an own string value only: a read of `process.env.__proto__` or `.constructor` is the absence of a variable
    for (const k of Object.keys(this.curEnv)) if (typeof this.curEnv[k] === 'string') curEnv[k] = this.curEnv[k];
    const projects = new Set(['', ...captures.map((c) => c.project || '')]);
    const configFor = {};
    for (const p of projects) configFor[p] = this.configFor(p);
    const hits = {};
    for (const [nid, rc] of this.hits) hits[nid] = rc.outcome;
    // Jest workers' own items outside any file (src/jest/worker.js): global inputs of every file, as in band
    const global = CAPTURE.global.slice();
    const seen = new Set(global.map((it) => JSON.stringify(it)));
    for (const c of captures) {
      for (const it of c.worker_global || []) { const k = JSON.stringify(it); if (!seen.has(k)) { seen.add(k); global.push(it); } }
      delete c.worker_global;
    }
    const input = {
      global, spec_keys: [...this.specKeys], captures, cur_env: curEnv,
      urandom: Boolean(this.run.cfg.urandom), epoch_ms: this.epochMs === undefined ? null : this.epochMs,
      run_id: this.runId, runtime: this.runtimeDigest, startup: this.startupDigest(), config_for: configFor,
      uncacheable_projects: [...this.uncacheableProjects.keys()], verify: Boolean(this.verify), hits,
    };
    const text = JSON.stringify(input);
    if (process.env.DETJS_POLICY_DUMP) {
      // test-only: the inputs of the policy, for test/policy-equivalence.test.js
      try {
        fs.mkdirSync(process.env.DETJS_POLICY_DUMP, { recursive: true });
        fs.writeFileSync(path.join(process.env.DETJS_POLICY_DUMP, `${this.runId}-${process.pid}.json`), text);
      } catch { /* test aid only */ }
    }
    const out = JSON.parse(this.store.recordSession(text));
    this.recorded += out.recorded;
    for (const [nid, why] of out.not_cached) this.notCached.set(nid, why);
    this.verified = [...(this.verified || []), ...out.verified];
    this.ranFiles = out.ran_files;
  }

  writeReceipts() {
    try {
      fs.mkdirSync(path.dirname(this.receiptsPath), { recursive: true });
      const hits = [...this.hits].map(([nid, r]) => [nid, JSON.stringify(r)]);
      fs.writeFileSync(this.receiptsPath, native.receiptLines(hits, [...this.misses], Boolean(this.verify)));
    } catch { /* report only */ }
  }

  summary() {
    const kinds = {};
    for (const why of this.misses.values()) { const k = why.split(':', 1)[0].replace(/^.*?: /, ''); kinds[k] = (kinds[k] || 0) + 1; }
    const nc = {};
    for (const why of this.notCached.values()) { const k = why.split(':', 1)[0]; nc[k] = (nc[k] || 0) + 1; }
    let reusedTests = 0;
    let reusedSeconds = 0;
    for (const f of this.reusedFiles.values()) { reusedTests += f.tests.length; reusedSeconds += f.duration; }
    const verified = this.verified || [];
    return {
      run: this.runId,
      runner: this.runner,
      verify_mode: this.verify,
      reused_files: this.reusedFiles.size,
      reused_tests: reusedTests,
      ran_files: this.ranFiles || {},
      reused_files_list: [...this.reusedFiles.values()].map((f) => (f.project ? `${f.fileId}@@${f.project}` : f.fileId)),
      reused_recorded_seconds: Math.round(reusedSeconds * 1000) / 1000,
      missed_files: this.misses.size,
      miss_reasons: kinds,
      misses: Object.fromEntries([...this.misses.entries()].slice(0, 400)),
      recorded: this.recorded,
      not_cached: nc,
      not_cached_detail: Object.fromEntries([...this.notCached.entries()].slice(0, 200)),
      not_cached_top: (() => {
        const c = new Map();
        for (const w of this.notCached.values()) { const k = w.slice(0, 220); c.set(k, (c.get(k) || 0) + 1); }
        return Object.fromEntries([...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 80));
      })(),
      identity_seconds: Math.round(this.t.identity * 1000) / 1000,
      check_seconds: Math.round(this.t.check * 1000) / 1000,
      record_seconds: Math.round(this.t.record * 1000) / 1000,
      config: this.configDigest,
      runtime: this.runtimeDigest,
      runtime_parts: this.rid ? this.rid.parts : null,
      packages: this.rid ? this.rid.lists.packages : null,
      startup: this.startupDigest(),
      disabled: this.disabled,
      uncacheable_projects: Object.fromEntries(this.uncacheableProjects),
      verified: verified.length,
      // tests only (a reused file is also verified as a file entry over the same tests: review R-032 F8)
      verified_tests: verified.filter((v) => v.nodeid.includes('::')).length,
      verify_mismatches_tests: verified.filter((v) => !v.same && v.nodeid.includes('::')).length,
      verify_mismatches: verified.filter((v) => !v.same),
      receipts: this.receiptsPath,
      cache_dir: this.dir,
      error: this.error || null,
      remote: this.remote ? this.remote.report() : null,
      notes: [...CAPTURE.notes],
    };
  }

  lines(s) {
    const out = [];
    if (s.disabled) {
      out.push(`detjs cache: off for this session (${s.disabled})`);
      return out;
    }
    const verb = s.verify_mode ? 'would reuse (verify mode: run anyway)' : 'reused with proof';
    out.push(`detjs cache: ${verb} ${s.reused_tests} tests in ${s.reused_files} files (${s.reused_recorded_seconds} s recorded); `
      + `ran ${s.missed_files} files; recorded ${s.recorded} tests; check ${s.check_seconds} s, identity ${s.identity_seconds} s, record ${s.record_seconds} s`);
    if (Object.keys(s.not_cached).length) out.push(`detjs cache: not cached: ${Object.entries(s.not_cached).map(([k, v]) => `${k} ${v}`).join(', ')}`);
    if (s.verify_mode) out.push(`detjs cache: verified ${s.verified} results, ${s.verify_mismatches.length} differ`);
    for (const m of s.verify_mismatches.slice(0, 20)) out.push(`detjs cache: VERIFY MISMATCH ${m.nodeid}: cached ${m.cached}, fresh ${m.fresh}`);
    out.push(`detjs cache: receipts ${path.relative(process.cwd(), s.receipts) || s.receipts}`);
    if (s.remote) {
      const r = s.remote;
      out.push(`detjs cache: shared cache ${r.service} [${r.namespace}]: candidates for ${r.pull_files_with_candidates || 0} files, `
        + `${r.pull_proven || 0} proven from the service; pushed ${r.push_entry_docs_new || 0} entries; ${r.requests} requests`);
      if (r.error) out.push(`detjs cache: shared cache error: ${r.error} (the local mirror ${r.local_dir} was used)`);
    }
    return out;
  }
}

module.exports = { ProofSession, stable, configFiles, ownFile, projectPart, UNCACHEABLE };
