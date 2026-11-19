'use strict';
// Shared cache client for detjs: `--det-cache=https://host[:port]/<namespace>` (the service is
// python/detpy/cache_service.py; the protocol, documents, addresses and lookup keys are those of
// python/detpy/remote_cache.py, docs/SHARED-CACHE.md).
//
// The engine keeps working on a local cache directory (the local mirror, also the fallback when the service
// cannot be reached). Pull runs at the reuse decision: for every test file it looks up the file's entry (its
// manifest: the list of its tests and the inputs of its collection) and then the entries of the tests it lists,
// under lookup keys (test id, configuration digest, runtime digest, with and without the clock epoch); a candidate
// goes into the local store only when the local entry does not already prove reuse, and is then checked exactly
// like a local entry: the service supplies candidates, never decisions. Push runs at the end: every local entry
// not yet on the service, its file and set documents, the key log, then the session's receipts linked to the run.
//
// The token comes from an inherited pipe (FENVIX_CACHE_TOKEN_FD), a hand-off file (FENVIX_CACHE_TOKEN_FILE,
// deleted once read) or FENVIX_CACHE_TOKEN; it is read in the main process before any test runs and the variables
// are removed from the environment, so worker processes and threads never inherit it. Plain http:// is refused to
// hosts other than loopback unless FENVIX_CACHE_ALLOW_HTTP=1. A cache problem never fails a test run.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');
const crypto = require('node:crypto');
const http = require('node:http');
const https = require('node:https');
const native = require('../native');

const realSetTimeout = setTimeout; // bound before Level 0 replaces timers
const DOC_VERSION = 1;
const ENTRY_FIELDS = ['outcome', 'report', 'fingerprint', 'duration', 'run', 'config', 'runtime', 'epoch', 'env', 'data'];
const JOURNAL = 'remote-pushed.json';
const CLIENT_ENV = ['FENVIX_CACHE_TOKEN', 'FENVIX_CACHE_TOKEN_FD', 'FENVIX_CACHE_TOKEN_FILE', 'FENVIX_CACHE_LOCAL',
  'FENVIX_CACHE_REPORT', 'FENVIX_CACHE_ALLOW_HTTP'];

// -- canonical JSON (byte-identical to Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True))
function pyFloat(n) {
  if (Number.isInteger(n) && Math.abs(n) < 1e21) return String(n);
  const a = Math.abs(n);
  if (a >= 1e-4 && a < 1e16) {
    const s = String(n);
    return s.includes('.') || s.includes('e') ? s : `${s}.0`;
  }
  const [m, e] = n.toExponential().split('e');
  const ex = Number(e);
  return `${m}e${ex < 0 ? '-' : '+'}${String(Math.abs(ex)).padStart(2, '0')}`;
}

