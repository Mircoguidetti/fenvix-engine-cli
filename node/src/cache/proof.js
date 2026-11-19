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
const { runtimeIdentity } = require('./runtime-id');

const VERSION = require('../../package.json').version;
const CONFIG_FILES = /^(tsconfig.*\.json|jsconfig.*\.json|babel\.config\.[cm]?[jt]s(on)?|\.babelrc(\.[cm]?[jt]s(on)?)?|\.swcrc|postcss\.config\.[cm]?[jt]s|\.postcssrc(\.[a-z]+)?|\.browserslistrc|browserslist|vite\.config\.[cm]?[jt]s|vitest\.config\.[cm]?[jt]s|vitest\.(workspace|projects)\.[cm]?[jt]s(on)?|jest\.config\.[cm]?[jt]s(on)?|jest\.preset\.[cm]?js|\.env(\..+)?|\.swcrc|\.nvmrc|\.node-version)$/;
const SKIP_DIRS = new Set(['node_modules', '.git', '.detjs', '.hg', '.svn', 'coverage', '.nx', '.turbo']);
const UNCACHEABLE = {
  spawn: 'subprocess',
  worker: 'worker thread',
  connect: 'network connection',
  udp: 'UDP socket',
  'net-record': 'network recording (--det-record)',
  proc: 'reads /proc, /sys or /dev',
  rw: 'reads a file another test file or the start-up code wrote',
  entropy: 'os entropy (not controlled; use --det-urandom)',
  'env-unobserved': 'environment reads not observable in this process',
  machine: 'reads a machine fact that changes between calls',
};

function digest(x) {
  return native.digest(typeof x === 'string' ? x : JSON.stringify(x));
}

// detjs' own per-session values inside a runner configuration (runner shim path, sequencer, the run's seed)
const OWN_STRING = /[\\/]node_modules[\\/]\.detjs[\\/]runner-\d+\.mjs$/;
// output and selection settings never change a result; the resolved configuration repeats them at several depths
const ANY_VOLATILE = new Set(['webSocketToken', 'tokenCreated', 'outputFile', 'reporters', 'reporter', 'shard', 'changed',
  'passWithNoTests', 'filters', 'cliExclude', 'related']);
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

