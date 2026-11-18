"""Runtime identity: equal on equivalent machines, different whenever behaviour can differ.

A cached result is reused only under the same runtime identity. The identity is keyed on *content*, never on
machine paths, timestamps or how a package was installed, so two machines built from the same image (or two
virtualenvs at different paths with the same packages) share it, and any change that can change a test's
behaviour changes it:

* ``python``: the interpreter's version string, implementation, ABI, flags (``-O``, ``-X utf8``, ...), warning
  options, encodings, locale and time zone;
* ``executable``: the bytes of the interpreter binary;
* ``native``: the bytes of every shared library in the dynamic-link closure of the interpreter, of the standard
  library's extension modules and of every installed distribution's extension modules (libpython, the C library
  and its loader, libssl, libz, libffi, libsqlite3, ...), found the way the dynamic loader finds them
  (RPATH/RUNPATH with ``$ORIGIN``, ``LD_LIBRARY_PATH``, ``/etc/ld.so.cache``, the default directories) and named
  by file name, not by directory;
* ``stdlib``: the bytes of every standard-library file, by path relative to the standard-library directory;
* ``distributions``: per installed distribution, name, version and the bytes of every file its ``RECORD`` lists
  inside the site directory, except files an installer writes differently on each machine (``RECORD`` itself,
  ``INSTALLER``, ``REQUESTED``, ``direct_url.json``, bytecode caches, scripts outside the site directory). The
  project under test, installed in editable mode, is left out: its files are inputs of each test;
* ``site_tree``: every file under every site directory by relative path and bytes, whether or not a ``RECORD``
  lists it (packages copied in without metadata, files added to a package after installation, egg-info installs,
  ``.pth`` files), except bytecode caches, installer bookkeeping and the project's own editable install;
* ``extra_paths``: the content of import-path entries outside the project, the standard library and the site
  directories (``PYTHONPATH``, ``.pth`` lines to other directories);
* ``sys_path``: the import path, each entry named relative to the standard library, the site directories, the
  interpreter prefixes or the project root;
* ``native`` also holds the libraries ``LD_PRELOAD`` and ``/etc/ld.so.preload`` put ahead of libc;
* ``locale``: every locale category a test gets from ``setlocale(LC_ALL, "")``, ``LANGUAGE`` and the locale data;
  ``tz``: ``TZ``, the zone file it names, ``/etc/localtime``; ``cpu``: CPUs visible to the process and the
  instruction-set level (x86-64 v1..v4; ``FENVIX_RUNTIME_ISA=off`` leaves the level out, at the user's risk).

File digests are memoised under (device, inode, size, mtime, ctime) in a per-interpreter memo file
(``$FENVIX_RUNTIME_MEMO``, default ``~/.cache/fenvix``; ``off`` disables it), so an unchanged machine hashes
nothing again. A copied memo never applies on another machine: the inode and ctime differ.
"""

from __future__ import annotations

import json
import locale
import os
import platform
import struct
import sys
import sysconfig
import time

from . import _core

IDENTITY_VERSION = "fenvix-runtime-3"