function pyString(s) {
  return JSON.stringify(s).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

function canonical(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return pyFloat(v);
  if (typeof v === 'string') return pyString(v);
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  const keys = Object.keys(v).filter((k) => v[k] !== undefined).sort();
  return `{${keys.map((k) => `${pyString(k)}:${canonical(v[k])}`).join(',')}}`;
}

function docId(doc) {
  return crypto.createHash('sha256').update(canonical(doc)).digest('hex');
}

/** Project of a node id (`file@@project` or `file@@project::test`; '' without a project). */
function projectOf(nodeid) {
  const head = nodeid.split('::', 1)[0];
  const i = head.indexOf('@@');
  return i < 0 ? '' : head.slice(i + 2);
}

function lookupKey(nodeid, config, runtime, epoch) {
  const parts = ['fenvix-lookup-1', nodeid, config, runtime, epoch === null || epoch === undefined ? '' : String(epoch)];
  const bufs = [];
  for (const p of parts) {
    const raw = Buffer.from(p, 'utf8');
    const len = Buffer.alloc(8);
    len.writeBigUInt64LE(BigInt(raw.length));
    bufs.push(len, raw);
  }
  return native.digest(Buffer.concat(bufs));
}

function ownFile(nodeid) {
  return String(nodeid).split('::', 1)[0].split('@@', 1)[0];
}

function isLoopback(host) {
  const h = String(host).toLowerCase().replace(/^\[|\]$/g, '');
  return h === 'localhost' || h === 'localhost.localdomain' || h === 'ip6-localhost' || h === '::1' || /^127\./.test(h);
}

function localDirFor(url) {
  if (process.env.FENVIX_CACHE_LOCAL) return path.resolve(process.env.FENVIX_CACHE_LOCAL);
  const base = process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache');
  return path.join(base, 'fenvix', 'remote', crypto.createHash('sha256').update(url).digest('hex').slice(0, 16));
}

function takeToken() {
  const fd = process.env.FENVIX_CACHE_TOKEN_FD;
  if (fd) {
    try {
      const n = Number(fd);
      const t = fs.readFileSync(n, 'utf8').trim();
      try { fs.closeSync(n); } catch { /* closed */ }
      return t || null;
    } catch { return null; }
  }
  const f = process.env.FENVIX_CACHE_TOKEN_FILE;
  if (f) {
    try {
      const t = fs.readFileSync(f, 'utf8').trim();
      fs.unlinkSync(f);
      return t || null;
    } catch { return null; }
  }
  const t = process.env.FENVIX_CACHE_TOKEN;
  return t ? t.trim() : null;
}

class ServiceError extends Error {}

class Http {
  constructor(base, token, timeout = 60000, retries = 2) {
    this.base = base.replace(/\/+$/, '');
    this.token = token;
    this.timeout = timeout;
    this.retries = retries;
    this.sent = 0;
    this.received = 0;
    this.requests = 0;
  }

  once(method, p, body) {
    return new Promise((resolve, reject) => {
      const u = new URL(this.base + p);
      const headers = { 'Accept-Encoding': 'gzip', 'User-Agent': 'fenvix-engine' };
      if (this.token) headers.Authorization = `Bearer ${this.token}`;
      let data = null;
      if (body !== undefined) {
        data = Buffer.from(JSON.stringify(body));
        headers['Content-Type'] = 'application/json';
        if (data.length > 4096) {
          data = zlib.gzipSync(data, { level: 5 });
          headers['Content-Encoding'] = 'gzip';
        }
        headers['Content-Length'] = String(data.length);
      }
      const mod = u.protocol === 'https:' ? https : http;
      // Level 0 closes the network even between tests: the client's own requests run with it suspended
      let restore = () => {};
      try { restore = require('../network').openNetwork(); } catch { /* not installed */ }
      let req;
      try {
        req = mod.request(u, { method, headers, timeout: this.timeout, agent: false }, (res) => {
          const chunks = [];
          res.on('data', (c) => chunks.push(c));
          res.on('end', () => {
            let raw = Buffer.concat(chunks);
            this.requests++;
            this.sent += data ? data.length : 0;
            this.received += raw.length;
            try {
              if (String(res.headers['content-encoding'] || '').toLowerCase() === 'gzip') raw = zlib.gunzipSync(raw);
              const j = raw.length ? JSON.parse(raw.toString('utf8')) : {};
              if (res.statusCode >= 400) {
                const e = new ServiceError(`HTTP ${res.statusCode} on ${p}: ${j.error || ''}`);
                e.status = res.statusCode;
                reject(e);
              } else resolve(j);
            } catch (e) { reject(new ServiceError(`bad response on ${p}: ${e.message}`)); }
          });
          res.on('error', (e) => reject(new ServiceError(`${e.code || e.name} on ${p}: ${e.message}`)));
        });
      } finally {
        restore();
      }
      req.on('timeout', () => req.destroy(new Error('timeout')));
      req.on('error', (e) => reject(new ServiceError(`${e.code || e.name} on ${p}: ${e.message}`)));
      if (data) req.write(data);
      req.end();
    });
  }

  async call(method, p, body) {
    let last;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      try {
        return await this.once(method, p, body);
      } catch (e) {
        if (e.status && e.status < 500) throw e;
        last = e;
      }
      if (attempt < this.retries) await new Promise((r) => realSetTimeout(r, 500 * 2 ** attempt));
    }
    throw last;
  }
}

