"""Shared cache client: ``pytest --det --det-cache=https://host[:port]/<namespace>``.

The engine keeps working on a local cache directory (the *local mirror*, also the fallback when the service cannot
be reached); this module connects it to the cache service (``detpy.cache_service``):

* **pull**, after collection and before the reuse decision: for every collected test it looks up its lookup keys
  (test id, configuration digest, runtime digest, with and without the clock epoch) and fetches the most recent
  entries recorded under them on any machine. A candidate is put in the local store only when the local entry
  does not already prove reuse, and it is then checked exactly like a local entry (code, data, environment,
  runtime, configuration): the service supplies candidates, never decisions.
* **push**, at the end of the session: every entry of the local store not yet on the service is uploaded as a
  content-addressed document (its source-file facts as separate documents, shared between entries), then
  appended to the key log; the session's receipts follow as one document, linked to the run.

The token comes from an inherited pipe (``FENVIX_CACHE_TOKEN_FD``, what ``fenvix-run`` uses), a hand-off file
(``FENVIX_CACHE_TOKEN_FILE``, deleted once read) or ``FENVIX_CACHE_TOKEN``; before any test runs it is taken out of
the environment, the descriptor and the file. Tests run in the client's process, so code that searches the process
memory can still find it: untrusted code (pull-request jobs) gets read-only tokens. Plain ``http://`` is refused to
hosts other than loopback. The local mirror is ``FENVIX_CACHE_LOCAL`` or
``~/.cache/fenvix/remote/<digest of the URL>``. Any service error is reported and the session continues on the
local mirror: a cache problem never fails a test run.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from . import _core

# real clocks, bound before Level 0 virtualises the time module (the client's timings and retry waits are real)
_perf = time.perf_counter
_sleep = time.sleep

SCHEMES = ("http://", "https://")
DOC_VERSION = 1
_ENTRY_FIELDS = ("outcome", "report", "fingerprint", "duration", "run", "config", "runtime", "epoch", "env", "data")
_JOURNAL = "remote-pushed.json"
CLIENT: "RemoteCache | None" = None


def is_url(value) -> bool:
    return isinstance(value, str) and value.startswith(SCHEMES)


def canonical(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def doc_id(doc) -> str:
    return hashlib.sha256(canonical(doc)).hexdigest()


def lookup_key(nodeid: str, config: str, runtime: str, epoch) -> str:
    """Where a test's entries are filed on the service: test id, configuration digest, runtime digest and clock
    epoch (empty for a test that did not read the clock). Computable before the test runs, unlike the entry's
    proof key (the digest of every recorded input), which the entry document carries."""
    b = bytearray()
    for part in ("fenvix-lookup-1", nodeid, config, runtime, "" if epoch is None else str(epoch)):
        raw = part.encode()
        b += struct.pack("<Q", len(raw)) + raw
    return _core.digest(bytes(b))


# ---------------------------------------------------------------------------------------------------------------------
class ServiceError(Exception):
    pass


class _NetworkOpen:
    """Level 0 closes the network (external hosts are refused even between tests): the client's own requests to the
    service run with the policy suspended, in the main thread, while no test runs."""

    def __enter__(self):
        from . import network

        self.network = network
        self.saved = network.POLICY
        network.POLICY = None

    def __exit__(self, *exc):
        self.network.POLICY = self.saved
        return False


class Http:
    def __init__(self, base: str, token: str | None, timeout: float = 60.0, retries: int = 2):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retries = retries
        self.sent = 0
        self.received = 0
        self.requests = 0

    def call(self, method: str, path: str, body=None):
        data = None
        headers = {"Accept-Encoding": "gzip", "User-Agent": "fenvix-engine"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
            if len(data) > 4096:
                data = gzip.compress(data, 5)
                headers["Content-Encoding"] = "gzip"
        last = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
            try:
                with _NetworkOpen(), urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    self.requests += 1
                    self.sent += len(data or b"")
                    self.received += len(raw)
                    if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw or b"{}")
            except urllib.error.HTTPError as e:
                try:
                    msg = json.loads(e.read() or b"{}").get("error", "")
                except ValueError:
                    msg = ""
                if e.code < 500:
                    raise ServiceError(f"HTTP {e.code} on {path}: {msg}") from None
                last = ServiceError(f"HTTP {e.code} on {path}: {msg}")
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = ServiceError(f"{type(e).__name__} on {path}: {getattr(e, 'reason', e)}")
            if attempt < self.retries:
                _sleep(0.5 * (2 ** attempt))
        raise last  # type: ignore[misc]


def split_url(url: str) -> tuple[str, str]:
    """(service base URL, namespace) from ``https://host[:port]/<namespace>``."""
    u = urllib.parse.urlsplit(url)
    ns = urllib.parse.unquote(u.path.strip("/")) or "default"
    return f"{u.scheme}://{u.netloc}", ns


