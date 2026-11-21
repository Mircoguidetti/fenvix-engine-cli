'use strict';
// Cache with proof for Level 2 browser runs (`detjs playwright --det --det-cache=DIR`).
//
// Unit of reuse: one selection of one project (the Playwright arguments that choose the tests: files, --grep,
// --project, ...). End-to-end tests of one app share its server and database, so a test's result depends on every
// test that ran before it in the same run; a test file is never reused alone. The selection is reused when every
// input of its recorded run is unchanged:
//
//   * the key: detjs, Playwright and Node versions, platform, the selection arguments, seed, epoch, the Level 2
//     controls, the start state (--det-state or --det-cache-state: its files digest and the snapshot's identity), and
//     the environment (every variable except the volatile ones listed in VOLATILE_ENV);
//   * the inputs recorded while it ran (src/pw/inputs.js, in every Node process of the run: the runner, its workers,
//     the app servers and their Node children): the content of every file read and module loaded, the listing of every
//     directory listed, the browser executable.
//
// A recorded run is stored only when it can be proven complete (`cacheable`): every TCP connection a process opened
// went to a port an app server of the run listened on, or to a database the start state covers; no child process
// other than Node and the browser ran (their reads are not seen). An app server outside the run that is not under
// `detjs serve --det-cache=DIR` is caught by the first rule (its port was connected to but not listened on).
// The reused run reports the recorded outcomes and fingerprints (its trace is the recorded one), with a receipt that
// lists what was compared. Results of failing tests are reused too: the same inputs give the same run.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const native = require('../native');

const FORMAT = 1;
const VOLATILE_ENV = /^(?:DETJS.*|PLAYWRIGHT_JSON_OUTPUT_NAME|PLAYWRIGHT_HTML_.*|GITHUB_.*|RUNNER_.*|ACTIONS_.*|INVOCATION_ID|JOURNAL_STREAM|SHLVL|OLDPWD|PWD|_|TERM|TERM_.*|COLORTERM|SSH_.*|TMUX.*|STY|WINDOWID|DISPLAY|XDG_SESSION_.*|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS|LS_COLORS|HOSTNAME|LINES|COLUMNS|NODE_OPTIONS|FORCE_COLOR|NO_COLOR|L2_.*|ENGINE_SHA|PYTHONUNBUFFERED|CLAUDE.*)$/;

function sha(s) { return crypto.createHash('sha256').update(s).digest('hex'); }

function fileDigest(p) {
  try {
    const st = fs.statSync(p);
    if (st.isDirectory()) return 'dir';
    return native.fileDigest ? native.fileDigest(p) || 'unreadable' : sha(fs.readFileSync(p)).slice(0, 32);
  } catch { return 'missing'; }
}

function listingDigest(p) {
  try { return sha(fs.readdirSync(p).sort().join('\0')).slice(0, 32); } catch { return 'missing'; }
}

function envKey(env) {
  const out = {};
  for (const k of Object.keys(env).sort()) if (!VOLATILE_ENV.test(k)) out[k] = env[k];
  return out;
}

/** The state the run starts from: { digest, saved, ports } of a detjs state spec, or null. */
function stateKey(specFile) {
  if (!specFile) return null;
  const snap = require('./snapshot');
  const spec = snap.load(specFile);
  let saved = null;
  try { saved = JSON.parse(fs.readFileSync(path.join(spec.dir, 'meta.json'), 'utf8')).saved; } catch { /* none yet */ }
  const ports = spec.postgres.map((u) => { const x = new URL(u); return `${x.hostname}:${x.port || '5432'}`; });
  return { digest: snap.digest(spec), saved, ports };
}

class PwCache {
  constructor(dir, root) {
    this.dir = path.resolve(root, dir);
    this.root = root;
    fs.mkdirSync(path.join(this.dir, 'pw'), { recursive: true });
  }

  key(k) {
    const id = sha(JSON.stringify({ format: FORMAT, selection: k.selection, root: k.root })).slice(0, 32);
    return { id, full: k };
  }

  entryFile(id) { return path.join(this.dir, 'pw', `${id}.json`); }

  /** { hit: entry, receipt } or { miss: why } */
  check(key) {
    let e;
    try { e = JSON.parse(fs.readFileSync(this.entryFile(key.id), 'utf8')); } catch { return { miss: 'no recorded run of this selection' }; }
    const a = e.key;
    const b = key.full;
    for (const f of Object.keys(b)) {
      if (JSON.stringify(a[f]) !== JSON.stringify(b[f])) {
        if (f === 'env') {
          const keys = new Set([...Object.keys(a.env || {}), ...Object.keys(b.env || {})]);
          const diff = [...keys].filter((x) => (a.env || {})[x] !== (b.env || {})[x]).sort();
          return { miss: `environment changed: ${diff.slice(0, 5).join(', ')}${diff.length > 5 ? ` (+${diff.length - 5})` : ''}` };
        }
        return { miss: `${f} changed` };
      }
    }
    let n = 0;
    for (const [p, d] of Object.entries(e.inputs.files)) {
      n++;
      const now = fileDigest(p);
      if (now !== d) return { miss: `input changed: ${path.relative(this.root, p) || p} (${d === 'missing' ? 'was missing' : now === 'missing' ? 'now missing' : 'content'})` };
    }
    for (const [p, d] of Object.entries(e.inputs.dirs)) {
      n++;
      if (listingDigest(p) !== d) return { miss: `directory listing changed: ${path.relative(this.root, p) || p}` };
    }
    const receipt = {
      kind: 'pw-selection', entry: key.id, recorded_at: e.recorded_at, recorded_run: e.run,
      compared: { key_fields: Object.keys(b).length, files: Object.keys(e.inputs.files).length, dirs: Object.keys(e.inputs.dirs).length, total: n },
      tests: Object.keys(e.outcomes).length,
    };
    return { hit: e, receipt };
  }

