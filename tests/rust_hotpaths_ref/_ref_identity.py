"""Verbatim reference copy of the runtime-identity functions of ``python/detpy/proofcache.py`` before they moved to
Rust (rust-hotpaths-2, ``crates/detpy-py/src/identity.rs``): ``_stat_key``, ``_dist_infos``, ``runtime_identity``,
``tz_locale_identity``, ``_safe``, ``_encodable``, ``cache_epoch`` and start()'s env0 line (as ``env0_of``).
Used by ``tests/test_identity_rust.py``.
"""

from __future__ import annotations

import json
import os
import platform
import sys

from detpy import _core

_DETPY_OWN_ENV = frozenset({"DETPY_REEXEC", "DETPY_PRECOMPILE_S", "DETPY_PYC_CACHE", "DETPY_BLOCKED_PLUGINS"})


def _stat_key(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]


def _dist_infos(root: str, memo_path: str | None = None):
    """(runtime digest part for installed distributions, dist-info dirs of editable installs of the project).

    Reading every distribution's metadata and RECORD takes seconds where thousands are installed: each one's
    result is memoised in ``memo_path`` under the size, mtime, ctime and inode of its metadata files (an installer
    rewrites them, which changes the ctime), so an unchanged environment is not read again.
    """
    from importlib import metadata

    memo: dict = {}
    if memo_path:
        try:
            with open(memo_path) as fh:
                memo = json.load(fh)
        except (OSError, ValueError):
            memo = {}
    fresh: dict = {}
    parts, editable = [], []
    root_sep = os.path.realpath(root) + os.sep
    for d in metadata.distributions():
        path = getattr(d, "_path", None)
        key = None
        if path is not None:
            base = os.path.realpath(str(path))
            key = json.dumps([base, root_sep] + [_stat_key(os.path.join(base, f)) for f in (
                "METADATA", "PKG-INFO", "RECORD", "direct_url.json")])
        hit = memo.get(key) if key is not None else None
        if hit is None:
            # name, version and RECORD digest read in Rust where the plain reading is certain to match
            # importlib.metadata's (simple header block); else importlib.metadata itself
            fast = _core.dist_identity(path) if type(d) is metadata.PathDistribution and path is not None else None
            if fast is not None:
                name = fast[0]
            else:
                name = (d.metadata.get("Name") or "?") if d.metadata is not None else "?"
            project = False
            try:
                du = d.read_text("direct_url.json")
                if du:
                    info = json.loads(du)
                    url = info.get("url", "")
                    if url.startswith("file://") and (os.path.realpath(url[7:]) + os.sep).startswith(root_sep):
                        project = True
            except Exception:
                pass
            if project:
                hit = ["project", os.path.realpath(str(path)) + os.sep if path is not None else None]
            elif fast is not None:
                hit = ["dist", f"{name.lower()}=={fast[1]}:{fast[2]}"]
            else:
                try:
                    rec = d.read_text("RECORD") or ""
                except Exception:
                    rec = ""
                hit = ["dist", f"{name.lower()}=={d.version}:{_core.digest(rec.encode())}"]
        if key is not None:
            fresh[key] = hit
        if hit[0] == "project":
            if hit[1] is not None:
                editable.append(hit[1])
        else:
            parts.append(hit[1])
    if memo_path and fresh != memo:
        try:
            tmp = f"{memo_path}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump(fresh, fh)
            os.replace(tmp, memo_path)
        except OSError:
            pass
    return sorted(set(parts)), sorted(set(editable))  # parallel-proof: duplicates dropped (identity.rs)


def runtime_identity(root: str, memo_path: str | None = None) -> tuple[str, dict, list]:
    import sysconfig

    exe = os.path.realpath(sys.executable)
    lib = None
    libdir, ldlib = sysconfig.get_config_var("LIBDIR"), sysconfig.get_config_var("LDLIBRARY")
    if libdir and ldlib and os.path.exists(os.path.join(libdir, ldlib)):
        lib = os.path.join(libdir, ldlib)
    dists, editable = _dist_infos(root, memo_path)
    d = {
        "python": sys.version,
        "cache_tag": sys.implementation.cache_tag,
        "executable": _core.file_digest(exe),
        "libpython": _core.file_digest(lib) if lib else None,
        "system": platform.system(),
        "machine": platform.machine(),
        "libc": "-".join(platform.libc_ver()),
        "stdlib": _core.listing_digest(os.path.dirname(os.__file__)),
        "distributions": _core.digest("\n".join(dists).encode()),
        "n_distributions": len(dists),
    }
    return _core.digest(json.dumps(d, sort_keys=True).encode()), d, editable


_LOCALE_VARS = ("TZ", "TZDIR", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE",
                "LC_MONETARY", "LC_MESSAGES", "LC_PAPER", "LC_NAME", "LC_ADDRESS", "LC_TELEPHONE",
                "LC_MEASUREMENT", "LC_IDENTIFICATION")


def tz_locale_identity() -> dict:
    """Time zone and locale as C sees them: the variables, /etc/localtime's content and the zone file TZ names."""
    env = dict(os.environ._data) if hasattr(os.environ, "_data") else dict(os.environ)  # noqa: SLF001 (no event)
    dec = {os.fsdecode(k) if isinstance(k, bytes) else k: os.fsdecode(v) if isinstance(v, bytes) else v
           for k, v in env.items()}
    d = {k: dec.get(k) for k in _LOCALE_VARS}
    d["/etc/localtime"] = _core.file_digest("/etc/localtime")
    tz = dec.get("TZ")
    if tz:
        name = tz[1:] if tz.startswith(":") else tz
        zdir = dec.get("TZDIR") or "/usr/share/zoneinfo"
        path = name if os.path.isabs(name) else os.path.join(zdir, name)
        d["tzfile"] = _core.file_digest(path) if os.path.isfile(path) else None
    return d


def _safe(s: str) -> str:
    """``s`` as valid UTF-8 text (undecodable bytes of environment strings escaped)."""
    return s if _encodable(s) else s.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def _encodable(s: str) -> bool:
    try:
        s.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def cache_epoch(cache_dir: str, head_ns: int, window_ns: int) -> int:
    """The epoch the cache in ``cache_dir`` runs its tests at (``epoch.json``).

    The HEAD commit time when the cache took it, kept while the current HEAD commit time ``head_ns`` is at most
    ``window_ns`` later; otherwise (no epoch yet, or older than the window) the epoch moves to ``head_ns``. An older
    checkout keeps the cache's epoch (later than its commit, as for any run after the commit). The epoch is part of
    the key of every test that read the clock, so moving it reruns those tests.
    """
    path = os.path.join(os.path.abspath(cache_dir), "epoch.json")
    try:
        with open(path) as fh:
            kept = int(json.load(fh)["epoch_ns"])
    except (OSError, ValueError, KeyError, TypeError):
        kept = None
    if kept is not None and head_ns - kept <= window_ns:
        return kept
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump({"epoch_ns": head_ns, "taken_from": "git HEAD commit time"}, fh)
        os.replace(tmp, path)
    except OSError:
        pass
    return head_ns


def env0_of(environ_items) -> dict:
    # start(): env0 = {_safe(k): _safe(v) for k, v in os.environ.items() if k not in _DETPY_OWN_ENV}
    return {_safe(k): _safe(v) for k, v in environ_items if k not in _DETPY_OWN_ENV}