def local_dir_for(url: str) -> str:
    v = os.environ.get("FENVIX_CACHE_LOCAL")
    if v:
        return os.path.abspath(v)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "fenvix", "remote", hashlib.sha256(url.encode()).hexdigest()[:16])


def _token_to_pipe() -> None:
    """A token given in FENVIX_CACHE_TOKEN moves to an inherited pipe (FENVIX_CACHE_TOKEN_FD) before detpy re-executes
    the interpreter, so the process that runs the tests does not carry it in its environment block
    (/proc/self/environ)."""
    t = os.environ.pop("FENVIX_CACHE_TOKEN", None)
    if not t or os.environ.get("FENVIX_CACHE_TOKEN_FD"):
        return
    r, w = os.pipe()
    os.write(w, t.strip().encode())
    os.close(w)
    os.set_inheritable(r, True)
    os.environ["FENVIX_CACHE_TOKEN_FD"] = str(r)


def _take_token() -> str | None:
    """Read the token once, from the first source set, and leave nothing behind for the tests: an inherited pipe
    (FENVIX_CACHE_TOKEN_FD, closed after reading), a hand-off file (FENVIX_CACHE_TOKEN_FILE, deleted after reading:
    keep the master copy elsewhere), or FENVIX_CACHE_TOKEN."""
    fd = os.environ.get("FENVIX_CACHE_TOKEN_FD")
    if fd:
        try:
            n = int(fd)
            chunks = []
            while True:
                b = os.read(n, 4096)
                if not b:
                    break
                chunks.append(b)
            os.close(n)
            return b"".join(chunks).decode().strip() or None
        except (ValueError, OSError):
            return None
    f = os.environ.get("FENVIX_CACHE_TOKEN_FILE")
    if f:
        try:
            with open(f) as fh:
                t = fh.read().strip() or None
            os.unlink(f)
            return t
        except OSError:
            return None
    t = os.environ.get("FENVIX_CACHE_TOKEN")
    return t.strip() if t else None


def localize(value):
    """``--det-cache`` value -> the directory the engine uses. A service URL becomes its local mirror and the client
    is set up (once per process); a directory is returned unchanged. The token is read later, by ``hide_token``,
    in the process that runs the tests."""
    global CLIENT
    if not is_url(value):
        return value
    _token_to_pipe()
    if CLIENT is None or CLIENT.url != value:
        CLIENT = RemoteCache(value, None, local_dir_for(value))
    return CLIENT.local_dir


_CLIENT_ENV = ("FENVIX_CACHE_TOKEN", "FENVIX_CACHE_TOKEN_FD", "FENVIX_CACHE_TOKEN_FILE", "FENVIX_CACHE_LOCAL",
               "FENVIX_CACHE_REPORT", "FENVIX_CACHE_ALLOW_HTTP")


def hide_token() -> None:
    """In the process that runs the tests, before any test: take the token (closing its pipe or deleting its
    hand-off file) and remove the client's variables from os.environ, so no token is left in the environment, in
    an open descriptor or in a file. A test runs in the same process as the client, so code that searches the
    process memory can still find it: give untrusted code read-only tokens (docs/SHARED-CACHE.md)."""
    if CLIENT is None:  # no service in this session: leave the caller's token sources alone
        return
    token = _take_token()
    if token:
        CLIENT.http.token = token
    for k in _CLIENT_ENV:
        os.environ.pop(k, None)


def attach(config) -> None:
    """Register the pull/push hooks. Called before the engine's proof-cache plugin is registered: pluggy runs
    later-registered ``trylast`` hooks later, so the pull runs just before the engine's reuse decision."""
    if CLIENT is None:
        return
    config.pluginmanager.register(_Hooks(CLIENT), "detpy-cache-remote")


