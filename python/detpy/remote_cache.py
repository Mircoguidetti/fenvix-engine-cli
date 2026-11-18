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

The token comes from ``FENVIX_CACHE_TOKEN`` (or the file named by ``FENVIX_CACHE_TOKEN_FILE``) and is removed from
the environment before any test runs. The local mirror is ``FENVIX_CACHE_LOCAL`` or
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
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
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
                time.sleep(0.5 * (2 ** attempt))
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


def _read_token() -> str | None:
    t = os.environ.get("FENVIX_CACHE_TOKEN")
    if t:
        return t.strip()
    f = os.environ.get("FENVIX_CACHE_TOKEN_FILE")
    if f:
        try:
            with open(f) as fh:
                return fh.read().strip() or None
        except OSError:
            return None
    return None


def localize(value):
    """``--det-cache`` value -> the directory the engine uses. A service URL becomes its local mirror and the client
    is set up (once per process); a directory is returned unchanged."""
    global CLIENT
    if not is_url(value):
        return value
    if CLIENT is None or CLIENT.url != value:
        CLIENT = RemoteCache(value, _read_token(), local_dir_for(value))
    return CLIENT.local_dir


def hide_token() -> None:
    """Remove the token from the environment of the test session (called in the process that runs the tests)."""
    for k in ("FENVIX_CACHE_TOKEN",):
        os.environ.pop(k, None)


def attach(config, pc) -> None:
    """Register the pull/push hooks next to the proof-cache plugin ``pc``."""
    if CLIENT is None or pc is None:
        return
    CLIENT.pc = pc
    config.pluginmanager.register(_Hooks(CLIENT), "detpy-cache-remote")


# ---------------------------------------------------------------------------------------------------------------------
def _entry_doc(nodeid: str, e: dict, files: list, sets: list, file_ids: dict) -> tuple[dict, dict]:
    """(entry document, {file doc id: file doc} it references) from an entry of the store JSON."""
    used: list[int] = []
    pos: dict[int, int] = {}

    def ref(fi: int) -> int:
        if fi not in pos:
            pos[fi] = len(used)
            used.append(fi)
        return pos[fi]

    def set_refs(sid) -> list[int]:
        s = sets[sid] if isinstance(sid, int) and 0 <= sid < len(sets) else []
        return [ref(fi) for fi in s if 0 <= fi < len(files)]

    content, skeleton, hooks = set_refs(e.get("content")), set_refs(e.get("skeleton")), set_refs(e.get("hooks"))
    u = e.get("units") or []
    units = [[ref(u[i]), u[i + 1]] for i in range(0, len(u) - 1, 2) if 0 <= u[i] < len(files)]
    fdocs = {}
    ids = []
    for fi in used:
        fid = file_ids.get(fi)
        if fid is None:
            f = files[fi]
            fd = {"kind": "file", "v": DOC_VERSION, "path": f["path"], "content": f["content"],
                  "skeleton": f["skeleton"], "hooks": f["hooks"], "units": f.get("units", []),
                  "imports": f.get("imports", [])}
            fid = doc_id(fd)
            file_ids[fi] = fid
            fdocs[fid] = fd
        ids.append(fid)
    doc = {"kind": "entry", "v": DOC_VERSION, "nodeid": nodeid, "proof_key": e.get("key"),
           "entry": {k: e.get(k) for k in _ENTRY_FIELDS}, "files": ids, "content": content, "skeleton": skeleton,
           "hooks": hooks, "units": units}
    return doc, fdocs


