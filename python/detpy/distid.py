"""Per-distribution identity for ``--det-cache`` (PROTOTYPE, behind ``--det-cache-dists``).

Without the flag the installed distributions enter the cache key as one digest per run (``runtime_identity``):
any version bump invalidates every recorded result. With the flag the run-level runtime identity leaves the
distributions out, and every test instead depends on the distributions it actually used:

* the distributions whose modules (Python or native) were loaded before or during the test, in the process
  (``sys.modules`` and ``/proc/self/maps``; a module loaded by an earlier test stays loaded, so it counts for
  every later test, the same rule the cache applies to repository modules);
* the distributions whose files the test (or a process it started) read: *every* distribution whose RECORD lists
  the file (review R-020b N1: a file two distributions install changes when either is upgraded), plus the file's
  claim group (``c/`` keys: which distributions install files in its top-level directory, and which paths there
  several of them install), so a distribution that starts claiming the file invalidates too. Ownership comes from
  every RECORD path, inside or outside the site directory, and covers the libraries in ``/proc/self/maps`` wherever
  they are (review R-020b N2: a wheel's data scheme installs shared libraries into ``<prefix>/lib``). The file
  index is built in Rust (``detpy-core/src/distfiles.rs``);
* the answers of the metadata queries it made: ``importlib.metadata`` by name (one distribution), by entry-point
  group (that group across all distributions) or a full scan (every distribution);
* the top-level module names it looked up (found or not): which distributions provide that name;
* the directories under a site directory that it listed, or that the import system searched for a submodule
  it looked up (found or not): the listing itself (``l/`` keys, review R-020 H2: a namespace package or a
  shared directory gains a submodule from a distribution the test never loaded);
* the ``.pth`` files of the site directories, for every test (``@pth``, review R-020 H3: ``site.py`` runs them at
  startup, before anything is recorded);
* everything a test or fixture that ran before it in the same process depended on (``proofcache._record_all``,
  review R-020 H1: an answer memoised by an earlier test is used without an event).

Existence checks (``os.stat``, ``os.path.exists``, ``shutil.which``) of paths under a site directory are recorded
as the path's kind by ``proofcache`` (review R-020b N3), as for any other path.

Each of these is a small identity file under ``<cache>/dist-identity/``, rewritten from the current environment at
the start of every session. On the Rust capture, a context's dependency on one is recorded at once as an ordinary
data read of that file (``Tracker.add`` -> ``CaptureCore.read``), so the Rust record step (including the prefix
rule) and the checker need no change; the capture hands reads, listings and existence checks under a site directory
to ``Tracker.path`` (``CaptureCore.set_dist_read``). A read under ``site-packages`` that maps to no distribution
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
PTH = "@pth"
PROJECT = ""  # owner of the files of the project's own (editable) install
EP_ALL = "e/@all"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _fname(s: str) -> str:
    return s if _SAFE.match(s) and s not in (".", "..") else "h-" + hashlib.sha1(s.encode()).hexdigest()[:20]


def listing_key(path: str) -> str:
    """Identity key of the listing of a directory under a site directory."""
    return "l/" + _fname("dir:" + os.path.realpath(path))


def claim_key(group: str) -> str:
    """Identity key of a claim group (``distfiles.rs``): which distributions install files in it, and which of
    its paths several of them install."""
    return "c/" + _fname("claim:" + group)


def listing_content(path: str) -> str:
    """The path, then the sorted entry names (bytecode caches left out: the interpreter writes them, no installer
    does); a missing or unreadable directory is its own state."""
    try:
        names = sorted(n for n in os.listdir(path) if n != "__pycache__")
    except FileNotFoundError:
        return f"{path}\n<missing>\n"
    except NotADirectoryError:
        return f"{path}\n<not a directory>\n"
    except OSError as e:
        return f"{path}\n<error {e.errno}>\n"
    return path + "\n" + "".join(n + "\n" for n in names)


def pth_content(site_dirs) -> str:
    """Every .pth file of the site directories, in the order site.py runs them: name and content digest."""
    out = []
    for d in sorted({os.path.realpath(x) for x in site_dirs}):
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".pth"))
        except OSError:
            continue
        for n in names:
            try:
                with open(os.path.join(d, n), "rb") as fh:
                    h = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                h = "unreadable"
            out.append(f"{d}/{n} {h}\n")
    return "".join(out)


def _write_atomic(p: str, content: str) -> None:
    try:
        with open(p) as fh:
            if fh.read() == content:
                return
    except (OSError, UnicodeDecodeError):
        pass
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        fh.write(content)
    os.replace(tmp, p)


def _top_of(rel: str) -> str | None:
    """Top-level module name a RECORD path provides (None for metadata, scripts, data). Rust: distfiles.rs."""
    from . import _core

    return _core.dist_top_of(rel)


class Index:
    """The installed distributions of this interpreter: identity per distribution, file -> distribution,
    top-level module name -> distributions, entry points per group."""

    def __init__(self, project_root: str):
        self.root_sep = os.path.realpath(project_root) + os.sep
        self.ident: dict[str, str] = {}       # normalised name -> "name==version\nRECORD digest"
        self.tops: dict[str, set] = {}        # top-level module name -> names
        self.groups: dict[str, list] = {}     # entry-point group -> sorted lines
        self.unmapped = 0
        self.build()

    def build(self) -> None:
        from importlib import metadata

        from . import _core

        # file -> distributions, claim groups, top-level names: the RECORD of every distribution, every path it
        # installs (inside or outside the site directory), every claimant of a shared path (Rust: distfiles.rs)
        self.dist_files = df = _core.DistFiles()
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
            if path is not None:
                if project:
                    df.add_project_path(str(path))
                df.add(n, os.path.realpath(str(d.locate_file(""))), rec, project)
            try:
                eps = d.entry_points
            except Exception:
                eps = ()
            for ep in eps:
                self.groups.setdefault(ep.group, []).append(f"{n}:{ep.name}={ep.value}")
        for g in self.groups.values():
            g.sort()
        self.tops = {t: set(ns) for t, ns in df.tops()}

    def owners(self, path: str):
        """(owners, claim group) of ``path`` (absolute): every distribution whose RECORD lists it (review R-020b
        N1: a path several distributions install changes when any of them is upgraded) and the claim group whose
        identity file changes when a distribution starts claiming the path. None when no RECORD explains it;
        ``([PROJECT], None)`` for the project's own install."""
        return self.dist_files.lookup(path)

    def dist_of(self, path: str) -> str | None:
        """One distribution owning ``path`` (absolute) or None (``owners`` gives all of them)."""
        r = self.dist_files.lookup(path)
        return r[0][0] if r and r[0] else None

    def write(self, out_dir: str, site_dirs=()) -> None:
        """Rewrite the identity files under ``out_dir`` (atomically per file; stale files removed). Listing files
        (``l/``) are written when a test first depends on them and rewritten here from the directory they name."""
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
        want[PTH] = pth_content(site_dirs)
        for g, content in self.dist_files.claims():
            want[claim_key(g)] = content
        for sub in ("d", "e", "m", "l", "c"):
            os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
        for f in os.listdir(os.path.join(out_dir, "l")):
            if ".tmp" in f:
                continue
            p = os.path.join(out_dir, "l", f)
            try:
                with open(p) as fh:
                    d = fh.readline().rstrip("\n")
            except (OSError, UnicodeDecodeError):
                d = ""
            if d and listing_key(d) == "l/" + f:
                want["l/" + f] = listing_content(d)
        have = set()
        for sub in ("d", "e", "m", "l", "c"):
            for f in os.listdir(os.path.join(out_dir, sub)):
                if ".tmp" not in f:
                    have.add(f"{sub}/{f}")
        for top in (ALL, PTH):
            if os.path.exists(os.path.join(out_dir, top)):
                have.add(top)
        for rel in have - set(want):
            try:
                os.unlink(os.path.join(out_dir, rel))
            except OSError:
                pass
        for rel, content in want.items():
            _write_atomic(os.path.join(out_dir, rel), content)


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
        self._listings: set = set()
        self.global_keys = {PTH}                  # inputs of every test (startup: .pth files)
        self._maps_len = -1

    # -- recording -------------------------------------------------------------------
    def suppressed(self) -> bool:
        return getattr(self.local, "depth", 0) > 0

    def add(self, ctx: int, key: str) -> None:
        """Context ``ctx`` depends on identity ``key``: recorded at once as an ordinary data read of the identity
        file (the Rust capture keys it by content; the record step and the prefix rule need nothing else)."""
        d = self.deps.setdefault(ctx, set())
        if key in d:
            return
        d.add(key)
        p = key if key.startswith("/") else os.path.join(self.dir, key)  # "/...": a file outside every RECORD
        self.cap.read(ctx, p, "f")

    def in_site(self, p: str) -> bool:
        return any(p.startswith(d) for d in self.site_dirs)

    def path(self, ctx: int, p: str) -> None:
        """A read (file or listing) of ``p`` under a site directory, by the test process or a child."""
        if self.suppressed():
            return
        r = self.index.owners(p)
        if r is not None and r[0] == [PROJECT]:
            return  # the project's own editable install: repository files and its metadata are recorded as data
        if os.path.isdir(p) and not self.is_site_dir(p) and ".dist-info" not in p and ".egg-info" not in p:
            # review R-020 H2: a directory under a site directory can gain or lose entries from any distribution
            # (a namespace package, a plugin directory), not only from the one that owns its other files: the
            # listing itself is the input
            self.listing(ctx, p)
            return
        if r is None:
            self.unmapped[p] = self.unmapped.get(p, 0) + 1
            if os.path.isdir(p):
                # a listing no RECORD explains (site-packages itself: pkg_resources' scan): every distribution's
                # presence is the input
                self.add(ctx, ALL)
            else:
                # a file no RECORD lists (_virtualenv.py, a .pth file, a file written after install): its content
                self.add(ctx, os.path.realpath(p))
            return
        for k in self.keys_of(r):
            self.add(ctx, k)

    @staticmethod
    def keys_of(r) -> list:
        """Identity keys of a path with owners and claim group ``r`` (``Index.owners``)."""
        owners, group = r
        keys = ["d/" + _fname(n) for n in owners]
        if group is not None:
            keys.append(claim_key(group))
        return keys

    def _loaded_path(self, p: str, index: int) -> None:
        """A module or native library loaded in the process (seen after the test at ``index``): its owners and
        claim group, or its own content when no RECORD lists it and it sits under a site directory. A path outside
        every site directory that no RECORD lists (the interpreter, system libraries) is not an input here."""
        r = self.index.owners(p)
        if r is None:
            if any(p.startswith(d) for d in self.site_dirs) or any(
                    os.path.realpath(p).startswith(d) for d in self.site_dirs):
                self.unmapped[p] = self.unmapped.get(p, 0) + 1
                self._loaded_key(os.path.realpath(p), index)
            return
        if r[0] == [PROJECT]:
            return
        for k in self.keys_of(r):
            self._loaded_key(k, index)

    def is_site_dir(self, p: str) -> bool:
        p = p.rstrip(os.sep) + os.sep
        return p in self.site_dirs or os.path.realpath(p) + os.sep in self.site_dirs

    def listing(self, ctx: int, d: str) -> None:
        """Depend on the listing of directory ``d`` (under a site directory); its identity file is written on first
        use in the session and rewritten from the directory by ``Index.write`` at the start of every session."""
        key = listing_key(d)
        if key not in self._listings:
            self._listings.add(key)
            p = os.path.join(self.dir, key)
            cap = self.cap
            was, cap.active = cap.active, False  # detpy's own reads and writes are not inputs or outputs
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                _write_atomic(p, listing_content(os.path.realpath(d)))
            except OSError:
                key = ALL
            finally:
                cap.active = was
        self.add(ctx, key)

    def _loaded_key(self, key: str, index: int) -> None:
        if key not in self._loaded_seen:
            self._loaded_seen.add(key)
            self.loaded.append((key, index))
            # an input of the context that loaded it (the test that just ran, or collection); every later test
            # carries it (prefix rule)
            self.add(self._scan_ctx, key)

    def scan(self, index: int, ctx: int | None = None) -> None:
        """Distributions of the modules and native libraries loaded so far (after the test at ``index``, whose
        context is ``ctx``; the current context when None)."""
        self._scan_ctx = self.cap._cur() if ctx is None else ctx
        mods = sys.modules
        if len(mods) != self._nmods:
            self._nmods = len(mods)
            for m in list(mods.values()):
                f = getattr(m, "__file__", None)
                if not isinstance(f, str) or f in self._mod_files_seen:
                    continue
                self._mod_files_seen.add(f)
                self._loaded_path(os.path.abspath(f), index)
        # review R-020 H4: C code can dlopen() a library at any time (lazily loaded CUDA libraries, execution
        # providers, drivers) without a Python event: the maps are read after every test, not only when
        # sys.modules grew or ctypes.dlopen fired; parsed only when they changed
        self._dlopen = False
        try:
            with open("/proc/self/maps") as fh:
                text = fh.read()
        except OSError:
            text = ""
        if len(text) != self._maps_len or text != getattr(self, "_maps_text", None):
            self._maps_len = len(text)
            self._maps_text = text
            lines = text.splitlines()
            for line in lines:
                i = line.find("/")
                if i < 0:
                    continue
                p = line[i:]
                if p in self._maps_seen:
                    continue
                self._maps_seen.add(p)
                # review R-020b N2: every mapping goes through the RECORDs, not only those under a site directory
                # (a wheel's data scheme installs shared libraries into <prefix>/lib: mkl, tbb, intel-openmp)
                self._loaded_path(p, index)

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
                if not cap.active or tracker.suppressed():
                    return None
                if path is None:
                    if "." not in fullname and _by_user(1):
                        tracker.add(cap._cur(), "m/" + _fname(fullname))
                    return None
                # review R-020 H2: a submodule is searched in the directories of its parent's __path__; under a
                # site directory, any distribution can add one there (namespace packages, shared directories):
                # their listings are the input, whether the submodule is found or not
                try:
                    entries = [e for e in path if isinstance(e, str) and tracker.in_site(e.rstrip(os.sep) + os.sep)]
                except Exception:
                    entries = []
                if entries and _by_user(1):
                    ctx = cap._cur()
                    was, cap.active = cap.active, False  # the listing's own reads are not inputs
                    try:
                        for e in entries:
                            tracker.listing(ctx, e)
                    finally:
                        cap.active = was
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
    def data_deps(self, keys) -> dict[str, str]:  # (not used on the Rust capture: see add)
        """{absolute identity file path: dependency string} for identity keys."""
        from . import _core

        out = {}
        for k in keys:
            p = k if k.startswith("/") else os.path.join(self.dir, k)  # "/...": a file outside every RECORD
            d = _core.file_digest(p)
            out[p] = f"f:{d}" if d is not None else "missing"
        return out