function configFiles(root, { nestedViteConfigs = true } = {}, limit = 200000) {
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
      } else if (CONFIG_FILES.test(e.name) || (r === 'package.json')) {
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
    });
  }

  /** The configuration digest a file of `project` is keyed by. */
  configFor(project) {
    return (this.projectConfig && this.projectConfig.get(project || '')) || this.configDigest;
  }

  identity() {
    if (this.runtimeDigest) return;
    const t0 = process.hrtime.bigint();
    this.quiet(() => {
      this.rid = runtimeIdentity(this.root, this.env0);
      this.runtimeDigest = this.rid.digest;
      this.machine = machineFacts();
      this.curEnv = { ...this.env0, ...this.machine };
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
    this.identity();
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
      try { out.push(JSON.parse(fs.readFileSync(path.join(dir, n), 'utf8'))); } catch { /* truncated: not recorded */ }
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

  recordAll(captures) {
    const store = this.store;
    const curEnv = this.curEnv;
    const envAll = native.envAllDigest(curEnv);
    const envDep = (name) => (name === '*' ? envAll : native.envValueDigest(curEnv[name] ?? null));
    // global (main process) inputs: start-up reads by anyone minus the test files themselves, plus user code's
    // reads during the run
    const global = CAPTURE.global.filter((it) => !(it[0] === 'data' && it[3] === 'infra' && this.specKeys.has(it[1])));
    // writers of this session and of earlier sessions
    const writers = new Map();
    const addW = (k, l) => { let s = writers.get(k); if (!s) writers.set(k, (s = new Set())); s.add(l); };
    for (const it of CAPTURE.global) if (it[0] === 'write') addW(it[1], '');
    for (const c of captures) for (const it of c.items) if (it[0] === 'write') addW(it[1], c.label);
    let past = {};
    try { past = JSON.parse(store.written()); } catch { /* none */ }
    for (const [k, ls] of Object.entries(past)) for (const l of ls) addW(k, l);
    const sessionWritten = {};
    for (const [k, s] of writers) sessionWritten[k] = [...s];
    const startup = this.startupDigest();
    const fileIx = new Map();
    const codeIndex = (rel, d) => {
      const k = `${rel}\u0000${d}`;
      let i = fileIx.get(k);
      if (i === undefined) { i = store.addFile(rel, d); fileIx.set(k, i); }
      return i;
    };
    const observe = (items, label, base) => {
      const flags = new Map();
      const env = new Map();
      const data = new Map();
      const content = new Set();
      let clock = false;
      const take = (it) => {
        switch (it[0]) {
          case 'data': data.set(`${it[1]}\u0000${it[2]}`, [it[1], it[2]]); break;
          case 'code': content.add(codeIndex(it[1], it[2])); break;
          case 'env': env.set(it[1], envDep(it[1])); break;
          case 'clock': clock = true; break;
          case 'flag': if (!flags.has(it[1])) flags.set(it[1], it[2]); break;
          default:
        }
      };
      for (const it of global) take(it);
      for (const it of items) take(it);
      if (base) for (const it of base) take(it);
      for (const [, [k]] of data) {
        const ws = writers.get(k);
        if (ws && [...ws].some((w) => w !== label) && !flags.has('rw')) flags.set('rw', `${k} written by ${[...ws].filter((w) => w !== label).join(',') || 'start-up'}`);
      }
      if (flags.has('entropy') && this.run.cfg.urandom) flags.delete('entropy');
      return { flags, env: [...env.entries()], data: [...data.values()], content: [...content], clock };
    };
    this.ranFiles = {};
    for (const c of captures) {
      const proj = c.project || '';
      const mid = this.idOf(c.fileId, proj);
      this.ranFiles[mid] = { duration: Math.round((c.duration || 0) * 1000) / 1000, tests: c.tests.length, ok: Boolean(c.ok) };
      if (this.uncacheableProjects.has(proj)) continue;
      const notes = c.notes || [];
      const extraFlags = notes.some((n) => n.startsWith('process.env not replaceable')) ? [['flag', 'env-unobserved', 'process.env']] : [];
      const ids = [];
      for (const t of c.tests) {
        const nid = this.testKey(t.id, proj);
        ids.push(t.id);
        const o = observe(c.items.slice(0, t.upto), c.label, extraFlags);
        const why = this.uncacheable(o, t.outcome);
        this.verifyOne(nid, t.outcome);
        if (why) {
          store.remove(nid);
          this.notCached.set(nid, why);
          continue;
        }
        store.record(nid, JSON.stringify({
          outcome: t.outcome, report: { outcome: t.outcome }, fingerprint: t.fingerprint || '', duration: t.duration || 0,
          run: this.runId, config: this.configFor(proj), runtime: this.runtimeDigest, epoch: o.clock ? this.epochMs : null,
          env: o.env, data: o.data, content: o.content, startup,
        }));
        this.recorded++;
      }
      const o = observe(c.items, c.label, extraFlags);
      const outcome = c.ok ? 'passed' : 'failed';
      this.verifyOne(mid, outcome);
      const why = this.uncacheable(o, outcome);
      if (why) {
        store.remove(mid);
        this.notCached.set(mid, why);
        continue;
      }
      store.record(mid, JSON.stringify({
        outcome, report: { kind: 'file', file: c.fileId, project: proj || null, tests: ids }, fingerprint: '',
        duration: c.duration || 0, run: this.runId, config: this.configFor(proj), runtime: this.runtimeDigest,
        epoch: o.clock ? this.epochMs : null, env: o.env, data: o.data, content: o.content, startup,
      }));
    }
    store.addWritten(JSON.stringify(sessionWritten));
  }

  uncacheable(o, outcome) {
    if (!['passed', 'skipped', 'todo'].includes(outcome)) return `outcome ${outcome}`;
    for (const [f, detail] of o.flags) {
      if (UNCACHEABLE[f]) return `${UNCACHEABLE[f]}: ${detail}`;
    }
    return null;
  }

  /** Verify mode: a result that would have been reused, compared with the fresh run. */
  verifyOne(nid, outcome) {
    if (!this.verify || !this.hits.has(nid)) return;
    this.verified = this.verified || [];
    const rc = this.hits.get(nid);
    this.verified.push({ nodeid: nid, cached: rc.outcome, fresh: outcome, same: rc.outcome === outcome });
  }

  writeReceipts() {
    try {
      fs.mkdirSync(path.dirname(this.receiptsPath), { recursive: true });
      const lines = [];
      for (const [nid, r] of this.hits) lines.push(JSON.stringify({ nodeid: nid, reused: !this.verify, ...(this.verify ? { would_reuse: true } : {}), ...r }));
      for (const [nid, why] of this.misses) lines.push(JSON.stringify({ nodeid: nid, reused: false, why }));
      fs.writeFileSync(this.receiptsPath, lines.length ? `${lines.join('\n')}\n` : '');
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
