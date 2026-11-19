"""Reference implementations: the Python code paths that rust-hotpaths moved to Rust, kept verbatim (only
``self`` renamed and the store passed in) so equivalence tests can run old and new on the same inputs.

* ``record_reference``: ``ProofCachePlugin._record_all`` before the per-test assembly moved to
  ``detpy_core::record`` (children are collected by the caller, as the new path does);
* ``ScanSocketsRef``: ``Capture._scan_sockets`` before ``_core.SocketScan``.
"""

from __future__ import annotations

import json
import os

from detpy import _core, _state
from _ref_pc_helpers import _GLOBAL_CTX, _ctx_file, _encodable, _final, _module_of, _uncacheable  # (were in detpy.proofcache)


def record_reference(self, store) -> None:
    """Old ``_record_all`` body with ``store`` as the plugin's store (``self.store`` is swapped by the caller)."""
    cap = self.cap
    if cap.rec is None:
        return
    fcache: dict[str, int | None] = {}
    rels = cap.fnames
    # file facts for every executed or loaded repository file (new versions parsed in parallel)
    needed = set(rels) | {r for r, _ in cap.loaded_order} | cap.preloaded
    self._prefetch_facts(sorted(needed), fcache)
    for rel in needed:
        self._facts_index(rel, fcache)
    ranges = []
    for rel in rels:
        ix = fcache.get(rel)
        if ix is None:
            ranges.append([])
        else:
            ranges.append([(a, b) for _, a, b, _ in store.file_facts(ix)[4]])
    per, imp = cap.rec.fold(len(cap.ctx_names), cap.segs, ranges)
    names = cap.ctx_names
    ctx_of = {n: i for i, n in enumerate(names)}

    def units_of(fids_units):
        out = set()
        for v in fids_units:
            fid, u = v >> 32, v & 0xFFFFFFFF
            ix = fcache.get(rels[fid])
            if ix is not None:
                out.add((ix, u))
        return out

    def unparsable(fids):
        out = set()
        for fid in fids:
            ix = fcache.get(rels[fid])
            if ix is None or not store.file_facts(ix)[4]:
                if ix is not None:
                    f = store.file_facts(ix)
                    if f[2] == f[1]:  # not Python: whole content
                        out.add(ix)
        return out

    conftests = {r for r in needed if r.rsplit("/", 1)[-1] == "conftest.py"}
    test_files = {_ctx_file(n) for n in self.items}
    # import graph: test modules imported by any loaded module are shared, others only serve their own tests
    imported_names = set()
    for rel in needed:
        ix = fcache.get(rel)
        if ix is not None:
            imported_names.update(store.file_facts(ix)[5])
    shared_test_files = set()
    for tf in test_files:
        mod, _ = _module_of(os.path.join(self.root, tf))
        if mod and (mod in imported_names or mod.rsplit(".", 1)[-1] in imported_names):
            shared_test_files.add(tf)

    # global contexts: startup, between tests, import time
    g_ctx = [ctx_of[c] for c in _GLOBAL_CTX if c in ctx_of]
    g_units = units_of(imp[0])
    g_unparsable = unparsable(imp[1])
    for c in g_ctx:
        g_units |= units_of(per[c][0])
        g_unparsable |= unparsable(per[c][1])
    # import-time reads of a test module that no other module imports serve only its own tests
    own_import = {tf: ctx_of["i|" + tf] for tf in test_files - shared_test_files if "i|" + tf in ctx_of}
    own_import_ix = set(own_import.values())
    g_ctx_all = g_ctx + [cap.import_ctx] + [i for n, i in ctx_of.items()
                                            if n.startswith("i|") and i not in own_import_ix]
    g_data, g_env, g_flags = {}, set(), set()
    for c in g_ctx_all:
        # review R-023: /proc, /sys, /dev reads of code that runs for every test are not data inputs (as their flag)
        _merge_data(g_data, cap.data.get(c, {}))  # review R-023b N1
        g_env |= cap.env.get(c, set())
        g_flags |= {f for f in cap.flags.get(c, set()) if f != "pstate"}

    pre_ix = {fcache[r] for r in cap.preloaded if fcache.get(r) is not None}
    names_of = cap.ctx_names
    session_written = {cap._key(p): sorted(names_of[c] for c in w) for p, w in cap.writers.items()
                       if _encodable(p)}
    written = {p: set(w) for p, w in store.written().items()}
    for p, w in session_written.items():
        written.setdefault(p, set()).update(w)
    # persisted for the next sessions: paths in the repository only (temporary files have fresh names)
    store.add_written({p: w for p, w in session_written.items() if not os.path.isabs(p)})
    # results reused in this session whose input files code of this session then wrote: drop them
    for nid in self.hits:
        if not session_written:
            break
        try:
            deps = json.loads(store.entry(nid)).get("data", [])
        except KeyError:
            continue
        own = {"t|" + nid}
        for path, _dep in deps:
            if path in session_written and not set(session_written[path]) <= own:
                self.stale_hits[nid] = path
                store.remove(nid)
                break
    loaded_idx = cap.loaded_order  # (rel, index)
    cfg = _state.STATE.config
    file_of_ix = {}
    for rel, ix in fcache.items():
        if ix is not None:
            file_of_ix[ix] = rel

    def in_scope(rel: str, own: str) -> bool:
        if rel in test_files:
            return rel == own or rel in shared_test_files
        if rel in conftests:
            d = rel.rsplit("/", 1)[0] if "/" in rel else ""
            return d == "" or own == d or own.startswith(d + "/")
        return True

    # review R-020 H1/O1 (prefix rule; claude/dep-verdict-abjcfw): everything a context that ran before a test in
    # this process depended on is an input of that test (contexts in order of first activation; a test module's own
    # import context at the collection of its file)
    first: dict = {}
    for k, (_t, c) in enumerate(cap.timeline):
        first.setdefault(c, k)
    g_set = set(g_ctx_all)
    for n, i in ctx_of.items():
        if n.startswith("i|") and i in own_import_ix:
            first.setdefault(i, first.get(ctx_of.get("c|" + n[2:]), 0))
    carry_order = sorted((k, c) for c, k in first.items() if c not in g_set)
    def files_of(c):
        if c >= len(per):
            return set()
        return {v >> 32 for v in per[c][0]} | {int(v) for v in per[c][1]}

    fixtures_of: dict = {}
    for n in self.ran:
        tc = ctx_of.get("t|" + n)
        if tc is not None:
            fixtures_of[tc] = [ctx_of[f] for f in self.fixture_ctx.get(n, []) if f in ctx_of]
    by_file: dict = {}
    no_code: list = []
    for k, c in carry_order:
        fs = files_of(c)
        if not fs and (cap.data.get(c) or cap.env.get(c) or cap.flags.get(c)):
            no_code.append((k, c))
        for f in fs:
            by_file.setdefault(f, []).append((k, c))
    c_data: dict = {}
    c_env: set = set()
    c_flags: set = set()
    c_units: set = set()
    c_content: set = set()
    c_ctxs: list = []
    last_sel = None
    for nid in self.ran:
        item = self.items.get(nid)
        if item is None:
            continue
        tpos = first.get(ctx_of.get("t|" + nid), len(cap.timeline) + 1)
        own = _ctx_file(nid)
        own_ctxs = [ctx_of[c] for c in ["t|" + nid, "c|" + own, *self.fixture_ctx.get(nid, [])] if c in ctx_of]
        if own in own_import:
            own_ctxs.append(own_import[own])
        # parallel-proof round 3, carried-set rule: only earlier contexts connected to the test through shared
        # executed repository files (closure), plus earlier contexts that ran no repository code
        reach = set()
        queue = []
        for c in own_ctxs:
            for f in files_of(c):
                if f not in reach:
                    reach.add(f)
                    queue.append(f)
        sel = set()
        while queue:
            f = queue.pop()
            for k, c in by_file.get(f, ()):
                if k >= tpos or c in own_ctxs or (k, c) in sel:
                    continue
                sel.add((k, c))
                group = [c]
                for fc in fixtures_of.get(c, ()):  # an earlier test comes with its wider-scoped fixtures
                    fk = first.get(fc)
                    if fk is not None and fk < tpos and fc not in own_ctxs and fc not in g_set and (fk, fc) not in sel:
                        sel.add((fk, fc))
                        group.append(fc)
                for g in group:
                    for f2 in files_of(g):
                        if f2 not in reach:
                            reach.add(f2)
                            queue.append(f2)
        for k, c in no_code:
            if k < tpos and c not in own_ctxs:
                sel.add((k, c))
        if sel != last_sel:
            c_data, c_env, c_flags, c_units, c_content, c_ctxs = {}, set(), set(), set(), set(), []
            for _k, c in sorted(sel):
                c_ctxs.append(c)
                _merge_data(c_data, cap.data.get(c, {}))
                c_env |= cap.env.get(c, set())
                c_flags |= cap.flags.get(c, set())
                if c < len(per):
                    c_units |= units_of(per[c][0])
                    c_content |= unparsable(per[c][1])
            last_sel = sel
        p = self.parts.get(nid, {})
        outcome = _final(p)
        if outcome not in ("passed", "skipped", "xfailed"):
            self._not_cached(nid, f"outcome {outcome}")
            continue
        own = _ctx_file(nid)
        ctxs = [ctx_of[c] for c in ["t|" + nid, "c|" + own, *self.fixture_ctx.get(nid, [])] if c in ctx_of]
        if own in own_import:
            ctxs.append(own_import[own])
        flags = set(g_flags)
        data = dict(g_data)
        _merge_data(data, c_data)
        env = set(g_env) | c_env
        units = set(c_units)
        content = set(pre_ix) | g_unparsable | c_content
        for c in ctxs:
            flags |= cap.flags.get(c, set())
            _merge_data(data, cap.data.get(c, {}))
            env |= cap.env.get(c, set())
            units |= units_of(per[c][0])
            content |= unparsable(per[c][1])
        why = _uncacheable(flags, cfg)
        own_flags = set(flags)
        if why is not None:
            self.not_cached_where[nid] = self._where(why, g_ctx_all + ctxs)
        elif c_flags:
            why = _uncacheable(c_flags, cfg)
            if why is not None:
                self.not_cached_where[nid] = self._where(why, c_ctxs)
                why = f"after an earlier test or fixture of this process: {why}"
            else:
                flags |= c_flags
        if why is None:
            # writers credited to the test: its own contexts and the global ones (startup, between tests,
            # import time), whose code is an input of every test
            credited = set(ctxs) | set(g_ctx_all)
            names = {names_of[c] for c in credited}
            carried_credit = credited | set(c_ctxs)
            for f in sorted(flags):
                if f.startswith("rw:") and not cap.writers.get(f[3:], set()) <= (
                        credited if f in own_flags else carried_credit):
                    why = f"reads a file another test or fixture wrote: {cap._key(f[3:])}"
                    break
            if why is None:
                own_reads = lambda path: path in g_data or any(path in cap.data.get(c, ()) for c in ctxs)  # noqa: E731
                for path in data:
                    if path in c_data and c_data[path] == data[path] and not own_reads(path):
                        continue
                    w = written.get(path)
                    if w and not w <= names:
                        why = f"reads a file another test or fixture wrote: {path}"
                        break
        # parallel-proof round 3, item 9: pytest's conftest.py / __init__.py lookups from the root to the test's file
        for rel in _core.collection_candidates(os.path.dirname(own)):
            if rel not in data:
                data[rel] = "s:" + _core.stat_kind(os.path.join(cap.root_sep, rel))
        if why is None and "net-replay" in flags and cfg.cassette_path:
            d = _core.file_digest(cfg.cassette_path)
            data[cap._key(os.path.realpath(cfg.cassette_path))] = f"f:{d}" if d else "missing"
        if why:
            self._not_cached(nid, why)
            continue
        idx = self.test_index.get(nid, 0)
        skeleton, hooks = set(), set()
        for rel, seen_at in loaded_idx:
            if seen_at > idx:
                continue
            ix = fcache.get(rel)
            if ix is None:
                continue
            if rel in conftests:
                hooks.add(ix)
            if in_scope(rel, own):
                skeleton.add(ix)
        for ix, u in g_units:
            rel = file_of_ix.get(ix)
            # hooks run outside tests can act on any test; test modules serve their own tests
            if rel is not None and (rel in conftests or in_scope(rel, own)):
                units.add((ix, u))
        if type(item).__name__ == "DoctestItem" or not hasattr(item, "obj"):
            ix = fcache.get(own)
            if ix is None:
                ix = self._facts_index(own, fcache)
            if ix is not None:
                content.add(ix)
        epoch = self.epoch if ("time" in flags and "time" in cfg.controls) else None
        if "time" in flags and "time" not in cfg.controls:
            self._not_cached(nid, "real clock")
            continue
        env_deps = []
        for name in sorted(n for n in env if _encodable(n)):
            if name == "*":
                env_deps.append(("*", _core.env_all_digest(dict(cap.env0))))
            else:
                env_deps.append((name, _core.env_value_digest(cap.env0.get(name))))  # env0 is sanitised
        report = {w: p[w] for w in ("setup", "call") if w in p}
        store.record(nid, outcome, json.dumps(report), self.fingerprints.get(nid, ""), self.dur.get(nid, 0.0),
                     self.run_id, self.config_digest, self.runtime_digest, epoch, env_deps,
                     _core.compact_stats(sorted(data.items()), cap.root_sep.rstrip("/"), 8), sorted(content),
                     sorted(skeleton), sorted(hooks), sorted(units))
        self.recorded += 1
    store.save()



