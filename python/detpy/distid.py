"""Per-distribution identity for ``--det-cache`` (PROTOTYPE, behind ``--det-cache-dists``).

Without the flag the installed distributions enter the cache key as one digest per run (``runtime_identity``):
any version bump invalidates every recorded result. With the flag the run-level runtime identity leaves the
distributions out, and every test instead depends on the distributions it actually used:

* the distributions whose modules (Python or native) were loaded before or during the test, in the process
  (``sys.modules`` and ``/proc/self/maps``; a module loaded by an earlier test stays loaded, so it counts for
  every later test, the same rule the cache applies to repository modules);
* the distributions whose files the test (or a process it started) read;
* the answers of the metadata queries it made: ``importlib.metadata`` by name (one distribution), by entry-point
  group (that group across all distributions) or a full scan (every distribution);
* the top-level module names it looked up (found or not): which distributions provide that name.

Each of these is a small identity file under ``<cache>/dist-identity/``, rewritten from the current environment at
the start of every session; a test records the content digest of the files it depends on as ordinary data
dependencies, so the Rust checker needs no change. A read under ``site-packages`` that maps to no distribution
falls back to the identity of the whole environment (``@all``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading

ALL = "@all"
PROJECT = ""  # owner of the files of the project's own (editable) install
EP_ALL = "e/@all"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _fname(s: str) -> str:
    return s if _SAFE.match(s) and s not in (".", "..") else "h-" + hashlib.sha1(s.encode()).hexdigest()[:20]


def _top_of(rel: str) -> str | None:
    """Top-level module name a RECORD path provides (None for metadata, scripts, data)."""
    if rel.startswith("..") or rel.startswith("/"):
        return None
    first = rel.split("/", 1)[0]
    if first.endswith((".dist-info", ".egg-info", ".data")) or first == "__pycache__":
        return None
    if "/" in rel:
        return first if first.isidentifier() else None
    if first.endswith(".py"):
        n = first[:-3]
        return n if n.isidentifier() else None
    if first.endswith((".so", ".pyd")):
        n = first.split(".", 1)[0]
        return n if n.isidentifier() else None
    return None


class Index:
    """The installed distributions of this interpreter: identity per distribution, file -> distribution,
    top-level module name -> distributions, entry points per group."""

    def __init__(self, project_root: str):
        self.root_sep = os.path.realpath(project_root) + os.sep
        self.ident: dict[str, str] = {}       # normalised name -> "name==version\nRECORD digest"
        self.files: dict[str, str] = {}       # absolute real path -> normalised name
        self.dirs: dict[str, str | None] = {}  # top directory under a site dir -> name (None when shared)
        self.tops: dict[str, set] = {}        # top-level module name -> names
        self.groups: dict[str, list] = {}     # entry-point group -> sorted lines
        self.unmapped = 0
        self.build()

    def build(self) -> None:
        from importlib import metadata

        seen = set()
        for d in metadata.distributions():
            path = getattr(d, "_path", None)
            try:
                name = (d.metadata.get("Name") or "") if d.metadata is not None else ""
            except Exception:
                name = ""
            if not name:
                continue
            n = norm(name)
            if n in seen:
                continue  # shadowed by an earlier sys.path entry, as importlib.metadata resolves names
            seen.add(n)
            project = False
            try:
                du = d.read_text("direct_url.json")
                if du:
                    url = json.loads(du).get("url", "")
                    if url.startswith("file://") and (os.path.realpath(url[7:]) + os.sep).startswith(self.root_sep):
                        project = True
            except Exception:
                pass
            try:
                rec = d.read_text("RECORD") or ""
            except Exception:
                rec = ""
            h = hashlib.sha256(rec.encode()).hexdigest()[:24]
            if not project:
                self.ident[n] = f"{name}=={d.version}\n{h}\n"
            owner = PROJECT if project else n
            base = os.path.realpath(str(d.locate_file(""))) if path is not None else None
            if project and path is not None:
                self.files[os.path.realpath(str(path))] = PROJECT
                self.dirs[os.path.realpath(str(path))] = PROJECT
            for line in rec.splitlines():
                rel = line.rsplit(",", 2)[0] if line.count(",") >= 2 else line.split(",", 1)[0]
                if not rel or base is None:
                    continue
                ap = os.path.realpath(os.path.join(base, rel)) if ".." in rel else os.path.join(base, rel)
                self.files[ap] = owner
                if project:
                    continue
                if "/" in rel and not rel.startswith(".."):
                    top_dir = os.path.join(base, rel.split("/", 1)[0])
                    prev = self.dirs.get(top_dir, n)
                    self.dirs[top_dir] = n if prev == n else None
                t = _top_of(rel)
                if t:
                    self.tops.setdefault(t, set()).add(n)
            try:
                eps = d.entry_points
            except Exception:
                eps = ()
            for ep in eps:
                self.groups.setdefault(ep.group, []).append(f"{n}:{ep.name}={ep.value}")
        for g in self.groups.values():
            g.sort()

    def dist_of(self, path: str) -> str | None:
        """Distribution owning ``path`` (absolute) or None."""
        n = self.files.get(path)
        if n is not None:
            return n
        rp = os.path.realpath(path)
        n = self.files.get(rp)
        if n is not None:
            return n
        # bytecode caches of a recorded source file
        d, f = os.path.split(rp)
        if os.path.basename(d) == "__pycache__":
            src = os.path.join(os.path.dirname(d), f.split(".", 1)[0] + ".py")
            n = self.files.get(src)
            if n is not None:
                return n
        # a file under a top-level directory that only one distribution installs
        p = rp
        while True:
            parent = os.path.dirname(p)
            if parent == p:
                return None
            if p in self.dirs:
                return self.dirs[p]
            p = parent

    def write(self, out_dir: str) -> None:
        """Rewrite the identity files under ``out_dir`` (atomically per file; stale files removed)."""
        want: dict[str, str] = {}
        for n, s in self.ident.items():
            want[f"d/{_fname(n)}"] = s
        for g, lines in self.groups.items():
            want[f"e/{_fname(g)}"] = "\n".join(lines) + "\n"
        want[EP_ALL] = hashlib.sha256("\n".join(f"{g}\n{chr(10).join(v)}" for g, v in sorted(self.groups.items()))
                                      .encode()).hexdigest() + "\n"
        for t, ns in self.tops.items():
            want[f"m/{_fname(t)}"] = "\n".join(sorted(ns)) + "\n"
        want[ALL] = hashlib.sha256("".join(v for _, v in sorted(self.ident.items())).encode()).hexdigest() + "\n"
        for sub in ("d", "e", "m"):
            os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
        have = set()
        for sub in ("d", "e", "m"):
            for f in os.listdir(os.path.join(out_dir, sub)):
                if ".tmp" not in f:
                    have.add(f"{sub}/{f}")
        if os.path.exists(os.path.join(out_dir, ALL)):
            have.add(ALL)
        for rel in have - set(want):
            try:
                os.unlink(os.path.join(out_dir, rel))
            except OSError:
                pass
        for rel, content in want.items():
            p = os.path.join(out_dir, rel)
            try:
                with open(p) as fh:
                    if fh.read() == content:
                        continue
            except OSError:
                pass
            tmp = f"{p}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                fh.write(content)
            os.replace(tmp, p)


_DETPY_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _by_user(depth: int) -> bool:
    """Whether the first frame above ``depth`` that is not the standard library or the import system belongs to
    user code (the tests, the project, its installed dependencies) rather than pytest, pluggy or detpy."""
    from . import _sites

    try:
        f = sys._getframe(depth + 1)
    except ValueError:
        return True
    while f is not None:
        fn = f.f_code.co_filename
        if fn.startswith(_DETPY_DIR):
            return False
        kind, _ = _sites._classify(fn)
        if kind == _sites._USER:
            return True
        if kind == _sites._INFRA:
            return False
        f = f.f_back
    return True


class Tracker:
    """Collects, per capture context, the identity files each context depends on."""

    def __init__(self, cap, index: Index, ident_dir: str):
        self.cap = cap
        self.index = index
        self.dir = ident_dir
        self.deps: dict[int, set] = {}            # context -> identity keys ("d/x", "e/g", "m/t", "@all")
        self.loaded: list[tuple[str, int]] = []   # (identity key, index of the test after which it was seen)
        self._loaded_seen: set = set()
        self._mod_files_seen: set = set()
        self._maps_seen: set = set()
        self._nmods = -1
        self._dlopen = False
        self.local = threading.local()
        self.unmapped: dict[str, int] = {}        # site-packages paths that map to no distribution
        self._saved: list = []
        self.site_dirs: tuple = ()
        self.index_seconds = 0.0

    # -- recording -------------------------------------------------------------------
    def suppressed(self) -> bool:
        return getattr(self.local, "depth", 0) > 0

    def add(self, ctx: int, key: str) -> None:
        self.deps.setdefault(ctx, set()).add(key)

    def in_site(self, p: str) -> bool:
        return any(p.startswith(d) for d in self.site_dirs)

    def path(self, ctx: int, p: str) -> None:
        """A read (file or listing) of ``p`` under a site directory, by the test process or a child."""
        if self.suppressed():
            return
        n = self.index.dist_of(p)
        if n == PROJECT:
            return  # the project's own editable install: repository files and its metadata are recorded as data
        if n is None:
            self.unmapped[p] = self.unmapped.get(p, 0) + 1
            if os.path.isdir(p):
                # a listing no RECORD explains (site-packages itself: pkg_resources' scan): every distribution's
                # presence is the input
                self.add(ctx, ALL)
            else:
                # a file no RECORD lists (_virtualenv.py, a .pth file, a file written after install): its content
                self.add(ctx, os.path.realpath(p))
            return
        self.add(ctx, "d/" + _fname(n))

    def _loaded_key(self, key: str, index: int) -> None:
        if key not in self._loaded_seen:
            self._loaded_seen.add(key)
            self.loaded.append((key, index))

    def scan(self, index: int) -> None:
        """Distributions of the modules and native libraries loaded so far (after the test at ``index``)."""
        mods = sys.modules
        if len(mods) != self._nmods:
            self._nmods = len(mods)
            for m in list(mods.values()):
                f = getattr(m, "__file__", None)
                if not isinstance(f, str) or f in self._mod_files_seen:
                    continue
                self._mod_files_seen.add(f)
                if not any(f.startswith(d) for d in self.site_dirs):
                    rf = os.path.realpath(f)
                    if not any(rf.startswith(d) for d in self.site_dirs):
                        continue
                n = self.index.dist_of(os.path.abspath(f))
                if n == PROJECT:
                    continue
                if n is None:
                    self.unmapped[f] = self.unmapped.get(f, 0) + 1
                    self._loaded_key(os.path.realpath(f), index)
                else:
                    self._loaded_key("d/" + _fname(n), index)
            self._dlopen = True  # an extension module may have loaded native libraries
        if self._dlopen:
            self._dlopen = False
            try:
                with open("/proc/self/maps") as fh:
                    lines = fh.read().splitlines()
            except OSError:
                lines = []
            for line in lines:
                i = line.find("/")
                if i < 0:
                    continue
                p = line[i:]
                if p in self._maps_seen:
                    continue
                self._maps_seen.add(p)
                if not any(p.startswith(d) for d in self.site_dirs):
                    continue
                n = self.index.dist_of(p)
                if n == PROJECT:
                    continue
                if n is None:
                    self.unmapped[p] = self.unmapped.get(p, 0) + 1
                    self._loaded_key(os.path.realpath(p), index)
                else:
                    self._loaded_key("d/" + _fname(n), index)

    # -- metadata queries ----------------------------------------------------------------
    def install(self) -> None:
        """Wrap importlib.metadata's query functions and add a module-name finder in front of sys.meta_path."""
        import importlib.metadata as md

        tracker = self

        def wrap(owner, attr, keyfn, classmethod_=False):
            orig = owner.__dict__.get(attr) if classmethod_ else getattr(owner, attr, None)
            if orig is None:
                return
            fn = orig.__func__ if classmethod_ else orig

            def wrapper(*args, **kwargs):
                cap = tracker.cap
                if cap.active and not tracker.suppressed() and _by_user(1):
                    try:
                        key = keyfn(args[1:] if classmethod_ else args, kwargs)
                    except Exception:
                        key = ALL
                    if key:
                        tracker.add(cap._cur(), key)
                tracker.local.depth = getattr(tracker.local, "depth", 0) + 1
                try:
                    return fn(*args, **kwargs)
                finally:
                    tracker.local.depth -= 1

            wrapper.__wrapped__ = fn
            wrapper.__name__ = getattr(fn, "__name__", attr)
            wrapper.__doc__ = getattr(fn, "__doc__", None)
            self._saved.append((owner, attr, orig))
            setattr(owner, attr, classmethod(wrapper) if classmethod_ else wrapper)

        def by_name(args, kwargs):
            name = args[0] if args else kwargs.get("distribution_name", kwargs.get("name"))
            return "d/" + _fname(norm(name)) if isinstance(name, str) else ALL

        def eps(args, kwargs):
            if set(kwargs) <= {"group", "name"} and isinstance(kwargs.get("group"), str):
                return "e/" + _fname(kwargs["group"])
            return EP_ALL

        def discover(args, kwargs):
            name = kwargs.get("name")
            if isinstance(name, str) and set(kwargs) <= {"name", "context"} and not args:
                return "d/" + _fname(norm(name))
            return ALL

        for attr in ("version", "distribution", "metadata", "files", "requires"):
            wrap(md, attr, by_name)
        wrap(md, "entry_points", eps)
        wrap(md, "distributions", discover)
        wrap(md, "packages_distributions", lambda a, k: ALL)
        wrap(md.Distribution, "from_name", by_name, classmethod_=True)
        wrap(md.Distribution, "discover", discover, classmethod_=True)

        class _NameFinder:
            """Records the top-level module names looked up; finds nothing itself."""

            @staticmethod
            def find_spec(fullname, path=None, target=None):
                cap = tracker.cap
                if path is None and "." not in fullname and cap.active and not tracker.suppressed() \
                        and _by_user(1):
                    tracker.add(cap._cur(), "m/" + _fname(fullname))
                return None

            @staticmethod
            def invalidate_caches():
                pass

        self._finder = _NameFinder
        sys.meta_path.insert(0, _NameFinder)

    def uninstall(self) -> None:
        for owner, attr, orig in reversed(self._saved):
            setattr(owner, attr, orig)
        self._saved = []
        f = getattr(self, "_finder", None)
        if f is not None and f in sys.meta_path:
            sys.meta_path.remove(f)

    # -- keys ---------------------------------------------------------------------------
    def data_deps(self, keys) -> dict[str, str]:
        """{absolute identity file path: dependency string} for identity keys."""
        from . import _core

        out = {}
        for k in keys:
            p = k if k.startswith("/") else os.path.join(self.dir, k)  # "/...": a file outside every RECORD
            d = _core.file_digest(p)
            out[p] = f"f:{d}" if d is not None else "missing"
        return out
