"""Classify one `--det` run of one test into information-carrying channels.

Sensors (see docs/REPORT-measure-provable.md):
  * strace: the ground truth of the syscalls the run made.
  * the engine's own trace: the events `--det` recorded for the test, its `uncontrolled.*`
    marks and the header inputs.
  * an audit hook (harness/measure_provable/fenvix_sensor.py): the Python-level operations,
    used to tell a read made by Python from one made by native code.

The output is a per-test channel set. The three buckets are derived from it by rules
declared in BUCKET (Rule E, primary) and BUCKET_STRICT (Rule S, sensitivity).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# --- syscall line ---------------------------------------------------------------
LINE = re.compile(r"^(?P<pid>\d+)\s+(?P<rest>.*)$")
CALL = re.compile(r"^(?P<name>[a-z_0-9]+)\((?P<args>.*)$")
RESUMED = re.compile(r"^<\.\.\.\s+(?P<name>[a-z_0-9]+)\s+resumed>(?P<args>.*)$")
# first quoted string, and the fd<path> form strace -y prints
STR1 = re.compile(r'"((?:[^"\\]|\\.)*)"')
FDPATH = re.compile(r'^\s*(\d+)<(?P<p>[^>]*)>')
DIRFD = re.compile(r'^\s*(?:AT_FDCWD|\d+)<(?P<d>[^>]*)>')


def _abspath(p: str, args: str) -> str:
    """strace -y renders the dirfd as AT_FDCWD<dir> or N<dir>: resolve a relative path."""
    if not p or p.startswith("/"):
        return p
    m = DIRFD.match(args)
    if not m:
        return p
    d = m.group("d").rstrip("/")
    if p == ".":
        return d or p
    if p.startswith("./"):
        p = p[2:]
    return f"{d}/{p}" if d else p

READ_STAT = {"stat", "lstat", "statx", "newfstatat", "fstatat64", "access", "faccessat",
             "faccessat2", "readlink", "readlinkat", "statfs", "statfs64"}
OPENS = {"open", "openat", "openat2"}
WRITEY = {"mkdir", "mkdirat", "unlink", "unlinkat", "rename", "renameat", "renameat2",
          "chmod", "fchmodat", "chown", "fchownat", "symlink", "symlinkat", "link",
          "linkat", "rmdir", "truncate", "utimensat", "chdir", "fchdir", "getcwd",
          "umask", "mknod", "mknodat", "fallocate", "ftruncate"}
CHILD = {"fork", "vfork"}

# an open for reading of an extension-less path is a content read, not a lookup
PROBE_AS_FILE = {"stdlib_probe": "stdlib", "syslib_probe": "syslib",
                 "sitepackages_probe": "sitepackages_data", "project_probe": "project_data",
                 "ancestor_probe": "home", "other_probe": "other", "engine_probe": "engine"}

ENGINE_CHILD_MARKERS = ("detpy._prewarm", "git log -1", "--format=%ct", "detpy._pycompile")


def _unescape(s: str) -> str:
    return s.encode("latin-1", "backslashreplace").decode("unicode_escape", "replace")


class Paths:
    """Path -> category.

    Distinctions that matter:
      * a *file* (its basename has an extension) vs a *probe* of a directory or of a
        module path the import system / the runner looks up. A probe carries existence,
        not content, and the engine's cache design already models module lookups as an
        input, so probes get their own `*_probe` categories.
      * which area the path belongs to: the engine's own machinery, the interpreter and
        its standard library, system libraries, the installed packages, the project, or
        the machine's state (/proc, /sys, /etc, /dev, /tmp).
    """

    CONTROLLED = {"engine", "stdlib", "syslib", "sitepackages_code", "runner_cache",
                  "null_dev",
                  "locale_data", "stdlib_probe", "syslib_probe", "sitepackages_probe",
                  "project_probe", "ancestor_probe", "engine_probe", "other_probe"}

    def __init__(self, cfg: dict):
        self.project = cfg["project_src"].rstrip("/")
        self.site = [p.rstrip("/") for p in cfg["site_dirs"]]
        self.stdlib = [p.rstrip("/") for p in cfg["stdlib_dirs"]]
        self.venv = cfg["venv"].rstrip("/")
        self.engine_extra = [p.rstrip("/") for p in cfg.get("engine_dirs", [])]
        # strict ancestors of every root we know: stats of these are lookups walking up
        anc = set()
        for root in [self.project, self.venv, *self.site, *self.stdlib, *self.engine_extra]:
            parts = root.split("/")
            for i in range(2, len(parts)):
                anc.add("/".join(parts[:i]))
        anc.update({"/", "/home", "/usr", "/usr/local", "/usr/lib", "/usr/local/lib", "/root"})
        self.ancestors = anc

    @staticmethod
    def _is_file(p: str) -> bool:
        base = p.rsplit("/", 1)[-1]
        return "." in base[1:]

    def _under(self, p: str, d: str) -> bool:
        return p == d or p.startswith(d + "/")

    def cat(self, p: str) -> str:
        if not p:
            return "other"
        f = self._is_file(p)
        if p.startswith("/FENVIXMARK"):
            return "engine"
        for d in self.engine_extra:
            if self._under(p, d):
                return "engine" if f else "engine_probe"
        if "/.cache/detpy/" in p or "/.detpy/" in p or p.endswith(".detpy") \
                or ("fenvix-" in p and ".dist-info" in p):
            return "engine"
        if "/__pycache__/" in p:
            return "runner_cache"
        if "/.pytest_cache/" in p:
            return "runner_cache"
        if "/node_modules/" in p:
            if "/detjs/" in p:
                return "engine"
            if not f:
                return "sitepackages_probe"
            if p.endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".json", ".map")):
                return "sitepackages_code"
            if p.endswith(".node") or p.endswith(".so") or ".so." in p:
                return "sitepackages_native"
            return "sitepackages_data"
        if any(self._under(p, d) for d in self.site):
            if "/detpy/" in p or "/detjs/" in p:
                return "engine"
            if not f:
                return "sitepackages_probe"
            if p.endswith((".py", ".pyc", ".pth", ".pyi", ".egg-link")) \
                    or ".dist-info/" in p or ".egg-info/" in p:
                return "sitepackages_code"
            if p.endswith(".so") or ".so." in p or ".abi3.so" in p:
                return "sitepackages_native"
            return "sitepackages_data"
        for d in self.stdlib:
            if self._under(p, d):
                return "stdlib" if f else "stdlib_probe"
        if re.match(r"^/usr(/local)?/lib/python3\d*\.?\d*\.zip$", p):
            return "stdlib"
        if self._under(p, self.venv):
            return "stdlib" if f else "stdlib_probe"
        if self._under(p, self.project):
            tail = p[len(self.project) + 1:]
            if not f:
                return "project_probe"
            if tail.startswith(".git/"):
                return "project_data"
            if p.endswith((".py", ".pyc", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts",
                           ".tsx", ".jsx")):
                return "project_source"
            return "project_data"
        if p in self.ancestors:
            return "ancestor_probe"
        if p.startswith("/proc/"):
            return "proc"
        if p.startswith("/sys/"):
            return "sys"
        if p.startswith(("/dev/null", "/dev/zero", "/dev/full")):
            return "null_dev"
        if p.startswith(("/dev/urandom", "/dev/random")):
            return "entropy_dev"
        if p.startswith("/dev/"):
            return "dev"
        if p.startswith(("/usr/share/locale", "/usr/lib/locale", "/usr/share/zoneinfo")) \
                or p == "/etc/localtime":
            return "locale_data"
        if p.startswith("/etc/"):
            return "etc" if f else "other_probe"
        if p.startswith(("/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/", "/usr/libexec/",
                         "/usr/local/lib/", "/usr/bin/", "/bin/", "/usr/sbin/", "/sbin/",
                         "/usr/local/bin/", "/usr/local/sbin/", "/opt/")):
            return "syslib" if f else "syslib_probe"
        if p.startswith(("/tmp/", "/var/tmp/")):
            return "tmp" if f else "other_probe"
        if p.startswith(("/root/", "/home/")):
            return "home" if f else "ancestor_probe"
        return "other" if f else "other_probe"


RET = re.compile(r"=\s*(-?\d+)")


def _scan1(path: Path):
    """First pass: the main pid, the engine's own child pids, and where its bootstrap ends.

    The engine bootstraps itself before the run it measures: it precompiles the standard
    library and site-packages under the fixed hash seed (in a worker thread), runs
    `detpy._prewarm` as a child, and then re-executes the interpreter with the fixed hash
    seed and ASLR off. Everything up to and including that last re-exec is the engine's own
    machinery, not the test's, so the measurement window starts after it.
    """
    main_pid = None
    engine_pids = set()
    first_mark = None
    last_main_exec = -1
    for i, raw in enumerate(path.open(errors="replace")):
        m = LINE.match(raw)
        if not m:
            continue
        pid, rest = m.group("pid"), m.group("rest")
        if main_pid is None:
            main_pid = pid
        if first_mark is None and "/FENVIXMARK/" in rest:
            first_mark = i
        if rest.startswith(("execve(", "execveat(")):
            if any(k in rest for k in ENGINE_CHILD_MARKERS):
                engine_pids.add(pid)
            elif pid == main_pid and (first_mark is None or i < first_mark):
                last_main_exec = i
    return main_pid, engine_pids, last_main_exec


def parse_strace(path: Path, paths: Paths, spawns_before_test: bool = True,
                 infra_collection: frozenset = frozenset()) -> dict:
    """-> {'phases': {phase: {channel: count}}, 'opened': {phase: set(path)}, ...}

    Phases: `collection` (the real session's imports, collection and fixture setup),
    `test` (between the start and the end of the test), `after` (reporting and teardown).
    """
    main_pid, engine_pids, boot_end = _scan1(path)
    phase = "collection"
    pend: dict = {}
    out: dict = {"collection": {}, "test": {}, "after": {}}
    opened: dict = {"collection": set(), "test": set(), "after": set()}
    execs: list = []
    nat_so = set()
    engine_bootstrap = {"threads": 0, "children": 0}
    suppressed: dict = {}

    def bump(ch: str) -> None:
        # `infra_collection`: channels the runtime and the runner open in every run whatever
        # test is selected, measured by a baseline run in which no test runs at all. Before the
        # test body they are runner infrastructure, not something the test observed. File
        # channels are never suppressed this way.
        if phase == "collection" and ch in infra_collection and not ch.startswith("fs."):
            suppressed[ch] = suppressed.get(ch, 0) + 1
            return
        out[phase][ch] = out[phase].get(ch, 0) + 1

    with path.open(errors="replace") as fh:
        for i, raw in enumerate(fh):
            raw = raw.rstrip("\n")
            m = LINE.match(raw)
            if not m:
                continue
            pid, rest = m.group("pid"), m.group("rest")
            if rest.startswith("+++") or rest.startswith("---"):
                continue
            mr = RESUMED.match(rest)
            if mr:
                name = mr.group("name")
                args = pend.pop((pid, name), "") + mr.group("args")
            else:
                mc = CALL.match(rest)
                if not mc:
                    continue
                name, args = mc.group("name"), mc.group("args")
                if args.endswith("<unfinished ...>"):
                    pend[(pid, name)] = args[: -len("<unfinished ...>")]
                    continue
            if pid in engine_pids:
                continue
            in_boot = i <= boot_end
            if in_boot:
                if name in ("clone", "clone3") and "CLONE_THREAD" in args:
                    engine_bootstrap["threads"] += 1
                elif name in CHILD or name in ("clone", "clone3"):
                    engine_bootstrap["children"] += 1
                continue
            sm = STR1.search(args)
            s1 = _unescape(sm.group(1)) if sm else ""
            if s1.startswith("/FENVIXMARK/"):
                tag = s1.rsplit("/", 1)[-1]
                if tag == "W":
                    break   # the sensor's own write: the run is over for our purposes
                phase = {"S": "test", "E": "after"}.get(tag, phase)
                continue
            if name in OPENS:
                allp = STR1.findall(args)
                p = _abspath(_unescape(allp[0]) if allp else "", args)
                write_only = ("O_WRONLY" in args or "O_TRUNC" in args) and "O_RDWR" not in args
                cat = paths.cat(p)
                if cat.endswith("_probe") and "O_DIRECTORY" not in args:
                    cat = PROBE_AS_FILE.get(cat, cat)
                if cat in ("engine", "engine_probe"):
                    continue
                if write_only:
                    bump(f"fs.write.{cat}")
                else:
                    bump(f"fs.read.{cat}")
                    opened[phase].add(p)
                    if cat == "sitepackages_native" or (p.endswith(".so") and cat
                                                        not in ("syslib", "stdlib")):
                        nat_so.add(p)
            elif name in READ_STAT:
                cat = paths.cat(_abspath(s1, args))
                if cat in ("engine", "engine_probe"):
                    continue
                bump(f"fs.statfs.{cat}" if name.startswith("statfs") else f"fs.stat.{cat}")
            elif name == "getdents64":
                fm = FDPATH.match(args)
                cat = paths.cat(fm.group("p") if fm else "")
                if cat in ("engine", "engine_probe"):
                    continue
                bump(f"fs.listdir.{cat}")
            elif name in WRITEY:
                pass
            elif name == "getrandom":
                bump("entropy.getrandom")
            elif name in ("clone", "clone3", *CHILD):
                # `spawns_before_test=False`: the runtime and the runner always start threads
                # and workers of their own before the test body runs (Node's libuv pool, the
                # Vitest worker). Only spawns from the test phase on are attributed to the test.
                if not spawns_before_test and phase == "collection":
                    engine_bootstrap["threads" if "CLONE_THREAD" in args else "children"] += 1
                elif name in ("clone", "clone3") and "CLONE_THREAD" in args:
                    bump("thread.create")
                else:
                    r = RET.search(args[-40:])
                    if not (r and r.group(1) in engine_pids):
                        bump("proc.child")
            elif name in ("execve", "execveat"):
                execs.append((phase, s1))
                bump("proc.exec")
            elif name in ("wait4", "waitid", "waitpid"):
                pass
            elif name == "uname":
                bump("machine.uname")
            elif name == "sysinfo":
                bump("machine.sysinfo")
            elif name == "getrusage":
                bump("clock.rusage")
            elif name == "times":
                bump("clock.times")
            elif name in ("clock_gettime", "clock_gettime64"):
                clk = "other"
                for k in ("CLOCK_PROCESS_CPUTIME_ID", "CLOCK_THREAD_CPUTIME_ID",
                          "CLOCK_MONOTONIC", "CLOCK_REALTIME", "CLOCK_BOOTTIME"):
                    if k in args:
                        clk = k
                        break
                bump(f"clock.{clk}")
            elif name in ("sched_getaffinity", "getcpu"):
                bump("machine.cpu")
            elif name == "ioctl":
                bump("tty.ioctl")
            elif name in ("socket", "socketpair"):
                bump("net.socket")
            elif name in ("connect", "sendto", "recvfrom", "recvmsg", "sendmsg", "bind",
                          "accept", "accept4", "listen", "getpeername", "getsockname"):
                fam = "unix" if ("AF_UNIX" in args or "sun_path" in args) else (
                    "local" if ("127.0.0.1" in args or "::1" in args) else "inet")
                bump(f"net.{name}.{fam}")
    return {"phases": out, "opened": opened, "execs": execs, "native_so": sorted(nat_so),
            "engine_pids": sorted(engine_pids), "engine_bootstrap": engine_bootstrap,
            "infra_suppressed": suppressed,
            "bootstrap_end_line": boot_end}


def load_engine(trace: Path, nodeid: str) -> dict:
    """The engine's own record for this test."""
    rec = {"found": False, "sources": {}, "uncontrolled": [], "n_events": 0, "outcome": ""}
    if not trace.exists():
        return rec
    for ln in trace.open(errors="replace"):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("type") != "test":
            continue
        rec.update(found=True, sources=r.get("counts") or {},
                   uncontrolled=r.get("uncontrolled") or [],
                   n_events=r.get("n_events") or 0, outcome=r.get("outcome", ""))
    return rec


def load_audit(path: Path) -> dict:
    by = {"start": set(), "test": set(), "after": set()}
    kinds = {"start": set(), "test": set(), "after": set()}
    if not path.exists():
        return {"opened": by, "events": kinds}
    for ln in path.open(errors="replace"):
        parts = ln.rstrip("\n").split("\t")
        if len(parts) != 3:
            continue
        ph, ev, arg = parts
        ph = ph if ph in by else "start"
        kinds[ph].add(ev)
        if ev in ("open", "os.listdir", "os.scandir", "glob.glob") and arg:
            by[ph].add(arg)
    return {"opened": by, "events": kinds}
