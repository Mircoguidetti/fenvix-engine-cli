"""File-level dependency capture with strace (language agnostic).

``traced(cmd, ...)`` runs a command under ``strace -f`` and returns what the
whole process tree observed of the file system:

* ``reads``   files whose content *before the run* the run could observe: opened read-only, or opened
              read-write / append (``O_RDWR``, ``O_APPEND``, Python ``"r+"``/``"a"``, sqlite, mmap) when the
              open neither truncated (``O_TRUNC``, ``creat``) nor created the file (``O_EXCL``, or a probe
              earlier in the same run found the path missing). A path is classified by its *first* access in
              the trace: read first -> dependency even if the run writes it later (review R-002 error 1);
              truncated / created first -> not a dependency;
* ``rw``      the subset of ``reads`` that the run also opened for writing or modified: their recorded
              content must be the content before the run (the caller hashes the committed blob), not the
              content the run left behind;
* ``exists``  paths successfully stat'ed / accessed (existence and type matter);
* ``missing`` paths probed that did not exist (a file created there later can
              change module resolution, plugin discovery, ...);
* ``lists``   directories whose entries were listed (getdents64), each with the
              position (line index) of the listing, so callers can drop the
              runner's own discovery crawl;
* ``execs``   programs executed;
* ``net``     inet connect() attempts [address, port], whatever their result (a refused or unreachable
              connection also makes the outcome depend on the network); per group as well;
* ``first``   line index of the first successful read of each path.

Only paths below one of ``roots`` are kept (repository, virtualenv,
node_modules, module cache). ``__pycache__/*.pyc`` reads are mapped to the
``.py`` source they were compiled from.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

STRACE_SYSCALLS = "%file,getdents64,connect,fchdir,clone,clone3,fork,vfork"
_LINE = re.compile(r"^(\d+)\s+(.*)$")
_CALL = re.compile(r"^([a-z0-9_]+)\((.*)\)\s+=\s+(-?\d+|\?)(.*)$")
_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')
_FDPATH = re.compile(r"^(?:AT_FDCWD|\d+)<([^>]*)>")
_RETPATH = re.compile(r"^<([^>]*)>")
_PYC = re.compile(r"^(.*)/__pycache__/([^/.]+)\.[^/]*\.pyc$")

WRITE_FLAGS = ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND")
_FLAG = re.compile(r"\bO_[A-Z]+\b")


def is_local_address(ip, port=0) -> bool:
    """True only for a loopback / unspecified address that is not a DNS query. Unknown address: not local.

    A connect to port 53 is name resolution: the answer comes from outside the machine even when the resolver
    listens on loopback (systemd-resolved, 127.0.0.53), so it counts as external network."""
    import ipaddress
    if port == 53:
        return False
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_loopback or a.is_unspecified


def external(net) -> list:
    """The non-local entries of a ``net`` list ([address, port] pairs)."""
    return [x for x in net if not is_local_address(x[0], x[1] if len(x) > 1 else 0)]
STAT_CALLS = {"stat", "lstat", "newfstatat", "statx", "access", "faccessat", "faccessat2", "readlink",
              "readlinkat", "stat64", "lstat64", "fstatat64"}
OPEN_CALLS = {"open", "openat", "openat2", "creat"}
WRITE_CALLS = {"unlink", "unlinkat", "rename", "renameat", "renameat2", "mkdir", "mkdirat", "rmdir", "symlink",
               "symlinkat", "link", "linkat", "truncate", "utimensat", "chmod", "fchmodat"}


def _unescape(s: str) -> str:
    if "\\" not in s:
        return s
    try:
        return s.encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode(
            "utf-8", "replace")
    except Exception:
        return s


def traced(cmd, cwd, env, log_path, roots, timeout=None, keep_log=False, group_suffix=None):
    """Run ``cmd`` under strace; return (returncode, output, wall_seconds, deps)."""
    full = ["strace", "-f", "-qq", "-y", "--seccomp-bpf", "-e", "trace=" + STRACE_SYSCALLS, "-e", "signal=none",
            "-s", "1024", "-o", str(log_path), "--"] + list(cmd)
    t0 = time.perf_counter()
    try:
        p = subprocess.run(full, cwd=cwd, env=env, capture_output=True, text=True, errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
        code, out = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        code = -9
        out = (e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + "\nTIMEOUT"
    wall = time.perf_counter() - t0
    deps = parse(log_path, cwd, roots, group_suffix)
    if not keep_log:
        try:
            os.unlink(log_path)
        except OSError:
            pass
    return code, out, wall, deps


def _keep(path: str, roots) -> bool:
    for r in roots:
        if path == r or path.startswith(r + "/"):
            return True
    return False


SKIP_PARTS = ("/.git/", "/.pytest_cache", "/.mypy_cache", "/.hypothesis", "/node_modules/.vite",
              "/node_modules/.cache", "/.ruff_cache", "/.s2rec/", "/.coverage")


def parse(log_path, cwd, roots, group_suffix=None) -> dict:
    roots = [os.path.realpath(r) for r in roots] + [r for r in roots]
    roots = sorted(set(roots))
    cwds = {}
    pending = {}
    reads, written, exists, missing, execs = {}, set(), set(), set(), []
    first = {}  # path -> "r" (first access observed the content before the run) or "w" (truncated/created first)
    lists = {}
    net = []
    root_pid = None
    n = 0
    group = {}  # pid -> group label (cwd of the exec of a binary ending with group_suffix)
    gdeps = {}

    def gadd(pid, kind, path):
        g = group.get(pid)
        if g is not None:
            gdeps.setdefault(g, {}).setdefault(kind, set()).add(path)

    def keep(path):
        return _keep(path, roots) and not any(x in path for x in SKIP_PARTS)

    def absify(pid, dirpart, p):
        if p.startswith("/"):
            return os.path.normpath(p)
        base = dirpart or cwds.get(pid) or str(cwd)
        return os.path.normpath(os.path.join(base, p))

    try:
        fh = open(log_path, errors="replace")
    except OSError:
        return {"error": "no-log"}
    with fh:
        for raw in fh:
            m = _LINE.match(raw.rstrip("\n"))
            if not m:
                continue
            pid, rest = int(m.group(1)), m.group(2)
            if root_pid is None:
                root_pid = pid
                cwds[pid] = str(cwd)
            if rest.endswith("<unfinished ...>"):
                pending[pid] = rest[: -len("<unfinished ...>")].rstrip()
                continue
            if rest.startswith("<..."):
                head = pending.pop(pid, None)
                if head is None:
                    continue
                k = rest.find("resumed>")
                rest = head + rest[k + len("resumed>"):] if k >= 0 else head
            if rest.startswith("+++") or rest.startswith("---"):
                continue
            cm = _CALL.match(rest)
            if not cm:
                continue
            n += 1
            name, args, ret, tail = cm.group(1), cm.group(2), cm.group(3), cm.group(4)
            ok = ret != "?" and not ret.startswith("-")
            if name in ("clone", "clone3", "fork", "vfork"):
                if ok and ret != "0":
                    # the child's own events can be logged before this return line: do not overwrite them
                    cwds.setdefault(int(ret), cwds.get(pid, str(cwd)))
                    if pid in group:
                        group.setdefault(int(ret), group[pid])
                continue
            if name == "chdir":
                s = _STR.search(args)
                if ok and s:
                    cwds[pid] = absify(pid, None, _unescape(s.group(1)))
                continue
            if name == "fchdir":
                fm = _FDPATH.match(args)
                if ok and fm:
                    cwds[pid] = fm.group(1)
                continue
            if name == "getdents64":
                fm = _FDPATH.match(args)
                if ok and fm:
                    d = fm.group(1)
                    if _keep(d, roots) and not any(s in d + "/" for s in SKIP_PARTS):
                        lists.setdefault(d, n)
                continue
            if name == "connect":
                # every inet attempt counts, whatever its result: a refused / unreachable / timed-out connection
                # also makes the outcome depend on the network
                if "AF_INET" in args:
                    ip = re.search(r'inet_addr\("([^"]+)"\)|inet_pton\(AF_INET6, "([^"]+)"', args)
                    port = re.search(r"sin6?_port=htons\((\d+)\)", args)
                    item = ((ip.group(1) or ip.group(2)) if ip else "?", int(port.group(1)) if port else 0)
                    gadd(pid, "net", item)
                    net.append(list(item))
                continue
            # path syscalls
            dirpart = None
            fm = _FDPATH.match(args)
            if fm:
                dirpart = fm.group(1)
            s = _STR.search(args)
            if not s:
                continue
            path = absify(pid, dirpart, _unescape(s.group(1)))
            if name in OPEN_CALLS:
                flags = args[s.end():]
                if ok:
                    rp = _RETPATH.match(tail.strip())
                    real = rp.group(1) if rp else path
                    fl = set(_FLAG.findall(flags))
                    if fl & set(WRITE_FLAGS) or name == "creat":
                        written.add(path)
                        written.add(real)
                        clobber = name == "creat" or "O_TRUNC" in fl or "O_EXCL" in fl or path in missing \
                            or not (fl & {"O_RDWR", "O_APPEND"})
                        if clobber:
                            first.setdefault(path, "w")
                        elif keep(path) and first.setdefault(path, "r") == "r":
                            # read-write / append open of an existing file: its content before the run is an input
                            reads.setdefault(path, n)
                            gadd(pid, "reads", path)
                        continue
                    if "O_DIRECTORY" in flags:
                        if _keep(path, roots) and not any(x in path for x in SKIP_PARTS):
                            exists.add(path)
                        continue
                    pm = _PYC.match(path)
                    if pm:
                        path = f"{pm.group(1)}/{pm.group(2)}.py"
                    if keep(path):
                        first.setdefault(path, "r")
                        reads.setdefault(path, n)
                        gadd(pid, "reads", path)
                else:
                    if ("ENOENT" in tail or "ENOTDIR" in tail) and _keep(path, roots) \
                            and not any(x in path for x in SKIP_PARTS):
                        missing.add(path); gadd(pid, "missing", path)
            elif name in STAT_CALLS:
                if not _keep(path, roots) or any(x in path for x in SKIP_PARTS):
                    continue
                if ok:
                    exists.add(path)
                elif "ENOENT" in tail or "ENOTDIR" in tail:
                    missing.add(path); gadd(pid, "missing", path)
            elif name == "execve":
                if ok:
                    execs.append(path)
                    if group_suffix and path.endswith(group_suffix):
                        group[pid] = cwds.get(pid, str(cwd))
                    gadd(pid, "execs", path)
            elif name in WRITE_CALLS:
                if ok:
                    written.add(path)
                    first.setdefault(path, "w")
                    if name in ("rename", "renameat", "renameat2", "symlink", "symlinkat", "link", "linkat"):
                        ss = _STR.findall(args)
                        if len(ss) > 1:
                            written.add(absify(pid, None, _unescape(ss[-1])))
    for d in [d for d in lists if d in written]:
        del lists[d]
    rw = set()
    for w in written:
        if first.get(w) == "r" and w in reads:
            rw.add(w)  # read (or opened read-write) before the run changed it: a dependency on the old content
        else:
            reads.pop(w, None)
        exists.discard(w)
        missing.discard(w)
    dropped = written - rw
    groups = {g: {k: (sorted(v - dropped) if k != "net" else sorted(list(x) for x in v)) for k, v in d.items()}
              for g, d in gdeps.items()}
    return {"groups": groups, "reads": reads, "rw": sorted(rw), "exists": sorted(exists - set(reads)),
            "missing": sorted(missing - exists - set(reads)),
            "lists": lists, "execs": execs, "net": net, "written": len(written), "lines": n}