/** Content-addressed documents of a store (the JSON the Rust core writes), as python/detpy/remote_cache.py. */
class Docs {
  constructor(store) {
    this.files = store.files || [];
    this.sets = store.sets || [];
    this.fileId = new Map();
    this.setId = new Map();
    this.docs = new Map();
  }

  file(fi) {
    let id = this.fileId.get(fi);
    if (id === undefined) {
      const f = this.files[fi];
      const d = { kind: 'file', v: DOC_VERSION, path: f.path, content: f.content, skeleton: f.skeleton, hooks: f.hooks, units: f.units || [], imports: f.imports || [] };
      id = docId(d);
      this.fileId.set(fi, id);
      this.docs.set(id, d);
    }
    return id;
  }

  setOf(fids) {
    const key = [...new Set(fids)].sort();
    const k = key.join(',');
    let id = this.setId.get(k);
    if (id === undefined) {
      const d = { kind: 'set', v: DOC_VERSION, files: key };
      id = docId(d);
      this.setId.set(k, id);
      this.docs.set(id, d);
    }
    return id;
  }

  entry(nodeid, e) {
    const n = this.files.length;
    const members = (sid) => {
      const s = Number.isInteger(sid) && sid >= 0 && sid < this.sets.length ? this.sets[sid] : [];
      return s.filter((fi) => fi >= 0 && fi < n).map((fi) => this.file(fi));
    };
    const u = e.units || [];
    const pairs = [];
    for (let i = 0; i + 1 < u.length; i += 2) if (u[i] >= 0 && u[i] < n) pairs.push([this.file(u[i]), u[i + 1]]);
    const ufiles = [...new Set(pairs.map(([f]) => f))].sort();
    const pos = new Map(ufiles.map((f, k) => [f, k]));
    const entry = {};
    for (const k of ENTRY_FIELDS) entry[k] = e[k] === undefined ? null : e[k];
    if (e.startup) entry.startup = e.startup;
    return {
      kind: 'entry', v: DOC_VERSION, nodeid, proof_key: e.key, entry,
      content: this.setOf(members(e.content)), skeleton: this.setOf(members(e.skeleton)), hooks: this.setOf(members(e.hooks)),
      unit_files: this.setOf(ufiles),
      units: pairs.map(([f, k]) => [pos.get(f), k]).sort((a, b) => a[0] - b[0] || a[1] - b[1]),
    };
  }
}

class RemoteCache {
  constructor(url, session) {
    this.url = url;
    const u = new URL(url);
    this.base = `${u.protocol}//${u.host}`;
    this.ns = decodeURIComponent(u.pathname.replace(/^\/+|\/+$/g, '')) || 'default';
    this.localDir = localDirFor(url);
    this.session = session;
    this.error = null;
    this.stats = { service: this.base, namespace: this.ns, local_dir: this.localDir };
    this.disabled = null;
    if (u.protocol === 'http:' && !isLoopback(u.hostname) && process.env.FENVIX_CACHE_ALLOW_HTTP !== '1') {
      this.disabled = `refusing plain http:// to ${u.hostname} (use https://, or FENVIX_CACHE_ALLOW_HTTP=1)`;
      this.fail('setup', new ServiceError(this.disabled));
    }
    this.http = new Http(this.base, takeToken());
    for (const k of CLIENT_ENV) {
      if (k === 'FENVIX_CACHE_LOCAL') continue;
      delete process.env[k];
    }
    this.reportPath = process.env.FENVIX_CACHE_REPORT || null;
    this.nsq = encodeURIComponent(this.ns);
    this.pulledDocs = new Set();
  }

  p(what) {
    return `/v1/ns/${this.nsq}/${what}`;
  }

  fail(phase, e) {
    (this.stats.errors = this.stats.errors || []).push(`${phase}: ${e && e.message ? e.message : e}`);
    this.error = this.stats.errors.join('; ');
  }