class ScanSocketsRef:
    """Old ``Capture._scan_sockets`` state machine: ``scan()`` returns whether the old code would flag "csock"."""

    def __init__(self):
        self._socks = None
        self.flagged = False

    def flag(self, ctx, flag, detail=None):
        self.flagged = True

    def scan(self) -> bool:
        self.flagged = False
        self._scan_sockets(0)
        return self.flagged

    def _scan_sockets(self, ctx):
        try:
            fds = os.listdir("/proc/self/fd")
        except OSError:
            return
        cur = {}
        for fd in fds:
            try:
                link = os.readlink("/proc/self/fd/" + fd)
            except OSError:
                continue
            if link.startswith("socket:["):
                cur[fd] = link[8:-1]
        prev, self._socks = self._socks, cur
        if prev is None:
            return
        new = {ino for fd, ino in cur.items() if prev.get(fd) != ino}
        if not new:
            return
        inet = set()
        for t in ("tcp", "tcp6", "udp", "udp6"):
            try:
                with open("/proc/self/net/" + t, "rb") as fh:
                    next(fh, None)
                    for line in fh:
                        parts = line.split()
                        if len(parts) > 9:
                            inet.add(parts[9].decode())
            except OSError:
                continue
        if ctx is not None and new & inet:
            self.flag(ctx, "csock", "an internet socket left open")


def _merge_data(into: dict, new: dict) -> None:
    """dict.update, except that a kind check ("s:...") never replaces a content or listing dependency."""
    for k, v in new.items():
        old = into.get(k)
        kind = lambda d: d.startswith(("s:", "l:"))  # noqa: E731
        if old is not None and kind(v) and not kind(old):
            continue
        into[k] = v