# files a distribution's RECORD lists that do not change behaviour and that installers write per machine
_INSTALLER_FILES = {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json", "uv_build.json"}
_SKIP_DIRS = {"__pycache__", "site-packages", "dist-packages"}
_ELF_MAGIC = b"\x7fELF"
_DEFAULT_LIB_DIRS = ("/lib64", "/usr/lib64", "/lib", "/usr/lib", "/usr/local/lib")


# ---------------------------------------------------------------------------------------------------------------------
class _Memo:
    """File digests keyed by path and (device, inode, size, mtime, ctime)."""

    def __init__(self, path: str | None):
        self.path = path
        self.data: dict = {}
        self.dirty = False
        self.hashed = 0
        self.bytes = 0
        if path:
            try:
                with open(path) as fh:
                    d = json.load(fh)
                if d.get("v") == IDENTITY_VERSION:
                    self.data = d.get("files", {})
            except (OSError, ValueError, AttributeError):
                self.data = {}

    @staticmethod
    def _stat_key(st) -> list:
        return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]

    def digest(self, path: str, st=None) -> str | None:
        try:
            st = st or os.stat(path)
        except OSError:
            return None
        key = self._stat_key(st)
        hit = self.data.get(path)
        if hit is not None and hit[:5] == key:
            return hit[5]
        d = _core.file_digest(path)
        if d is not None:
            self.data[path] = key + [d]
            self.dirty = True
            self.hashed += 1
            self.bytes += st.st_size
        return d

    def save(self) -> None:
        if not (self.path and self.dirty):
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.tmp{os.getpid()}"
            with open(tmp, "w") as fh:
                json.dump({"v": IDENTITY_VERSION, "files": self.data}, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass


def _default_memo_path() -> str | None:
    v = os.environ.get("FENVIX_RUNTIME_MEMO")
    if v == "off":
        return None
    if v:
        return v
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    tag = _core.digest(os.path.realpath(sys.prefix).encode())[:12]
    return os.path.join(base, "fenvix", f"runtime-memo-{tag}.json")


def _h(text: str) -> str:
    return _core.digest(text.encode("utf-8", "surrogateescape"))


# ---------------------------------------------------------------------------------------------------------------------
# ELF: DT_NEEDED closure, resolved like the dynamic loader
def _elf_info(path: str):
    """(class, machine, needed, rpath, runpath) of an ELF shared object or executable; None if not ELF."""
    try:
        with open(path, "rb") as fh:
            ident = fh.read(64)
            if len(ident) < 52 or ident[:4] != _ELF_MAGIC:
                return None
            cls, data = ident[4], ident[5]
            e = "<" if data == 1 else ">"
            if cls == 2:
                (_, machine, _, _, phoff, _, _, _, phentsize, phnum) = struct.unpack(e + "HHIQQQIHHH", ident[16:58])
            elif cls == 1:
                (_, machine, _, _, phoff, _, _, _, phentsize, phnum) = struct.unpack(e + "HHIIIIIHHH", ident[16:46])
            else:
                return None
            fh.seek(phoff)
            ph = fh.read(phentsize * phnum)
            loads, dyn = [], None
            for i in range(phnum):
                b = ph[i * phentsize:(i + 1) * phentsize]
                if cls == 2:
                    p_type, _, p_offset, p_vaddr, _, p_filesz, _, _ = struct.unpack(e + "IIQQQQQQ", b[:56])
                else:
                    p_type, p_offset, p_vaddr, _, p_filesz, _, _, _ = struct.unpack(e + "IIIIIIII", b[:32])
                if p_type == 1:
                    loads.append((p_vaddr, p_offset, p_filesz))
                elif p_type == 2:
                    dyn = (p_offset, p_filesz)
            if dyn is None:
                return (cls, machine, [], [], [])
            fh.seek(dyn[0])
            raw = fh.read(dyn[1])
            fmt, size = (e + "qQ", 16) if cls == 2 else (e + "iI", 8)
            needed, rpath, runpath, strtab, strsz = [], [], [], None, None
            for i in range(0, len(raw) - size + 1, size):
                tag, val = struct.unpack(fmt, raw[i:i + size])
                if tag == 0:
                    break
                if tag == 1:
                    needed.append(val)
                elif tag == 15:
                    rpath.append(val)
                elif tag == 29:
                    runpath.append(val)
                elif tag == 5:
                    strtab = val
                elif tag == 10:
                    strsz = val
            if strtab is None:
                return (cls, machine, [], [], [])
            off = None
            for vaddr, offset, filesz in loads:
                if vaddr <= strtab < vaddr + filesz:
                    off = strtab - vaddr + offset
                    break
            if off is None:
                off = strtab
            fh.seek(off)
            strs = fh.read(strsz or 1 << 20)
    except (OSError, struct.error):
        return None

    def s(o: int) -> str:
        end = strs.find(b"\0", o)
        return os.fsdecode(strs[o:end if end >= 0 else len(strs)])

    split = lambda vals: [p for v in vals for p in s(v).split(":") if p]  # noqa: E731
    return (cls, machine, [s(v) for v in needed], split(rpath), split(runpath))


def _ld_cache() -> dict[str, list[str]]:
    """soname -> paths from /etc/ld.so.cache (glibc's new format), in cache order."""
    out: dict[str, list[str]] = {}
    try:
        with open("/etc/ld.so.cache", "rb") as fh:
            b = fh.read()
    except OSError:
        return out
    magic = b"glibc-ld.so.cache1.1"
    base = b.find(magic)
    if base < 0:
        return out
    try:
        nlibs, _ = struct.unpack_from("<II", b, base + 20)
        for i in range(nlibs):
            _, key, value, _, _ = struct.unpack_from("<iIIIQ", b, base + 48 + 24 * i)
            k_end, v_end = b.find(b"\0", base + key), b.find(b"\0", base + value)
            out.setdefault(os.fsdecode(b[base + key:k_end]), []).append(os.fsdecode(b[base + value:v_end]))
    except struct.error:
        pass
    return out


class _Linker:
    def __init__(self, exe: str, exe_info):
        self.cls, self.machine = (exe_info[0], exe_info[1]) if exe_info else (None, None)
        # the executable's DT_RPATH also serves every object without a RUNPATH; its $ORIGIN is the executable's
        exe_origin = os.path.dirname(os.path.realpath(exe))
        self.exe_rpath = [d.replace("${ORIGIN}", exe_origin).replace("$ORIGIN", exe_origin)
                          for d in (exe_info[3] if exe_info and not exe_info[4] else [])]
        self.ld_library_path = [p for p in os.environ.get("LD_LIBRARY_PATH", "").split(":") if p]
        self._cache = None
        self._info: dict[str, object] = {}
        self.multiarch = sysconfig.get_config_var("MULTIARCH") or ""

    def info(self, path: str):
        if path not in self._info:
            self._info[path] = _elf_info(path)
        return self._info[path]

    def _fits(self, path: str) -> bool:
        i = self.info(path)
        return i is not None and (self.cls is None or (i[0] == self.cls and i[1] == self.machine))

    def resolve(self, name: str, obj: str, rpath: list, runpath: list) -> str | None:
        if "/" in name:
            p = name if os.path.isabs(name) else os.path.join(os.path.dirname(obj), name)
            return os.path.realpath(p) if os.path.exists(p) else None
        origin = os.path.dirname(os.path.realpath(obj))
        dirs = []
        if not runpath:
            dirs += rpath + self.exe_rpath
        dirs += self.ld_library_path + runpath
        for d in dirs:
            d = d.replace("$ORIGIN", origin).replace("${ORIGIN}", origin)
            p = os.path.join(d, name)
            if os.path.exists(p) and self._fits(p):
                return os.path.realpath(p)
        if self._cache is None:
            self._cache = _ld_cache()
        for p in self._cache.get(name, []):
            if os.path.exists(p) and self._fits(p):
                return os.path.realpath(p)
        defaults = list(_DEFAULT_LIB_DIRS)
        if self.multiarch:
            defaults = [f"/lib/{self.multiarch}", f"/usr/lib/{self.multiarch}"] + defaults
        for d in defaults:
            p = os.path.join(d, name)
            if os.path.exists(p) and self._fits(p):
                return os.path.realpath(p)
        return None

    def closure(self, roots: list[str]) -> tuple[dict[str, str], set[str]]:
        """{real path: soname-ish name} of every library the roots need (transitively), and unresolved names."""
        found: dict[str, str] = {}
        missing: set[str] = set()
        todo = list(roots)
        seen = set()
        while todo:
            obj = todo.pop()
            if obj in seen:
                continue
            seen.add(obj)
            i = self.info(obj)
            if not i:
                continue
            for name in i[2]:
                p = self.resolve(name, obj, i[3], i[4])
                if p is None:
                    missing.add(name)
                    continue
                if p not in found:
                    found[p] = name
                    todo.append(p)
        return found, missing


# ---------------------------------------------------------------------------------------------------------------------
def _site_dirs() -> list[str]:
    paths = sysconfig.get_paths()
    out = []
    for p in [paths.get("purelib"), paths.get("platlib")] + [p for p in sys.path if p.endswith(("site-packages",
                                                                                                 "dist-packages"))]:
        if p and os.path.isdir(p):
            r = os.path.realpath(p)
            if r not in out:
                out.append(r)
    return out


def _stdlib_dirs() -> list[str]:
    paths = sysconfig.get_paths()
    out = []
    for p in (paths.get("stdlib"), paths.get("platstdlib"), os.path.dirname(os.__file__)):
        if p and os.path.isdir(p):
            r = os.path.realpath(p)
            if r not in out:
                out.append(r)
    return out


def _tree_digest(top: str, memo: _Memo, natives: list) -> tuple[str, int]:
    """Digest of (relative path, content digest) of every file under ``top``, outside bytecode caches and site
    directories; extension modules found go to ``natives``."""
    rows = []
    for dp, dn, fn in os.walk(top):
        dn[:] = sorted(d for d in dn if d not in _SKIP_DIRS)
        for f in sorted(fn):
            p = os.path.join(dp, f)
            if f.endswith(".pyc"):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not os.path.isfile(p):
                continue
            rows.append(f"{os.path.relpath(p, top)}\0{memo.digest(p, st)}")
            if f.endswith(".so") or ".so." in f:
                natives.append(p)
    return _h("\n".join(rows)), len(rows)


def _record_paths(d) -> list[str] | None:
    try:
        rec = d.read_text("RECORD")
    except Exception:
        rec = None
    if rec is None:
        return None
    out = []
    import csv

    for row in csv.reader(rec.splitlines()):
        if row and row[0]:
            out.append(row[0])
    return out


def _distributions(root: str, memo: _Memo, natives: list):
    """(sorted 'name==version:content' lines, editable dist-info dirs of the project, paths the project's editable
    install owns). The lines group installed files per distribution for diagnosis; what is keyed is the whole site
    tree (``_site_tree``)."""
    from importlib import metadata

    lines, editable, owned = [], [], set()
    root_sep = os.path.realpath(root) + os.sep
    for d in metadata.distributions():
        meta = d.metadata
        name = ((meta.get("Name") if meta is not None else None) or "?").lower().replace("_", "-")
        version = d.version
        path = getattr(d, "_path", None)
        info_dir = os.path.realpath(str(path)) if path is not None else None
        base = os.path.dirname(info_dir) if info_dir else None
        project = False
        try:
            du = d.read_text("direct_url.json")
            if du:
                url = json.loads(du).get("url", "")
                if url.startswith("file://") and (os.path.realpath(url[7:]) + os.sep).startswith(root_sep):
                    project = True
        except Exception:
            pass
        files = _record_paths(d)
        if project:
            if base and files:
                for f in files:
                    owned.add(os.path.normpath(os.path.join(base, f)))
            if info_dir is not None:
                editable.append(info_dir + os.sep)
            continue
        if base is None or files is None:
            # no RECORD (old egg-info installs): name, version and metadata text
            text = ""
            try:
                text = d.read_text("METADATA") or d.read_text("PKG-INFO") or ""
            except Exception:
                pass
            lines.append(f"{name}=={version}:meta:{_h(text)}")
            continue
        rows = []
        for f in sorted(set(files)):
            parts = f.replace("\\", "/").split("/")
            if parts[0] == ".." or os.path.isabs(f) or "__pycache__" in parts or f.endswith(".pyc"):
                continue
            if len(parts) == 2 and parts[0].endswith((".dist-info", ".egg-info")) and parts[1] in _INSTALLER_FILES:
                continue
            p = os.path.join(base, f)
            dg = memo.digest(p)
            rows.append(f"{f}\0{dg or 'missing'}")
            if dg and (f.endswith(".so") or ".so." in f):
                natives.append(p)
        lines.append(f"{name}=={version}:{_h(chr(10).join(rows))}")
    return sorted(lines), editable, owned


def _is_installer_file(rel_parts: list[str]) -> bool:
    """Files an installer writes differently on each machine: a dist-info's RECORD, INSTALLER, REQUESTED,
    direct_url.json (they name paths, tools and times, not behaviour)."""
    return (len(rel_parts) >= 2 and rel_parts[-2].endswith((".dist-info", ".egg-info"))
            and rel_parts[-1] in _INSTALLER_FILES)


def _site_tree(sites: list[str], project_owned: set, project_dirs: list, memo: _Memo, natives: list) -> tuple[str, int]:
    """Every file under every site directory by relative path and bytes: installed distributions, files no RECORD
    lists (packages copied in without metadata, files added to a package after installation, egg-info installs),
    ``.pth`` files. Left out: bytecode caches, installer bookkeeping files, and the project's own editable install
    (its files are per-test inputs; its .pth names the checkout path)."""
    rows = []
    proj = tuple(project_dirs)
    for i, s in enumerate(sites):
        for dp, dn, fn in os.walk(s):
            dn[:] = sorted(d for d in dn if d != "__pycache__" and not (os.path.join(dp, d) + os.sep).startswith(proj))
            for f in sorted(fn):
                p = os.path.join(dp, f)
                if f.endswith((".pyc", ".pyo")) or os.path.normpath(p) in project_owned:
                    continue
                rel = os.path.relpath(p, s)
                if _is_installer_file(rel.split(os.sep)):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if not os.path.isfile(p):
                    continue
                rows.append(f"{i}\0{rel}\0{memo.digest(p, st)}")
                if f.endswith(".so") or ".so." in f:
                    natives.append(p)
    return _h("\n".join(rows)), len(rows)


_EXTRA_PATH_MAX_FILES = 50_000


def _extra_paths(root: str, stdlib: list[str], sites: list[str], memo: _Memo, natives: list) -> tuple[str, list]:
    """Import-path entries outside the project, the standard library and the site directories (PYTHONPATH, a .pth
    line to /opt/..., a second checkout): their modules are imported by the import system, which is never a
    per-test input, so their content is keyed here (relative path and bytes; a zip or file by its bytes). An entry
    with more than 50,000 files is keyed on a fresh random value: never reusable, rather than unchecked."""
    known = [os.path.realpath(root)] + stdlib + sites
    name = _namer(root, stdlib, sites)
    rows, labels = [], []
    seen = set()
    for p in sys.path:
        r = os.path.realpath(p or os.getcwd())
        if r in seen or any(r == d or r.startswith(d + os.sep) for d in known):
            continue
        seen.add(r)
        if os.path.isdir(r):
            files = []
            for dp, dn, fn in os.walk(r):
                dn[:] = sorted(d for d in dn if d != "__pycache__")
                files += [os.path.join(dp, f) for f in sorted(fn) if not f.endswith((".pyc", ".pyo"))]
                if len(files) > _EXTRA_PATH_MAX_FILES:
                    break
            if len(files) > _EXTRA_PATH_MAX_FILES:
                rows.append(f"{name(r)}\0too-many-files\0{os.urandom(16).hex()}")
                labels.append(f"{r} (too many files: never reusable)")
                continue
            sub = []
            for f in files:
                if os.path.isfile(f):
                    sub.append(f"{os.path.relpath(f, r)}\0{memo.digest(f)}")
                    if f.endswith(".so") or ".so." in f:
                        natives.append(f)
            rows.append(f"{name(r)}\0{_h(chr(10).join(sub))}")
            labels.append(f"{r} ({len(sub)} files)")
        elif os.path.isfile(r):
            rows.append(f"{name(r)}\0{memo.digest(r)}")
            labels.append(r)
        else:
            rows.append(f"{name(r)}\0missing")
    return _h("\n".join(rows)), labels


def _namer(root: str, stdlib: list[str], sites: list[str]):
    """A function naming a path relative to the project root, stdlib, site directories or interpreter prefixes
    (machine-independent); other paths keep their absolute path."""
    named = [(os.path.realpath(root), "<root>")]
    named += [(d, f"<stdlib{i}>") for i, d in enumerate(stdlib)]
    named += [(d, f"<site{i}>") for i, d in enumerate(sites)]
    named += [(os.path.realpath(sys.prefix), "<prefix>"), (os.path.realpath(sys.base_prefix), "<base_prefix>")]
    named.sort(key=lambda x: len(x[0]), reverse=True)

    def name(r: str) -> str:
        for d, label in named:
            if r == d or r.startswith(d + os.sep):
                rel = os.path.relpath(r, d)
                return label if rel == "." else f"{label}/{rel}"
        return r  # another directory: its path here, its content in ``extra_paths``
    return name


def _sys_path(root: str, stdlib: list[str], sites: list[str]) -> list[str]:
    name = _namer(root, stdlib, sites)
    return [name(os.path.realpath(p or os.getcwd())) for p in sys.path]


_LOCALE_CATEGORIES = ("LC_CTYPE", "LC_COLLATE", "LC_TIME", "LC_NUMERIC", "LC_MONETARY", "LC_MESSAGES")
_X86_LEVELS = (
    ("v2", {"cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3"}),
    ("v3", {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave"}),
    ("v4", {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}),
)


def _locale_part(memo: _Memo) -> dict:
    """What glibc gives a test that calls ``setlocale(LC_ALL, "")``: every category's value from the environment
    (read by C, never through os.environ), LANGUAGE, and the locale data (LOCPATH or /usr/lib/locale). The
    process's own locale is restored afterwards."""
    cats = [(n, getattr(locale, n)) for n in _LOCALE_CATEGORIES if hasattr(locale, n)]
    saved = {}
    for n, c in cats:
        try:
            saved[n] = locale.setlocale(c, None)
        except locale.Error:
            saved[n] = None
    env_locale: dict = {}
    try:
        locale.setlocale(locale.LC_ALL, "")
        for n, c in cats:
            env_locale[n] = locale.setlocale(c, None)
    except locale.Error as e:
        env_locale["error"] = str(e)
    finally:
        for n, c in cats:
            if saved.get(n) is not None:
                try:
                    locale.setlocale(c, saved[n])
                except locale.Error:
                    pass
    data_dir = os.environ.get("LOCPATH") or "/usr/lib/locale"
    data = _h("\n".join(f"{os.path.relpath(os.path.join(dp, f), data_dir)}\0{memo.digest(os.path.join(dp, f))}"
                        for dp, dn, fn in sorted(os.walk(data_dir)) for f in sorted(fn))) if os.path.isdir(data_dir) \
        else "missing"
    return {"categories": env_locale, "language": os.environ.get("LANGUAGE"), "locpath": "LOCPATH" in os.environ,
            "data": data}


def _tz_part(memo: _Memo) -> dict:
    """TZ and the zone rules behind it: the TZ value, /etc/localtime and /etc/timezone bytes, and the bytes of the
    zoneinfo file TZ names (tzname and the offsets alone do not fix the rules)."""
    tz = os.environ.get("TZ")
    zone = None
    if tz:
        name = tz[1:] if tz.startswith(":") else tz
        for base in (os.environ.get("TZDIR"), "/usr/share/zoneinfo"):
            if base and not os.path.isabs(name) and os.path.isfile(os.path.join(base, name)):
                zone = memo.digest(os.path.join(base, name))
                break
        if zone is None and os.path.isabs(name) and os.path.isfile(name):
            zone = memo.digest(name)
    return {"TZ": tz, "zone": zone, "localtime": memo.digest("/etc/localtime"),
            "timezone": memo.digest("/etc/timezone"), "offsets": [time.timezone, time.altzone, list(time.tzname)]}


def _cpu_part() -> dict:
    """CPUs visible to the process (pool sizes, chunking) and, unless FENVIX_RUNTIME_ISA=off, the instruction-set
    level (x86-64 v1..v4 from /proc/cpuinfo; elsewhere the feature list): native code that dispatches on CPU features
    (libm, numpy, OpenBLAS) can give other floating-point results."""
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = None
    d = {"cpu_count": os.cpu_count(), "affinity": affinity,
         "process_cpu_count": getattr(os, "process_cpu_count", lambda: None)()}
    if os.environ.get("FENVIX_RUNTIME_ISA", "level") == "off":
        d["isa"] = "not keyed (FENVIX_RUNTIME_ISA=off)"
        return d
    flags = None
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                if k.strip() in ("flags", "Features"):
                    flags = set(v.split())
                    break
    except OSError:
        pass
    if flags is None:
        d["isa"] = platform.processor() or platform.machine()
    elif platform.machine() in ("x86_64", "AMD64"):
        level = "v1"
        for name, need in _X86_LEVELS:
            if need <= flags:
                level = name
            else:
                break
        d["isa"] = f"x86-64-{level}"
    else:
        d["isa"] = f"{platform.machine()}:{_h(' '.join(sorted(flags)))}"
    return d


def _preload_names() -> list[str]:
    """Libraries the loader puts in every process ahead of the program's own: LD_PRELOAD and /etc/ld.so.preload."""
    names = os.environ.get("LD_PRELOAD", "").replace(":", " ").split()
    try:
        with open("/etc/ld.so.preload") as fh:
            names += fh.read().split()
    except OSError:
        pass
    return names


def _python_part() -> dict:
    try:
        ctype = locale.setlocale(locale.LC_CTYPE, None)
    except locale.Error:
        ctype = "?"
    impl = sys.implementation
    return {
        "version": sys.version,
        "implementation": [impl.name, list(impl.version)],
        "hexversion": sys.hexversion,
        "cache_tag": impl.cache_tag,
        "abiflags": getattr(sys, "abiflags", ""),
        "platform": sys.platform,
        "byteorder": sys.byteorder,
        "maxsize": sys.maxsize,
        "flags": repr(sys.flags),
        "warnoptions": list(sys.warnoptions),
        "xoptions": sorted(f"{k}={v}" for k, v in sys._xoptions.items()),
        "fs_encoding": sys.getfilesystemencoding(),
        "preferred_encoding": locale.getpreferredencoding(False),
        "lc_ctype": ctype,
        "tz": [time.timezone, time.altzone, list(time.tzname)],
        "system": platform.system(),
        "machine": platform.machine(),
    }


# ---------------------------------------------------------------------------------------------------------------------
def runtime_parts(root: str, memo_path: str | None = "default") -> tuple[dict, dict, list]:
    """(parts that make the identity, details for diagnosis, dist-info dirs of editable installs of the project)."""
    t0 = time.perf_counter()
    memo = _Memo(_default_memo_path() if memo_path == "default" else memo_path)
    exe = os.path.realpath(sys.executable)
    stdlib, sites = _stdlib_dirs(), _site_dirs()
    natives: list[str] = [exe]
    std_rows, std_files = [], 0
    for i, d in enumerate(stdlib):
        dg, n = _tree_digest(d, memo, natives)
        std_rows.append(dg)
        std_files += n
    dists, editable, project_owned = _distributions(root, memo, natives)
    site_digest, site_files = _site_tree(sites, project_owned, [e.rstrip(os.sep) + os.sep for e in editable], memo,
                                         natives)
    extra_digest, extra_labels = _extra_paths(root, stdlib, sites, memo, natives)
    exe_info = _elf_info(exe)
    native_lines, libc, libpython, unresolved = [], None, None, []
    if exe_info is not None:
        linker = _Linker(exe, exe_info)
        own = set(os.path.realpath(p) for p in natives)
        roots = sorted(own)
        for name in _preload_names():  # ahead of every other library in the process
            pre = linker.resolve(name, exe, [], [])
            if pre is None:
                native_lines.append(f"preload:{os.path.basename(name)}:unresolved")
            else:
                native_lines.append(f"preload:{os.path.basename(pre)}:{memo.digest(pre)}")
                roots.append(pre)
        libs, missing = linker.closure(roots)
        for p, name in sorted(libs.items(), key=lambda kv: (kv[1], kv[0])):
            if p in own:
                continue  # an extension module or a vendored library: keyed by the stdlib or its distribution
            dg = memo.digest(p)
            native_lines.append(f"{name}:{dg}")
            if name.startswith("libc.so"):
                libc = f"{'-'.join(platform.libc_ver())}:{dg}"
            if name.startswith("libpython"):
                libpython = dg
        unresolved = sorted(missing)
        native_lines += [f"{n}:unresolved" for n in unresolved]
    else:  # not ELF (macOS, Windows): the OS release stands for the system libraries
        native_lines.append(f"os:{platform.platform()}")
    if libpython is None:
        libdir, ldlib = sysconfig.get_config_var("LIBDIR"), sysconfig.get_config_var("LDLIBRARY")
        if libdir and ldlib and os.path.exists(os.path.join(libdir, ldlib)) and ldlib.endswith((".so", ".dylib")):
            libpython = memo.digest(os.path.join(libdir, ldlib))
    parts = {
        "identity": IDENTITY_VERSION,
        "python": _h(json.dumps(_python_part(), sort_keys=True)),
        "executable": memo.digest(exe),
        "libpython": libpython,
        "libc": libc or "-".join(platform.libc_ver()),
        "native": _h("\n".join(native_lines)),
        "stdlib": _h("\n".join(std_rows)),
        "distributions": _h("\n".join(dists)),
        "site_tree": site_digest,
        "extra_paths": extra_digest,
        "sys_path": _h("\n".join(_sys_path(root, stdlib, sites))),
        "locale": _h(json.dumps(_locale_part(memo), sort_keys=True)),
        "tz": _h(json.dumps(_tz_part(memo), sort_keys=True)),
        "cpu": _h(json.dumps(_cpu_part(), sort_keys=True)),
    }
    memo.save()
    details = {
        "python_version": platform.python_version(),
        "python": _python_part(),
        "dist_list": dists,
        "native_list": native_lines,
        "unresolved_native": unresolved,
        "sys_path": _sys_path(root, stdlib, sites),
        "extra_paths": extra_labels,
        "cpu": _cpu_part(),
        "n_site_files": site_files,
        "n_distributions": len(dists),
        "n_stdlib_files": std_files,
        "n_native": len(native_lines),
        "hashed_files": memo.hashed,
        "hashed_bytes": memo.bytes,
        "seconds": round(time.perf_counter() - t0, 4),
    }
    return parts, details, editable


def runtime_identity(root: str, memo_path: str | None = "default") -> tuple[str, dict, list]:
    """(digest, parts, editable dist-info dirs of the project) — the engine's runtime identity."""
    parts, details, editable = runtime_parts(root, memo_path)
    info = dict(parts)
    info["python_version"] = details["python_version"]
    info["n_distributions"] = details["n_distributions"]
    return _core.digest(json.dumps(parts, sort_keys=True).encode()), info, editable


def describe(root: str) -> dict:
    """Everything, for ``fenvix-run`` and ``python -m detpy.runtime_id``: digest, parts and details."""
    parts, details, _ = runtime_parts(root)
    return {"digest": _core.digest(json.dumps(parts, sort_keys=True).encode()), **parts, "details": details}


if __name__ == "__main__":
    print(json.dumps(describe(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()), indent=1))