  async get(ids) {
    const out = {};
    for (let i = 0; i < ids.length; i += 2000) {
      const got = (await this.http.call('POST', '/v1/blobs/get', { ids: ids.slice(i, i + 2000) })).docs || {};
      for (const [k, d] of Object.entries(got)) {
        if (docId(d) === k) out[k] = d;
        else this.stats.pull_bad_address = (this.stats.pull_bad_address || 0) + 1;
      }
    }
    return out;
  }

  async lookup(nodeids) {
    const s = this.session;
    const keys = new Map();
    for (const nid of nodeids) {
      const config = s.configFor ? s.configFor(projectOf(nid)) : s.configDigest;
      keys.set(lookupKey(nid, config, s.runtimeDigest, null), nid);
      keys.set(lookupKey(nid, config, s.runtimeDigest, s.epochMs), nid);
    }
    const klist = [...keys.keys()].sort();
    const found = {};
    for (let i = 0; i < klist.length; i += 5000) {
      Object.assign(found, (await this.http.call('POST', this.p('lookup'), { keys: klist.slice(i, i + 5000), limit: 3 })).found || {});
    }
    const perTest = new Map();
    for (const [k, ids] of Object.entries(found)) {
      const nid = keys.get(k);
      if (!perTest.has(nid)) perTest.set(nid, []);
      perTest.get(nid).push(...ids);
    }
    const docs = await this.get([...new Set([...perTest.values()].flat())].sort());
    const setIds = new Set();
    for (const d of Object.values(docs)) for (const k of ['content', 'skeleton', 'hooks', 'unit_files']) if (d[k]) setIds.add(d[k]);
    const sets = await this.get([...setIds].sort());
    Object.assign(docs, sets);
    const fileIds = new Set();
    for (const sd of Object.values(sets)) for (const f of sd.files || []) fileIds.add(f);
    Object.assign(docs, await this.get([...fileIds].sort()));
    return { perTest, docs };
  }

  static namesOwnFile(doc, docs) {
    const own = ownFile(doc.nodeid || '');
    if (((doc.entry || {}).data || []).some(([p]) => p === own)) return true;
    for (const k of ['content', 'skeleton', 'hooks', 'unit_files']) {
      for (const fid of (docs[doc[k]] || {}).files || []) if ((docs[fid] || {}).path === own) return true;
    }
    return false;
  }

  inject(doc, docs, memo) {
    // detjs entries key code by whole content: a candidate with function units or skeletons is not representable
    for (const k of ['skeleton', 'hooks', 'unit_files']) if (((docs[doc[k]] || {}).files || []).length) return false;
    const sd = docs[doc.content];
    if (!sd) return false;
    const content = [];
    for (const fid of sd.files) {
      let ix = memo.get(fid);
      if (ix === undefined) {
        const f = docs[fid];
        if (!f) return false;
        ix = this.session.store.addFileFacts(JSON.stringify({ path: f.path, content: f.content, skeleton: f.skeleton, hooks: f.hooks, units: f.units || [], imports: f.imports || [] }));
        memo.set(fid, ix);
      }
      content.push(ix);
    }
    const e = doc.entry;
    this.session.store.record(doc.nodeid, JSON.stringify({
      outcome: e.outcome, report: e.report, fingerprint: e.fingerprint || '', duration: Number(e.duration || 0), run: e.run || '',
      config: e.config, runtime: e.runtime, epoch: e.epoch ?? null, env: e.env || [], data: e.data || [], content, startup: e.startup || '',
    }));
    return true;
  }

  /** Bring in candidates for `nodeids` whose local entry does not prove reuse; returns the proven ids. */
  /** The proof check of `nid` against the configuration of its own project. */
  checkOwn(nid) {
    const s = this.session;
    if (s.configFor) s.store.setConfig(s.configFor(projectOf(nid)));
    return s.store.check(nid);
  }