# ---------------------------------------------------------------------------------------------------------------------
class _Docs:
    """Content-addressed documents of a store (the JSON the Rust core writes): one ``file`` document per version of a
    source file (its facts), one ``set`` document per set of files (sorted file document ids; sets are shared by
    many tests), one ``entry`` document per test. Every document is independent of the local file and set indices,
    so the same entry gives the same address on every machine."""

    def __init__(self, store: dict):
        self.files = store.get("files", [])
        self.sets = store.get("sets", [])
        self.file_id: dict[int, str] = {}
        self.set_id: dict[tuple, str] = {}
        self.docs: dict[str, dict] = {}

    def file(self, fi: int) -> str:
        fid = self.file_id.get(fi)
        if fid is None:
            f = self.files[fi]
            d = {"kind": "file", "v": DOC_VERSION, "path": f["path"], "content": f["content"],
                 "skeleton": f["skeleton"], "hooks": f["hooks"], "units": f.get("units", []),
                 "imports": f.get("imports", [])}
            fid = doc_id(d)
            self.file_id[fi] = fid
            self.docs[fid] = d
        return fid

    def set_of(self, fids) -> str:
        key = tuple(sorted(set(fids)))
        sid = self.set_id.get(key)
        if sid is None:
            d = {"kind": "set", "v": DOC_VERSION, "files": list(key)}
            sid = doc_id(d)
            self.set_id[key] = sid
            self.docs[sid] = d
        return sid

    def entry(self, nodeid: str, e: dict) -> dict:
        n = len(self.files)

        def members(sid) -> list[str]:
            s = self.sets[sid] if isinstance(sid, int) and 0 <= sid < len(self.sets) else []
            return [self.file(fi) for fi in s if 0 <= fi < n]

        u = e.get("units") or []
        pairs = [(self.file(u[i]), u[i + 1]) for i in range(0, len(u) - 1, 2) if 0 <= u[i] < n]
        ufiles = sorted({f for f, _ in pairs})
        pos = {f: k for k, f in enumerate(ufiles)}
        return {"kind": "entry", "v": DOC_VERSION, "nodeid": nodeid, "proof_key": e.get("key"),
                "entry": {**{k: e.get(k) for k in _ENTRY_FIELDS},
                          # what the start-up processes gave back: only on the entries that have it, so the address
                          # of every other entry stays as it was
                          **({"startup": e["startup"]} if e.get("startup") else {})},
                "content": self.set_of(members(e.get("content"))), "skeleton": self.set_of(members(e.get("skeleton"))),
                "hooks": self.set_of(members(e.get("hooks"))), "unit_files": self.set_of(ufiles),
                "units": sorted([pos[f], k] for f, k in pairs)}