class RemoteCache:
    def __init__(self, url: str, token: str | None, local_dir: str):
        self.url = url
        self.base, self.ns = split_url(url)
        self.local_dir = local_dir
        self.http = Http(self.base, token)
        self.pc = None
        self.error: str | None = None
        self.stats: dict = {"service": self.base, "namespace": self.ns, "local_dir": local_dir}
        self._nsq = urllib.parse.quote(self.ns, safe="")
        self.pulled_docs: set[str] = set()

    def _path(self, what: str) -> str:
        return f"/v1/ns/{self._nsq}/{what}"

    def _fail(self, phase: str, e: Exception) -> None:
        self.error = f"{phase}: {e}"
        self.stats.setdefault("errors", []).append(self.error)

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

    def _inject(self, doc: dict, files: dict) -> bool:
        store = self.pc.store
        idx = []
        for fid in doc["files"]:
            f = files.get(fid)
            if f is None:
                return False
            units = [(u["q"], u["a"], u["b"], u["d"]) if isinstance(u, dict) else tuple(u) for u in f.get("units", [])]
            idx.append(store.add_file(f["path"], f["content"], f["skeleton"], f["hooks"], units, f.get("imports", [])))
        e = doc["entry"]
        store.record(doc["nodeid"], e["outcome"], json.dumps(e.get("report")), e["fingerprint"],
                     float(e.get("duration") or 0.0), e["run"], e["config"], e["runtime"], e.get("epoch"),
                     [tuple(x) for x in e.get("env") or []], [tuple(x) for x in e.get("data") or []],
                     [idx[i] for i in doc["content"]], [idx[i] for i in doc["skeleton"]],
                     [idx[i] for i in doc["hooks"]], [(idx[f], u) for f, u in doc["units"]])
        return True

    def pull(self, items) -> None:
        pc = self.pc
        t0 = time.perf_counter()
        st = self.stats
        st.update(pull_candidates=0, pull_tests_with_candidates=0, pull_local_already=0, pull_injected=0,
                  pull_proven=0)
        nids = [it.nodeid for it in items]
        keys: dict[str, str] = {}
        for nid in nids:
            keys[lookup_key(nid, pc.config_digest, pc.runtime_digest, None)] = nid
            keys[lookup_key(nid, pc.config_digest, pc.runtime_digest, pc.epoch)] = nid
        try:
            found: dict[str, list] = {}
            klist = sorted(keys)
            for i in range(0, len(klist), 5000):
                found.update(self.http.call("POST", self._path("lookup"),
                                            {"keys": klist[i:i + 5000], "limit": 3})["found"])
            per_test: dict[str, list] = {}
            for k, docs in found.items():
                per_test.setdefault(keys[k], []).extend(docs)
            need = sorted({d for ds in per_test.values() for d in ds})
            docs = self._get(need)
            fneed = sorted({f for d in docs.values() for f in d.get("files", [])})
            files = self._get(fneed)
        except ServiceError as e:
            self._fail("pull", e)
            st["pull_seconds"] = round(time.perf_counter() - t0, 3)
            return
        st["pull_candidates"] = sum(len(v) for v in per_test.values())
        st["pull_tests_with_candidates"] = len(per_test)
        # candidates newest first; skip any the local store already has
        self._refresh_facts()
        pending = {}
        for nid, ids in per_test.items():
            ok, _ = pc.store.check(nid)
            if ok:
                st["pull_local_already"] += 1
                continue
            seen, cands = set(), []
            for d in ids:
                if d in docs and d not in seen and docs[d].get("nodeid") == nid:
                    seen.add(d)
                    cands.append(d)
            if cands:
                pending[nid] = cands
        rnd = 0
        while pending:
            for nid, cands in pending.items():
                if self._inject(docs[cands[0]], files):
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
        st["pull_seconds"] = round(time.perf_counter() - t0, 3)

    def _get(self, ids: list[str]) -> dict:
        out = {}
        for i in range(0, len(ids), 2000):
            out.update(self.http.call("POST", "/v1/blobs/get", {"ids": ids[i:i + 2000]})["docs"])
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
        pc = self.pc
        t0 = time.perf_counter()
        st = self.stats
        try:
            with open(os.path.join(self.local_dir, "proof-cache.json")) as fh:
                store = json.load(fh)
        except (OSError, ValueError) as e:
            self._fail("push", ServiceError(f"local store unreadable: {e}"))
            return
        files, sets = store.get("files", []), store.get("sets", [])
        journal = self._journal() | self.pulled_docs
        entry_docs, file_docs, rows, file_ids = {}, {}, [], {}
        for nid, e in store.get("tests", {}).items():
            doc, fdocs = _entry_doc(nid, e, files, sets, file_ids)
            did = doc_id(doc)
            if did in journal:
                continue
            entry_docs[did] = doc
            file_docs.update(fdocs)
            rows.append({"key": lookup_key(nid, e.get("config", ""), e.get("runtime", ""), e.get("epoch")), "doc": did,
                         "run": e.get("run")})
        st.update(push_entries=len(entry_docs), push_entry_docs_new=0, push_file_docs_new=0)
        try:
            for docs, label in ((file_docs, "push_file_docs_new"), (entry_docs, "push_entry_docs_new")):
                ids = sorted(docs)
                missing = []
                for i in range(0, len(ids), 20000):
                    missing += self.http.call("POST", "/v1/blobs/missing", {"ids": ids[i:i + 20000]})["missing"]
                st[label] = len(missing)
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
        st["push_seconds"] = round(time.perf_counter() - t0, 3)

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

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_finish(self, session):
        try:
            self.client.pull(session.items)
        except Exception as e:  # never break the session: the local mirror still works
            self.client._fail("pull", e)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        # after the engine recorded and saved the session's entries in the local mirror (detpy's session hook runs
        # earlier), before the terminal summary
        try:
            self.client.push()
        except Exception as e:
            self.client._fail("push", e)
        out = os.environ.get("FENVIX_CACHE_REPORT")
        if out:
            try:
                with open(out, "w") as fh:
                    json.dump(self.client.report(), fh, indent=1)
            except OSError:
                pass

    def pytest_terminal_summary(self, terminalreporter):
        r = self.client.report()
        tr = terminalreporter
        line = (f"shared cache {r['service']} [{r['namespace']}]: candidates for {r.get('pull_tests_with_candidates', 0)}"
                f" tests, {r.get('pull_proven', 0)} proven from the service, {r.get('pull_local_already', 0)} already "
                f"proven locally; pushed {r.get('push_entry_docs_new', 0)} entries "
                f"({r.get('push_file_docs_new', 0)} file facts); {r['requests']} requests")
        tr.write_line(line)
        if r.get("error"):
            tr.write_line(f"shared cache: {r['error']} (the local mirror {r['local_dir']} was used)", yellow=True)


if __name__ == "__main__":
    print(json.dumps({"lookup_key": lookup_key(*sys.argv[1:5])}))