  async pullIds(nodeids) {
    const st = this.stats;
    const { perTest, docs } = await this.lookup(nodeids);
    st.pull_candidates = (st.pull_candidates || 0) + [...perTest.values()].reduce((a, v) => a + v.length, 0);
    let pending = new Map();
    const proven = new Set();
    for (const [nid, ids] of perTest) {
      if (this.checkOwn(nid).ok) { st.pull_local_already = (st.pull_local_already || 0) + 1; proven.add(nid); continue; }
      const cands = [];
      for (const d of ids) {
        const doc = docs[d];
        if (!doc || cands.includes(d) || doc.kind !== 'entry' || doc.nodeid !== nid) continue;
        if (RemoteCache.namesOwnFile(doc, docs)) cands.push(d);
        else st.pull_rejected_no_own_file = (st.pull_rejected_no_own_file || 0) + 1;
      }
      if (cands.length) pending.set(nid, cands);
    }
    const memo = new Map();
    while (pending.size) {
      for (const [, cands] of pending) {
        if (this.inject(docs[cands[0]], docs, memo)) {
          st.pull_injected = (st.pull_injected || 0) + 1;
          this.pulledDocs.add(cands[0]);
        }
      }
      const next = new Map();
      for (const [nid, cands] of pending) {
        if (this.checkOwn(nid).ok) { st.pull_proven = (st.pull_proven || 0) + 1; proven.add(nid); } else if (cands.length > 1) next.set(nid, cands.slice(1));
      }
      pending = next;
    }
    return proven;
  }

  async pull(files) {
    if (this.disabled) return;
    const t0 = Date.now();
    const s = this.session;
    try {
      const mids = files.map((f) => s.idOf(f.fileId, f.project || ''));
      const provenFiles = await this.pullIds(mids);
      this.stats.pull_files_with_candidates = provenFiles.size;
      const tests = [];
      for (const f of files) {
        const mid = s.idOf(f.fileId, f.project || '');
        if (!provenFiles.has(mid)) continue;
        const e = JSON.parse(s.store.entry(mid) || '{}');
        for (const t of (e.report && e.report.tests) || []) tests.push(s.testKey(t, f.project || ''));
      }
      if (tests.length) await this.pullIds(tests);
    } catch (e) {
      this.fail('pull', e);
    }
    this.stats.pull_seconds = (Date.now() - t0) / 1000;
  }

  journalPath() { return path.join(this.localDir, JOURNAL); }

  journal() {
    try {
      const d = JSON.parse(fs.readFileSync(this.journalPath(), 'utf8'));
      if (d.service === this.base && d.namespace === this.ns) return new Set(d.docs || []);
    } catch { /* none */ }
    return new Set();
  }

  saveJournal(docs) {
    const p = this.journalPath();
    const tmp = `${p}.tmp${process.pid}`;
    try {
      fs.writeFileSync(tmp, JSON.stringify({ service: this.base, namespace: this.ns, docs: [...docs].sort() }));
      fs.renameSync(tmp, p);
    } catch { /* report only */ }
  }

