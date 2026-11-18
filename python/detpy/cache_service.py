"""fenvix cache service: a small HTTP store for proof-cache entries and receipts.

Self-hostable, standard library only (``http.server`` + SQLite), one file per deployment::

    python -m detpy.cache_service token --data DIR --org acme            # prints a new token once
    python -m detpy.cache_service serve --data DIR [--host 127.0.0.1] [--port 8787]

Model (every request is scoped to the organization of its token; a token never reaches another organization):

* **blobs**: immutable JSON documents addressed by the SHA-256 of their canonical bytes
  (``json.dumps(doc, sort_keys=True, separators=(",", ":"))``). The server recomputes the address of every
  document it receives and refuses a mismatch, so a stored document can never be replaced. Kinds: ``entry`` (one
  test's recorded inputs and result), ``file`` (facts of one version of one source file), ``receipts`` (one run's
  receipts).
* **keys**: an append-only log ``(namespace, proof key) -> entry blob``. The proof key is the engine's entry key
  (test id, configuration digest, runtime digest, clock epoch). A lookup returns the most recent distinct entries
  under each key; the engine checks every one against the current code and data before reusing anything.
* **runs**: an append-only log of runs with their receipts blob and summary.
* **untrusted**: an append-only log of proof keys a cache audit found wrong (a reusable result that two fresh runs
  contradicted). A lookup leaves out every entry filed under a proof key before that key was marked; an entry
  filed after the mark (a fresh run that recorded the key again) is returned. Every client follows the log
  (``?after=SEQ``) and applies each mark once to its own local mirror, so a machine that already holds the wrong
  entry stops reusing it too. Any token of the organization may mark a key: a mark only stops reuse.
  ``GET /v1/audit`` sums the audit counts per namespace (project) and over all of them, with the 95% upper bound
  on the wrong-skip rate: ``checked``/``matched`` from the run summaries (write tokens), ``wrong`` from every
  token's jobs (summaries and the untrusted log).

Nothing is ever updated or deleted through the API. Authentication: ``Authorization: Bearer <token>``; the server
keeps only the SHA-256 of each token (``DIR/tokens.json``, re-read when it changes). Read-only tokens may look up
and download but not write. Transport compression: ``Content-Encoding: gzip`` on requests, ``Accept-Encoding:
gzip`` on responses. Run it behind a TLS reverse proxy outside a private network.

Endpoints (JSON in, JSON out)::

    GET  /v1/health                                   no auth
    POST /v1/blobs/missing   {"ids": [...]}           -> {"missing": [...]}
    POST /v1/blobs/put       {"docs": {id: doc}}      -> {"stored": n, "existing": n}
    POST /v1/blobs/get       {"ids": [...]}           -> {"docs": {id: doc}, "missing": [...]}
    POST /v1/ns/<ns>/keys    {"put": [{"key", "doc", "run"}]}          -> {"added": n}
    POST /v1/ns/<ns>/lookup  {"keys": [...], "limit": 3}               -> {"found": {key: [doc id, ...]}}
    POST /v1/ns/<ns>/runs    {"run", "receipts", "summary"}            -> {"ok": true}
    GET  /v1/ns/<ns>/runs                                              -> {"runs": [...]}
    POST /v1/ns/<ns>/untrusted {"put": [{"proof_key", "nodeid", "run", "reason"}]} -> {"added": n}
    GET  /v1/ns/<ns>/untrusted[?after=SEQ&limit=N]                     -> {"untrusted": [{"seq", "proof_key", ...}]}
    GET  /v1/audit                                                     -> {"projects": {ns: {...}}, "all": {...}}
    GET  /v1/stats                                                     -> counts for the token's organization
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
import zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API = "v1"
MAX_BODY = 64 * 1024 * 1024  # decompressed; the client sends at most ~16 MB of documents per request
MAX_IDS = 50_000
_ID_CHARS = set("0123456789abcdef")


def canonical(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def doc_id(doc) -> str:
    return hashlib.sha256(canonical(doc)).hexdigest()


def _valid_id(s) -> bool:
    return isinstance(s, str) and len(s) == 64 and set(s) <= _ID_CHARS


def _valid_ns(s: str) -> bool:
    return 0 < len(s) <= 200 and all(c.isalnum() or c in "-_.@/+:" for c in s)


def upper_bound_95(checked: int, wrong: int) -> float:
    """One-sided 95% upper bound on the wrong-skip rate: 3/n when no wrong skip (rule of three), else the exact
    Clopper-Pearson bound. Same rule as the engine core (``detpy._core.audit_upper_bound``); kept here so the service
    stays standard library only."""
    import math

    if checked <= 0:
        return 1.0
    if wrong <= 0:
        return min(1.0, 3.0 / checked)
    if wrong >= checked:
        return 1.0

    def cdf(p: float) -> float:
        lp, lq = math.log(p), math.log1p(-p)
        terms, lc = [], 0.0
        for i in range(wrong + 1):
            if i:
                lc += math.log(checked - i + 1) - math.log(i)
            terms.append(lc + i * lp + (checked - i) * lq)
        m = max(terms)
        return min(1.0, math.exp(m + math.log(sum(math.exp(t - m) for t in terms))))

    lo, hi = wrong / checked, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if cdf(mid) > 0.05:
            lo = mid
        else:
            hi = mid
    return hi


# ---------------------------------------------------------------------------------------------------------------------
class Tokens:
    def __init__(self, path: str):
        self.path = path
        self.mtime = None
        self.by_hash: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _load(self) -> None:
        try:
            m = os.stat(self.path).st_mtime_ns
        except OSError:
            self.by_hash, self.mtime = {}, None
            return
        if m == self.mtime:
            return
        try:
            with open(self.path) as fh:
                rows = json.load(fh).get("tokens", [])
        except (OSError, ValueError):
            rows = []
        self.by_hash = {r["sha256"]: r for r in rows if r.get("sha256") and r.get("org")}
        self.mtime = m

    def check(self, token: str) -> dict | None:
        with self.lock:
            self._load()
            return self.by_hash.get(hashlib.sha256(token.encode()).hexdigest())

    @staticmethod
    def add(path: str, org: str, write: bool = True, label: str = "") -> str:
        token = "fxc_" + secrets.token_urlsafe(32)
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {"tokens": []}
        data["tokens"].append({"sha256": hashlib.sha256(token.encode()).hexdigest(), "org": org,
                               "write": bool(write), "label": label, "created": int(time.time())})
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
        return token


class Store:
    """SQLite: blobs (org, id) -> zlib(canonical JSON); keys and runs logs. Insert-only."""

    def __init__(self, path: str):
        self.path = path
        self.local = threading.local()
        db = self.db()
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS blobs (org TEXT NOT NULL, id TEXT NOT NULL, kind TEXT, size INTEGER,
                data BLOB NOT NULL, at REAL NOT NULL, PRIMARY KEY (org, id));
            CREATE TABLE IF NOT EXISTS keys (seq INTEGER PRIMARY KEY AUTOINCREMENT, org TEXT NOT NULL,
                ns TEXT NOT NULL, key TEXT NOT NULL, doc TEXT NOT NULL, run TEXT, at REAL NOT NULL,
                UNIQUE (org, ns, key, doc));
            CREATE INDEX IF NOT EXISTS keys_lookup ON keys (org, ns, key, seq);
            CREATE TABLE IF NOT EXISTS runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, org TEXT NOT NULL,
                ns TEXT NOT NULL, run TEXT NOT NULL, receipts TEXT, summary TEXT, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS untrusted (seq INTEGER PRIMARY KEY AUTOINCREMENT, org TEXT NOT NULL,
                ns TEXT NOT NULL, proof_key TEXT NOT NULL, nodeid TEXT, run TEXT, reason TEXT, label TEXT,
                keys_seq INTEGER NOT NULL, at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS untrusted_key ON untrusted (org, ns, proof_key, keys_seq);
            CREATE TRIGGER IF NOT EXISTS untrusted_append_only_u BEFORE UPDATE ON untrusted
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS untrusted_append_only_d BEFORE DELETE ON untrusted
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS blobs_append_only_u BEFORE UPDATE ON blobs
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS blobs_append_only_d BEFORE DELETE ON blobs
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS keys_append_only_u BEFORE UPDATE ON keys
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS keys_append_only_d BEFORE DELETE ON keys
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS runs_append_only_u BEFORE UPDATE ON runs
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS runs_append_only_d BEFORE DELETE ON runs
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)
        # the proof key of each key row (stores created before the audit have none: the client still checks them)
        if "proof_key" not in {r[1] for r in db.execute("PRAGMA table_info(keys)")}:
            db.execute("ALTER TABLE keys ADD COLUMN proof_key TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS keys_proof ON keys (org, ns, proof_key)")
        db.commit()

    def db(self) -> sqlite3.Connection:
        c = getattr(self.local, "db", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=60)
            c.execute("PRAGMA synchronous=NORMAL")
            self.local.db = c
        return c

    def missing(self, org: str, ids: list[str]) -> list[str]:
        db, have = self.db(), set()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT id FROM blobs WHERE org=? AND id IN ({','.join('?' * len(chunk))})"
            have.update(r[0] for r in db.execute(q, [org, *chunk]))
        return [i for i in ids if i not in have]

    def put(self, org: str, docs: dict) -> tuple[int, int]:
        db, now, stored, existing = self.db(), time.time(), 0, 0
        rows = []
        for i, doc in docs.items():
            if not _valid_id(i):
                raise ValueError(f"bad id {i!r}")
            b = canonical(doc)
            if hashlib.sha256(b).hexdigest() != i:
                raise ValueError(f"content does not match its address {i}")
            kind = doc.get("kind") if isinstance(doc, dict) else None
            rows.append((org, i, kind, len(b), zlib.compress(b, 6), now))
        with db:
            for r in rows:
                cur = db.execute("INSERT OR IGNORE INTO blobs (org, id, kind, size, data, at) VALUES (?,?,?,?,?,?)", r)
                if cur.rowcount:
                    stored += 1
                else:
                    existing += 1
        return stored, existing

    def get(self, org: str, ids: list[str]) -> dict:
        db, out = self.db(), {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT id, data FROM blobs WHERE org=? AND id IN ({','.join('?' * len(chunk))})"
            for bid, data in db.execute(q, [org, *chunk]):
                out[bid] = json.loads(zlib.decompress(data))
        return out

    def add_keys(self, org: str, ns: str, rows: list[dict]) -> int:
        db, now, added = self.db(), time.time(), 0
        docs = [r["doc"] for r in rows]
        absent = set(self.missing(org, sorted(set(docs))))
        if absent:
            raise ValueError(f"{len(absent)} entry documents are not stored (upload them first)")
        # the proof key is read from the stored entry document itself, never taken from the request
        pk = {i: (d.get("proof_key") if isinstance(d, dict) and isinstance(d.get("proof_key"), str) else None)
              for i, d in self.get(org, sorted(set(docs))).items()}
        with db:
            for r in rows:
                cur = db.execute("INSERT OR IGNORE INTO keys (org, ns, key, doc, run, at, proof_key) "
                                 "VALUES (?,?,?,?,?,?,?)",
                                 (org, ns, r["key"], r["doc"], str(r.get("run") or ""), now, pk.get(r["doc"])))
                added += cur.rowcount
        return added

    def add_untrusted(self, org: str, ns: str, rows: list[dict], label: str = "") -> int:
        db, now, added = self.db(), time.time(), 0
        with db:
            # entries filed up to now under these keys are out of every later lookup
            top = db.execute("SELECT COALESCE(MAX(seq), 0) FROM keys").fetchone()[0]
            for r in rows:
                db.execute("INSERT INTO untrusted (org, ns, proof_key, nodeid, run, reason, label, keys_seq, at) "
                           "VALUES (?,?,?,?,?,?,?,?,?)",
                           (org, ns, r["proof_key"], str(r.get("nodeid") or "")[:2000], str(r.get("run") or "")[:200],
                            str(r.get("reason") or "")[:2000], label[:200], top, now))
                added += 1
        return added

    def untrusted(self, org: str, ns: str, limit: int = 1000, after: int | None = None) -> list[dict]:
        """Marks of a namespace: newest first, or, with ``after``, the marks after that sequence number oldest first
        (how clients follow the log: every machine applies each mark to its own mirror once)."""
        if after is None:
            q, args = "ORDER BY seq DESC LIMIT ?", (org, ns, limit)
        else:
            q, args = "AND seq > ? ORDER BY seq LIMIT ?", (org, ns, after, limit)
        rows = self.db().execute("SELECT seq, proof_key, nodeid, run, reason, at FROM untrusted WHERE org=? AND ns=? "
                                 + q, args).fetchall()
        return [{"seq": r[0], "proof_key": r[1], "nodeid": r[2], "run": r[3], "reason": r[4], "at": r[5]}
                for r in rows]

    def audit(self, org: str) -> dict:
        """Audit counts per namespace (project) and over all of them.

        ``checked`` and ``matched`` come from the run summaries, which only write tokens can file. ``wrong`` counts
        every wrong skip found by any token's job: the distinct (run, test) pairs of the summaries' ``wrong_ids`` and
        of the untrusted log (a pull-request job marks its wrong skips there, it cannot file a summary). A wrong skip
        known only from the log was checked by its job: it is added to ``checked`` (``checked_without_summary``), so
        the bound never counts fewer checks than wrong skips; the matched checks of those jobs are unknown, which
        makes the bound higher (conservative), never lower."""
        db = self.db()
        zero = {"runs": 0, "checked": 0, "matched": 0, "wrong": 0, "flaky_evidence": 0, "checked_without_summary": 0}
        per: dict[str, dict] = {}
        wrong_seen: dict[str, set] = {}
        for ns, run, summary in db.execute("SELECT ns, run, summary FROM runs WHERE org=? ORDER BY seq", (org,)):
            try:
                a = (json.loads(summary or "null") or {}).get("audit")
            except (ValueError, AttributeError):
                a = None
            if not isinstance(a, dict):
                continue
            p = per.setdefault(ns, dict(zero))
            seen = wrong_seen.setdefault(ns, set())
            p["runs"] += 1
            for k in ("checked", "matched", "flaky_evidence"):
                v = a.get(k)
                p[k] += v if isinstance(v, int) and v >= 0 else 0
            ids = [i for i in (a.get("wrong_ids") or []) if isinstance(i, str)]
            n = a.get("wrong")
            n = n if isinstance(n, int) and n >= 0 else 0
            seen.update((run, i) for i in ids)
            # wrong skips the summary counts but does not name (``wrong_ids`` is capped)
            seen.update((run, f"#{j}") for j in range(max(0, n - len(set(ids)))))
        for ns, run, nodeid in db.execute("SELECT ns, run, nodeid FROM untrusted WHERE org=? ORDER BY seq", (org,)):
            p = per.setdefault(ns, dict(zero))
            seen = wrong_seen.setdefault(ns, set())
            if (run, nodeid) not in seen:
                seen.add((run, nodeid))
                p["checked_without_summary"] += 1
        total = dict(zero)
        for ns, p in per.items():
            p["wrong"] = len(wrong_seen.get(ns, ()))
            p["checked"] += p["checked_without_summary"]
            for k in total:
                total[k] += p[k]
            p["upper_bound_95"] = upper_bound_95(p["checked"], p["wrong"])
        total["upper_bound_95"] = upper_bound_95(total["checked"], total["wrong"])
        return {"projects": per, "all": total,
                "counted": "checked, matched and flaky_evidence: run summaries (write tokens); wrong: every token's "
                           "jobs (summaries and the untrusted log); checked_without_summary: wrong skips known only "
                           "from the untrusted log, each counted as one check"}

    def lookup(self, org: str, ns: str, keys: list[str], limit: int) -> dict:
        db, out = self.db(), {}
        for k in keys:
            rows = db.execute("SELECT doc FROM keys k WHERE org=? AND ns=? AND key=? AND NOT EXISTS (SELECT 1 FROM "
                              "untrusted u WHERE u.org=k.org AND u.ns=k.ns AND u.proof_key=k.proof_key AND "
                              "u.keys_seq >= k.seq) ORDER BY seq DESC LIMIT ?", (org, ns, k, limit)).fetchall()
            if rows:
                out[k] = [r[0] for r in rows]
        return out

    def add_run(self, org: str, ns: str, run: str, receipts: str | None, summary) -> None:
        db = self.db()
        with db:
            db.execute("INSERT INTO runs (org, ns, run, receipts, summary, at) VALUES (?,?,?,?,?,?)",
                       (org, ns, run, receipts, json.dumps(summary), time.time()))

    def runs(self, org: str, ns: str, limit: int = 100) -> list[dict]:
        rows = self.db().execute("SELECT run, receipts, summary, at FROM runs WHERE org=? AND ns=? ORDER BY seq DESC "
                                 "LIMIT ?", (org, ns, limit)).fetchall()
        return [{"run": r[0], "receipts": r[1], "summary": json.loads(r[2] or "null"), "at": r[3]} for r in rows]

    def stats(self, org: str) -> dict:
        db = self.db()
        blobs = dict(db.execute("SELECT COALESCE(kind,'?'), COUNT(*) FROM blobs WHERE org=? GROUP BY kind", (org,))
                     .fetchall())
        size = db.execute("SELECT COALESCE(SUM(size),0), COALESCE(SUM(LENGTH(data)),0) FROM blobs WHERE org=?",
                          (org,)).fetchone()
        nkeys = db.execute("SELECT COUNT(*) FROM keys WHERE org=?", (org,)).fetchone()[0]
        nruns = db.execute("SELECT COUNT(*) FROM runs WHERE org=?", (org,)).fetchone()[0]
        return {"blobs": blobs, "bytes": size[0], "stored_bytes": size[1], "keys": nkeys, "runs": nruns}


# ---------------------------------------------------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "fenvix-cache/1"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> "Service":
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # one short line per request on stderr, no headers (tokens)
        if not self.app.quiet:
            sys.stderr.write(f"[cache] {self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 1024
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, msg: str) -> None:
        self._send(code, {"error": msg})

    def _auth(self, write: bool) -> dict | None:
        h = self.headers.get("Authorization") or ""
        if not h.startswith("Bearer "):
            self._error(HTTPStatus.UNAUTHORIZED, "missing bearer token")
            return None
        t = self.app.tokens.check(h[7:].strip())
        if t is None:
            self._error(HTTPStatus.UNAUTHORIZED, "unknown token")
            return None
        if write and not t.get("write", True):
            self._error(HTTPStatus.FORBIDDEN, "read-only token")
            return None
        return t

    def _body(self):
        """The JSON body, read only after the token was checked. Compressed bodies are inflated in bounded steps:
        anything that would exceed MAX_BODY is refused while it streams (no gzip bomb)."""
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n else b""
        if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            out = bytearray(d.decompress(raw, MAX_BODY + 1))
            while len(out) <= MAX_BODY and d.unconsumed_tail:
                out += d.decompress(d.unconsumed_tail, MAX_BODY + 1 - len(out))
            if len(out) > MAX_BODY:
                raise ValueError("body too large")
            if not d.eof:
                raise ValueError("truncated gzip body")
            raw = bytes(out)
        return json.loads(raw or b"{}")

    def _route(self):
        parts = [urllib.parse.unquote(p) for p in self.path.split("?")[0].strip("/").split("/")]
        if not parts or parts[0] != API:
            return None, None
        if len(parts) >= 3 and parts[1] == "ns":
            return "ns:" + parts[-1], "/".join(parts[2:-1])
        return "/".join(parts[1:]), None

    def do_GET(self):
        route, ns = self._route()
        if route == "health":
            return self._send(200, {"ok": True, "api": API})
        tok = self._auth(write=False)
        if tok is None:
            return
        if route == "stats":
            return self._send(200, self.app.store.stats(tok["org"]))
        if route == "ns:runs" and ns and _valid_ns(ns):
            return self._send(200, {"runs": self.app.store.runs(tok["org"], ns)})
        if route == "ns:untrusted" and ns and _valid_ns(ns):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                after = int(q["after"][0]) if "after" in q else None
                limit = max(1, min(int(q.get("limit", ["1000"])[0]), 10_000))
            except ValueError:
                return self._error(400, "bad after or limit")
            return self._send(200, {"untrusted": self.app.store.untrusted(tok["org"], ns, limit, after)})
        if route == "audit":
            return self._send(200, self.app.store.audit(tok["org"]))
        self._error(404, "not found")

    def do_POST(self):
        route, ns = self._route()
        writes = route in ("blobs/put", "ns:keys", "ns:runs")
        tok = self._auth(write=writes)  # before the body is read: an unknown caller costs a header parse, nothing more
        if tok is None:
            self.close_connection = True  # the unread body must not be taken for the next request
            return
        try:
            body = self._body()
        except (ValueError, OSError, EOFError, zlib.error) as e:
            self.close_connection = True
            return self._error(400, f"bad body: {e}")
        org, st = tok["org"], self.app.store
        if ns is not None and not _valid_ns(ns):
            return self._error(400, "bad namespace")
        try:
            if route == "blobs/missing":
                ids = body.get("ids", [])
                if len(ids) > MAX_IDS or not all(_valid_id(i) for i in ids):
                    return self._error(400, "bad ids")
                return self._send(200, {"missing": st.missing(org, ids)})
            if route == "blobs/put":
                docs = body.get("docs", {})
                if not isinstance(docs, dict) or len(docs) > MAX_IDS:
                    return self._error(400, "bad docs")
                s, e = st.put(org, docs)
                return self._send(200, {"stored": s, "existing": e})
            if route == "blobs/get":
                ids = body.get("ids", [])
                if len(ids) > MAX_IDS or not all(_valid_id(i) for i in ids):
                    return self._error(400, "bad ids")
                got = st.get(org, ids)
                return self._send(200, {"docs": got, "missing": [i for i in ids if i not in got]})
            if route == "ns:keys":
                rows = body.get("put", [])
                if len(rows) > MAX_IDS or not all(isinstance(r, dict) and isinstance(r.get("key"), str)
                                                  and 0 < len(r["key"]) <= 128 and _valid_id(r.get("doc"))
                                                  for r in rows):
                    return self._error(400, "bad keys")
                return self._send(200, {"added": st.add_keys(org, ns, rows)})
            if route == "ns:lookup":
                keys = body.get("keys", [])
                limit = max(1, min(int(body.get("limit", 3)), 16))
                if len(keys) > MAX_IDS or not all(isinstance(k, str) and 0 < len(k) <= 128 for k in keys):
                    return self._error(400, "bad keys")
                return self._send(200, {"found": st.lookup(org, ns, keys, limit)})
            if route == "ns:untrusted":
                rows = body.get("put", [])
                if not isinstance(rows, list) or len(rows) > 10_000 or not all(
                        isinstance(r, dict) and isinstance(r.get("proof_key"), str) and 0 < len(r["proof_key"]) <= 128
                        for r in rows):
                    return self._error(400, "bad untrusted keys")
                return self._send(200, {"added": st.add_untrusted(org, ns, rows, str(tok.get("label") or ""))})
            if route == "ns:runs":
                run = body.get("run")
                rec = body.get("receipts")
                if not isinstance(run, str) or not run or (rec is not None and not _valid_id(rec)):
                    return self._error(400, "bad run")
                if rec is not None and st.missing(org, [rec]):
                    return self._error(400, "receipts blob not stored")
                st.add_run(org, ns, run, rec, body.get("summary"))
                return self._send(200, {"ok": True})
        except ValueError as e:
            return self._error(400, str(e))
        except sqlite3.Error as e:
            return self._error(503, f"store: {e}")
        self._error(404, "not found")

    def do_PUT(self):
        self._error(405, "append-only: use POST /v1/blobs/put")

    def do_DELETE(self):
        self._error(405, "append-only: nothing can be deleted through the API")


class Service:
    def __init__(self, data: str, host: str = "127.0.0.1", port: int = 8787, quiet: bool = False):
        os.makedirs(data, exist_ok=True)
        self.data = data
        self.tokens = Tokens(os.path.join(data, "tokens.json"))
        self.store = Store(os.path.join(data, "cache.sqlite3"))
        self.quiet = quiet
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = self  # type: ignore[attr-defined]

    @property
    def url(self) -> str:
        h, p = self.httpd.server_address[:2]
        return f"http://{h}:{p}"

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, daemon=True)
        t.start()
        return t

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m detpy.cache_service")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the service")
    s.add_argument("--data", required=True, help="data directory (cache.sqlite3, tokens.json)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--quiet", action="store_true")
    t = sub.add_parser("token", help="create a token for an organization (printed once; only its hash is kept)")
    t.add_argument("--data", required=True)
    t.add_argument("--org", required=True)
    t.add_argument("--read-only", action="store_true")
    t.add_argument("--label", default="")
    a = p.parse_args(argv)
    if a.cmd == "token":
        os.makedirs(a.data, exist_ok=True)
        print(Tokens.add(os.path.join(a.data, "tokens.json"), a.org, not a.read_only, a.label))
        return 0
    svc = Service(a.data, a.host, a.port, a.quiet)
    print(f"fenvix cache service on {svc.url} (data {a.data})", flush=True)
    try:
        svc.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