def _is_loopback(host: str) -> bool:
    import ipaddress

    if host in ("localhost", "localhost.localdomain", "ip6-localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def own_file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


class RemoteCache:
    def __init__(self, url: str, token: str | None, local_dir: str):
        self.url = url
        self.base, self.ns = split_url(url)
        self.local_dir = local_dir
        self.http = Http(self.base, token)
        self.pc = None
        self.error: str | None = None
        self.stats: dict = {"service": self.base, "namespace": self.ns, "local_dir": local_dir}
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        self.disabled = None
        if url.startswith("http://") and not _is_loopback(host) and os.environ.get("FENVIX_CACHE_ALLOW_HTTP") != "1":
            # the bearer token and the documents would cross the network in clear
            self.disabled = f"refusing plain http:// to {host} (use https://, or FENVIX_CACHE_ALLOW_HTTP=1)"
            self._fail("setup", ServiceError(self.disabled))
        self._nsq = urllib.parse.quote(self.ns, safe="")
        self.pulled_docs: set[str] = set()
        self.report_path = os.environ.get("FENVIX_CACHE_REPORT")

    def _path(self, what: str) -> str:
        return f"/v1/ns/{self._nsq}/{what}"

    def _fail(self, phase: str, e: Exception) -> None:
        self.stats.setdefault("errors", []).append(f"{phase}: {e}")
        self.error = "; ".join(self.stats["errors"])

    # -- pull -----------------------------------------------------------------------------------------------------
    def _refresh_facts(self) -> None:
        from . import _codefacts
        from .proofcache import _module_of

        pc = self.pc
        for path, content in pc.store.changed_code_files():
            mod, is_pkg = _module_of(os.path.join(pc.root, path))
            f = _codefacts.read_facts(os.path.join(pc.root, path), content, mod, is_pkg)
            if f is not None:
                pc.store.set_fresh(path, content, f[0], f[1], f[2], f[3])

    def _set_indices(self, sid: str, docs: dict, memo: dict) -> list[int] | None:
        """Store indices of the files of set document ``sid`` (added to the local store as needed)."""
        if sid in memo:
            return memo[sid]
        sd = docs.get(sid)
        out = None
        if sd is not None:
            store, out = self.pc.store, []
            for fid in sd["files"]:
                ix = memo.get(fid)
                if ix is None:
                    f = docs.get(fid)
                    if f is None:
                        out = None
                        break
                    units = [(u["q"], u["a"], u["b"], u["d"]) if isinstance(u, dict) else tuple(u)
                             for u in f.get("units", [])]
                    ix = store.add_file(f["path"], f["content"], f["skeleton"], f["hooks"], units,
                                        f.get("imports", []))
                    memo[fid] = ix
                out.append(ix)
        memo[sid] = out
        return out

    def _inject(self, doc: dict, docs: dict, memo: dict) -> bool:
        sets = [self._set_indices(doc[k], docs, memo) for k in ("content", "skeleton", "hooks", "unit_files")]
        if any(x is None for x in sets):
            return False
        content, skeleton, hooks, ufiles = sets
        e = doc["entry"]
        self.pc.store.record(doc["nodeid"], e["outcome"], json.dumps(e.get("report")), e["fingerprint"],
                             float(e.get("duration") or 0.0), e["run"], e["config"], e["runtime"], e.get("epoch"),
                             [tuple(x) for x in e.get("env") or []], [tuple(x) for x in e.get("data") or []],
                             content, skeleton, hooks, [(ufiles[f], k) for f, k in doc["units"]],
                             startup=e.get("startup") or "")
        return True

    def pull(self, items) -> None:
        if self.disabled:
            return
        pc = self.pc
        t0 = _perf()
        st = self.stats
        st.update(pull_candidates=0, pull_tests_with_candidates=0, pull_local_already=0, pull_injected=0,
                  pull_proven=0)
        keys: dict[str, str] = {}
        for it in items:
            nid = it.nodeid
            keys[lookup_key(nid, pc.config_digest, pc.runtime_digest, None)] = nid
            keys[lookup_key(nid, pc.config_digest, pc.runtime_digest, pc.epoch)] = nid
        try:
            found: dict[str, list] = {}
            klist = sorted(keys)
            for i in range(0, len(klist), 5000):
                found.update(self.http.call("POST", self._path("lookup"),
                                            {"keys": klist[i:i + 5000], "limit": 3})["found"])
            per_test: dict[str, list] = {}
            for k, ids in found.items():
                per_test.setdefault(keys[k], []).extend(ids)
            docs = self._get(sorted({d for ds in per_test.values() for d in ds}))
            sets = self._get(sorted({d[k] for d in docs.values() for k in ("content", "skeleton", "hooks",
                                                                           "unit_files") if d.get(k)}))
            docs.update(sets)
            docs.update(self._get(sorted({f for sd in sets.values() for f in sd.get("files", [])})))
        except ServiceError as e:
            self._fail("pull", e)
            st["pull_seconds"] = round(_perf() - t0, 3)
            return
        t1 = _perf()
        st["pull_fetch_seconds"] = round(t1 - t0, 3)
        st["pull_candidates"] = sum(len(v) for v in per_test.values())
        st["pull_tests_with_candidates"] = len(per_test)
        self._refresh_facts()
        pending = {}
        for nid, ids in per_test.items():
            ok, _ = pc.store.check(nid)
            if ok:
                st["pull_local_already"] += 1
                continue
            cands = []
            for d in ids:  # newest first
                if d in docs and d not in cands and docs[d].get("kind") == "entry" and docs[d].get("nodeid") == nid:
                    if self._names_own_file(docs[d], docs):
                        cands.append(d)
                    else:
                        st["pull_rejected_no_own_file"] = st.get("pull_rejected_no_own_file", 0) + 1
            if cands:
                pending[nid] = cands
        memo: dict = {}
        rnd = 0
        while pending:
            for nid, cands in pending.items():
                if self._inject(docs[cands[0]], docs, memo):
                    st["pull_injected"] += 1
                    self.pulled_docs.add(cands[0])
            self._refresh_facts()
            nxt = {}
            for nid, cands in pending.items():
                ok, _ = pc.store.check(nid)
                if ok:
                    st["pull_proven"] += 1
                elif len(cands) > 1:
                    nxt[nid] = cands[1:]
            pending = nxt
            rnd += 1
        st["pull_rounds"] = rnd
        st["pull_merge_seconds"] = round(_perf() - t1, 3)
        st["pull_seconds"] = round(_perf() - t0, 3)

    @staticmethod
    def _names_own_file(doc: dict, docs: dict) -> bool:
        """Floor check: a candidate must list its test's own file among its code or data inputs. Every entry the
        engine records does (10,963 of 10,963 in the pygments, click and marshmallow stores); an entry that claims
        no inputs would otherwise be reusable for any code at any commit. It does not stop a forger who lists the
        file: only signed entries would."""
        own = own_file(doc.get("nodeid", ""))
        if any(p == own for p, _ in (doc.get("entry") or {}).get("data") or []):
            return True
        for k in ("content", "skeleton", "hooks", "unit_files"):
            for fid in (docs.get(doc.get(k)) or {}).get("files", []):
                if (docs.get(fid) or {}).get("path") == own:
                    return True
        return False

    def _get(self, ids: list[str]) -> dict:
        """Documents by address; each one's address is recomputed, and a document that does not match it is dropped
        (a compromised service or anything on the path cannot substitute content)."""
        out = {}
        for i in range(0, len(ids), 2000):
            got = self.http.call("POST", "/v1/blobs/get", {"ids": ids[i:i + 2000]})["docs"]
            for k, d in got.items():
                if doc_id(d) == k:
                    out[k] = d
                else:
                    self.stats["pull_bad_address"] = self.stats.get("pull_bad_address", 0) + 1
        return out

    # -- push -----------------------------------------------------------------------------------------------------
    def _journal_path(self) -> str:
        return os.path.join(self.local_dir, _JOURNAL)

    def _journal(self) -> set:
        try:
            with open(self._journal_path()) as fh:
                d = json.load(fh)
            if d.get("service") == self.base and d.get("namespace") == self.ns:
                return set(d.get("docs", []))
        except (OSError, ValueError, AttributeError):
            pass
        return set()

    def _save_journal(self, docs: set) -> None:
        p = self._journal_path()
        tmp = f"{p}.tmp{os.getpid()}"
        try:
            with open(tmp, "w") as fh:
                json.dump({"service": self.base, "namespace": self.ns, "docs": sorted(docs)}, fh)
            os.replace(tmp, p)
        except OSError:
            pass

    def push(self) -> None:
        if self.disabled:
            return
        pc = self.pc
        t0 = _perf()
        st = self.stats
        try:
            with open(os.path.join(self.local_dir, "proof-cache.json")) as fh:
                store = json.load(fh)
        except (OSError, ValueError) as e:
            self._fail("push", ServiceError(f"local store unreadable: {e}"))
            return
        journal = self._journal() | self.pulled_docs
        ds = _Docs(store)
        entry_docs, rows = {}, []
        for nid, e in store.get("tests", {}).items():
            doc = ds.entry(nid, e)
            did = doc_id(doc)
            if did in journal:
                continue
            entry_docs[did] = doc
            rows.append({"key": lookup_key(nid, e.get("config", ""), e.get("runtime", ""), e.get("epoch")),
                         "doc": did, "run": e.get("run")})
        # only the file and set documents the new entries need
        need: dict[str, dict] = {}
        for d in entry_docs.values():
            for k in ("content", "skeleton", "hooks", "unit_files"):
                sd = ds.docs[d[k]]
                need[d[k]] = sd
                for f in sd["files"]:
                    need[f] = ds.docs[f]
        st.update(push_entries=len(entry_docs), push_entry_docs_new=0, push_file_docs_new=0, push_set_docs_new=0)
        st["push_build_seconds"] = round(_perf() - t0, 3)
        try:
            # files and sets first, entries next, then the key log: a key never points at a missing document
            for docs, label in ((need, None), (entry_docs, "push_entry_docs_new")):
                ids = sorted(docs)
                missing = []
                for i in range(0, len(ids), 20000):
                    missing += self.http.call("POST", "/v1/blobs/missing", {"ids": ids[i:i + 20000]})["missing"]
                if label:
                    st[label] = len(missing)
                else:
                    st["push_file_docs_new"] = sum(1 for m in missing if docs[m].get("kind") == "file")
                    st["push_set_docs_new"] = sum(1 for m in missing if docs[m].get("kind") == "set")
                batch, size = {}, 0
                for i in missing:
                    batch[i] = docs[i]
                    size += len(canonical(docs[i]))
                    if size > 16 * 1024 * 1024 or len(batch) >= 5000:
                        self.http.call("POST", "/v1/blobs/put", {"docs": batch})
                        batch, size = {}, 0
                if batch:
                    self.http.call("POST", "/v1/blobs/put", {"docs": batch})
            for i in range(0, len(rows), 5000):
                self.http.call("POST", self._path("keys"), {"put": rows[i:i + 5000]})
            journal |= set(entry_docs)
            self._save_journal(journal)
            rec = self._receipts_doc()
            if rec is not None:
                rid = doc_id(rec)
                self.http.call("POST", "/v1/blobs/put", {"docs": {rid: rec}})
                self.http.call("POST", self._path("runs"), {"run": pc.run_id, "receipts": rid,
                                                             "summary": self._run_summary()})
                st["receipts_doc"] = rid
        except ServiceError as e:
            self._fail("push", e)
        st["push_seconds"] = round(_perf() - t0, 3)

    def _receipts_doc(self):
        rows = []
        try:
            with open(self.pc.receipts_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        except (OSError, ValueError):
            return None
        return {"kind": "receipts", "v": DOC_VERSION, "run": self.pc.run_id, "rows": rows}

    def _run_summary(self) -> dict:
        pc = self.pc
        try:
            s = pc.summary_data()
        except Exception:
            s = {}
        keep = ("tests", "reused", "ran", "runtime", "config", "epoch_ns", "miss_reasons")
        return {k: s.get(k) for k in keep if k in s}

    def report(self) -> dict:
        d = dict(self.stats)
        d.update(requests=self.http.requests, bytes_sent=self.http.sent, bytes_received=self.http.received,
                 error=self.error)
        return d


class _Hooks:
    def __init__(self, client: RemoteCache):
        self.client = client

    def _bind(self) -> bool:
        if self.client.pc is None:
            from . import proofcache

            self.client.pc = proofcache.PLUGIN
        return self.client.pc is not None

    @pytest.hookimpl(trylast=True)
    def pytest_collection_finish(self, session):
        # registered after the engine's plugin, so among the trylast hooks this runs just before the engine's reuse
        # decision: after detpy opened its trace (which creates .detpy/ in the project), so the files and listings
        # checked here look the way the tests saw them
        if not self._bind():
            return
        try:
            self.client.pull(session.items)
        except Exception as e:  # never break the session: the local mirror still works
            self.client._fail("pull", e)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        # after the engine recorded and saved the session's entries in the local mirror (detpy's session hook runs
        # earlier), before the terminal summary
        if not self._bind():
            return
        try:
            self.client.push()
        except Exception as e:
            self.client._fail("push", e)
        out = self.client.report_path
        if out:
            try:
                with open(out, "w") as fh:
                    json.dump(self.client.report(), fh, indent=1)
            except OSError:
                pass

    def pytest_terminal_summary(self, terminalreporter):
        if self.client.pc is None:
            return
        r = self.client.report()
        tr = terminalreporter
        line = (f"shared cache {r['service']} [{r['namespace']}]: candidates for {r.get('pull_tests_with_candidates', 0)}"
                f" tests, {r.get('pull_proven', 0)} proven from the service, {r.get('pull_local_already', 0)} already "
                f"proven locally; pushed {r.get('push_entry_docs_new', 0)} entries "
                f"({r.get('push_file_docs_new', 0)} file facts); {r['requests']} requests, "
                f"pull {r.get('pull_seconds', 0)} s, push {r.get('push_seconds', 0)} s")
        tr.write_line(line)
        if r.get("error"):
            tr.write_line(f"shared cache: {r['error']} (the local mirror {r['local_dir']} was used)", yellow=True)


if __name__ == "__main__":
    print(json.dumps({"lookup_key": lookup_key(*sys.argv[1:5])}))