  /** Read the inputs the processes of a run recorded (inputs.js); decide whether the run is complete. */
  collect(inputsDirs, ctx) {
    const files = new Set();
    const dirs = new Set();
    const conns = new Set();
    const listens = new Set();
    const children = new Set();
    const roles = {};
    for (const d of inputsDirs) {
      let names = [];
      try { names = fs.readdirSync(d); } catch { continue; }
      for (const n of names) {
        const role = n.split('-')[0];
        roles[role] = (roles[role] || 0) + 1;
        let text = '';
        try { text = fs.readFileSync(path.join(d, n), 'utf8'); } catch { continue; }
        for (const line of text.split('\n')) {
          if (!line) continue;
          let r;
          try { r = JSON.parse(line); } catch { continue; }
          if (r[0] === 'f') files.add(r[1]);
          else if (r[0] === 'd') dirs.add(r[1]);
          else if (r[0] === 'c') conns.add(`${r[1]}:${r[2]}`);
          else if (r[0] === 'l') listens.add(r[1]);
          else if (r[0] === 'x') children.add(r[1]);
        }
      }
    }
    const why = [];
    const local = new Set(['localhost', '127.0.0.1', '::1', '0.0.0.0', '[::1]']);
    const covered = new Set((ctx.statePorts || []).map((x) => x.replace(/^localhost:/, '127.0.0.1:')));
    for (const c of conns) {
      const i = c.lastIndexOf(':');
      const host = c.slice(0, i);
      const port = c.slice(i + 1);
      const norm = `${local.has(host) ? '127.0.0.1' : host}:${port}`;
      if (local.has(host) && listens.has(port)) continue;
      if (covered.has(norm)) continue;
      why.push(`connection to ${c} (not an app server of the run, not covered by the start state)`);
    }
    for (const x of children) {
      if (ctx.browser && path.resolve(x) === path.resolve(ctx.browser)) continue;
      if (/(?:^|[\\/])(chrome|chrome-headless-shell|chromium|headless_shell)$/.test(x) && /ms-playwright|pw-browsers|chromium/.test(x)) { files.add(path.resolve(x)); continue; }
      why.push(`child process ${x} (not Node: its reads are not recorded)`);
    }
    if (ctx.browser) files.add(path.resolve(ctx.browser));
    return { files, dirs, why, roles, conns: [...conns].sort(), listens: [...listens].sort() };
  }

  record(key, inputs, result) {
    const f = {};
    for (const p of [...inputs.files].sort()) f[p] = fileDigest(p);
    const d = {};
    for (const p of [...inputs.dirs].sort()) d[p] = listingDigest(p);
    const traceCopy = path.join(this.dir, 'pw', `${key.id}.trace.jsonl`);
    try { fs.copyFileSync(result.trace, traceCopy); } catch { /* no trace */ }
    const e = {
      format: FORMAT, key: key.full, inputs: { files: f, dirs: d }, outcomes: result.outcomes, fingerprints: result.fingerprints,
      exit_code: result.code, recorded_at: new Date().toISOString(), run: result.run || null, trace: path.basename(traceCopy),
      roles: inputs.roles, connections: inputs.conns, listens: inputs.listens,
    };
    const tmp = `${this.entryFile(key.id)}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(e));
    fs.renameSync(tmp, this.entryFile(key.id));
    return e;
  }

  traceOf(entry) { return path.join(this.dir, 'pw', entry.trace); }
}

/** Outcomes and fingerprints of a Level 2 trace (reporter.js wrote it). */
function traceResults(trace) {
  const outcomes = {};
  const fingerprints = {};
  let text = '';
  try { text = fs.readFileSync(trace, 'utf8'); } catch { return { outcomes, fingerprints }; }
  for (const line of text.split('\n')) {
    if (!line.startsWith('{"type":"test"')) continue;
    try { const t = JSON.parse(line); outcomes[t.nodeid] = t.outcome; fingerprints[t.nodeid] = t.fingerprint; } catch { /* truncated */ }
  }
  return { outcomes, fingerprints };
}

module.exports = { PwCache, envKey, stateKey, traceResults, VOLATILE_ENV, fileDigest };