  async push() {
    if (this.disabled) return;
    const t0 = Date.now();
    const st = this.stats;
    let store;
    try { store = JSON.parse(fs.readFileSync(path.join(this.localDir, 'proof-cache.json'), 'utf8')); } catch (e) {
      this.fail('push', new ServiceError(`local store unreadable: ${e.message}`));
      return;
    }
    const journal = this.journal();
    for (const d of this.pulledDocs) journal.add(d);
    const ds = new Docs(store);
    const entryDocs = new Map();
    const rows = [];
    for (const [nid, e] of Object.entries(store.tests || {})) {
      const doc = ds.entry(nid, e);
      const did = docId(doc);
      if (journal.has(did)) continue;
      entryDocs.set(did, doc);
      rows.push({ key: lookupKey(nid, e.config || '', e.runtime || '', e.epoch), doc: did, run: e.run });
    }
    const need = new Map();
    for (const d of entryDocs.values()) {
      for (const k of ['content', 'skeleton', 'hooks', 'unit_files']) {
        const sd = ds.docs.get(d[k]);
        need.set(d[k], sd);
        for (const f of sd.files) need.set(f, ds.docs.get(f));
      }
    }
    st.push_entries = entryDocs.size;
    try {
      for (const [docs, label] of [[need, null], [entryDocs, 'push_entry_docs_new']]) {
        const ids = [...docs.keys()].sort();
        let missing = [];
        for (let i = 0; i < ids.length; i += 20000) missing = missing.concat((await this.http.call('POST', '/v1/blobs/missing', { ids: ids.slice(i, i + 20000) })).missing || []);
        if (label) st[label] = missing.length;
        else {
          st.push_file_docs_new = missing.filter((m) => docs.get(m).kind === 'file').length;
          st.push_set_docs_new = missing.filter((m) => docs.get(m).kind === 'set').length;
        }
        let batch = {};
        let size = 0;
        let n = 0;
        for (const id of missing) {
          batch[id] = docs.get(id);
          size += canonical(batch[id]).length;
          n++;
          if (size > 16 * 1024 * 1024 || n >= 5000) {
            await this.http.call('POST', '/v1/blobs/put', { docs: batch });
            batch = {}; size = 0; n = 0;
          }
        }
        if (n) await this.http.call('POST', '/v1/blobs/put', { docs: batch });
      }
      for (let i = 0; i < rows.length; i += 5000) await this.http.call('POST', this.p('keys'), { put: rows.slice(i, i + 5000) });
      for (const d of entryDocs.keys()) journal.add(d);
      this.saveJournal(journal);
      const rec = this.receiptsDoc();
      if (rec) {
        const rid = docId(rec);
        await this.http.call('POST', '/v1/blobs/put', { docs: { [rid]: rec } });
        const s = this.session.summary();
        await this.http.call('POST', this.p('runs'), { run: this.session.runId, receipts: rid,
          summary: { reused: s.reused_tests, reused_files: s.reused_files, ran: s.missed_files, runtime: s.runtime, config: s.config, miss_reasons: s.miss_reasons } });
        st.receipts_doc = rid;
      }
    } catch (e) {
      this.fail('push', e);
    }
    st.push_seconds = (Date.now() - t0) / 1000;
    if (this.reportPath) {
      try { fs.writeFileSync(this.reportPath, JSON.stringify(this.report(), null, 1)); } catch { /* report only */ }
    }
  }

  receiptsDoc() {
    try {
      const rows = fs.readFileSync(this.session.receiptsPath, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
      return { kind: 'receipts', v: DOC_VERSION, run: this.session.runId, rows };
    } catch { return null; }
  }

  report() {
    return { ...this.stats, requests: this.http.requests, bytes_sent: this.http.sent, bytes_received: this.http.received, error: this.error };
  }
}

/**
 * Push from a child process, synchronously (the session is exiting: Jest --forceExit). The token goes over stdin.
 */
function pushSync(client) {
  const { spawnSync } = require('node:child_process');
  const s = client.session;
  const job = { url: client.url, localDir: client.localDir, token: client.http.token, receiptsPath: s.receiptsPath, runId: s.runId,
    summary: s.summary(), pulledDocs: [...client.pulledDocs] };
  const env = { ...process.env };
  for (const k of Object.keys(env)) if (/^(FENVIX_CACHE_|DETJS)/.test(k)) delete env[k];
  const r = spawnSync(process.execPath, [__filename, '--push'], { input: JSON.stringify(job), encoding: 'utf8', env, timeout: 600000 });
  try { Object.assign(client.stats, JSON.parse(r.stdout).stats || {}); } catch { client.fail('push', new ServiceError(`push process: ${(r.stderr || '').slice(-500)}`)); }
}

module.exports = { RemoteCache, canonical, docId, lookupKey, pyFloat, Docs, ownFile, pushSync };

if (require.main === module && process.argv[2] === '--push') {
  const job = JSON.parse(fs.readFileSync(0, 'utf8'));
  process.env.FENVIX_CACHE_LOCAL = job.localDir;
  const session = { receiptsPath: job.receiptsPath, runId: job.runId, summary: () => job.summary };
  const c = new RemoteCache(job.url, session);
  c.http.token = job.token;
  for (const d of job.pulledDocs || []) c.pulledDocs.add(d);
  c.push().then(() => { process.stdout.write(JSON.stringify({ stats: c.report() })); }, (e) => { process.stdout.write(JSON.stringify({ stats: { error: String(e) } })); });
}
