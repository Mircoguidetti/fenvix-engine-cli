"""Map a test's channel set to one of the three buckets.

Rule E (primary): the engine's own controlled set is its own machinery, the interpreter and
its standard library, the system libraries the interpreter loads, and the *code* of the
installed packages in the virtualenv. Rationale: the engine pins the interpreter and runner
identity (`runtime`, `runner` inputs), precompiles stdlib and site-packages under the fixed
hash seed (`bytecode` control), and the environment is installed once and not written during
a run. Everything else that carries outside information into the test is unaccounted.

Rule S (sensitivity): only the engine's own machinery is controlled. The content of the
standard library and of the installed packages is not pinned by any input either, so reading
them is unaccounted too.
"""
from __future__ import annotations

import os

# Lookups: a stat / access / readlink of a directory or of a module path the import system
# or the runner walks. They carry existence, not content, and the cache design already
# models module lookups as a recorded input, so both rules treat them as controlled.
PROBES = ('stdlib_probe', 'syslib_probe', 'sitepackages_probe', 'project_probe', 'ancestor_probe', 'engine_probe', 'other_probe')

CONTROLLED_E = {"engine", "runner_cache", "stdlib", "syslib", "sitepackages_code",
                "locale_data", "null_dev", *PROBES}
CONTROLLED_S = {"engine", "runner_cache", "locale_data", "null_dev", *PROBES}

# category -> what the path is, for the cause label. The label also names *how* it was
# touched (content read / metadata stat / directory listing), because recording a content
# digest and recording a stat result are different pieces of work.
AREA = {
    "project_source": "a project source file",
    "project_data": "a project data file",
    "sitepackages_data": "an installed dependency's data file",
    "sitepackages_native": "a native extension file",
    "stdlib": "a standard library file",
    "syslib": "a system library file",
    "sitepackages_code": "an installed dependency's code",
    "runner_cache": "a runner bytecode cache file",
    "locale_data": "a locale or zoneinfo file",
    "tmp": "a temporary file",
    "proc": "/proc",
    "sys": "/sys",
    "etc": "a file under /etc",
    "home": "a file under the home directory",
    "dev": "a device file",
    "entropy_dev": "the OS entropy device",
    "other": "a file outside the engine's controlled set",
}
HOW = {"fs.read.": "content read of", "fs.stat.": "metadata read (stat) of",
       "fs.statfs.": "filesystem metadata read of", "fs.listdir.": "directory listing of"}

NON_VIRTUAL_CLOCKS = {
    "clock.rusage": "getrusage (CPU time, not virtualised)",
    "clock.times": "times (CPU time, not virtualised)",
    "clock.CLOCK_PROCESS_CPUTIME_ID": "process CPU clock read (not virtualised)",
    "clock.CLOCK_THREAD_CPUTIME_ID": "thread CPU clock read (not virtualised)",
    "clock.CLOCK_MONOTONIC": "real monotonic clock read not through the virtual clock",
    "clock.CLOCK_REALTIME": "real wall clock read not through the virtual clock",
    "clock.CLOCK_BOOTTIME": "boot clock read (not virtualised)",
    "clock.other": "clock read not through the virtual clock",
}

ACCOUNTED_ALWAYS = {
    "machine.uname",   # input `runtime` pins interpreter, version, platform, machine
    "tty.ioctl",       # terminal size / mode: pinned through env:TERM and env:COLUMNS inputs
    "net.socket",      # creating a socket carries nothing on its own
}


def classify(channels: dict, engine: dict, native_reads: list, rule: str = "E") -> tuple:
    """channels: {channel: count} summed over the phases that count.
    -> (bucket, [causes]) with bucket in PROVABLE / coverable / by-nature."""
    controlled = CONTROLLED_E if rule == "E" else CONTROLLED_S
    nature: list = []
    cover: list = []
    engine_entropy = bool(engine.get("sources", {}).get("entropy"))
    engine_net = bool(engine.get("sources", {}).get("net"))
    engine_fs = bool(engine.get("sources", {}).get("fs"))

    for ch, n in channels.items():
        if not n or ch in ACCOUNTED_ALWAYS or ch.startswith("fs.write."):
            continue
        if ch.startswith(tuple(HOW)):
            how = next(k for k in HOW if ch.startswith(k))
            cat = ch[len(how):]
            if cat in controlled:
                continue
            if cat == "entropy_dev" and engine_entropy:
                continue
            if how == "fs.listdir." and engine_fs:
                continue
            cover.append(f"{HOW[how]} {AREA.get(cat, cat)}")
        elif ch == "entropy.getrandom":
            if not engine_entropy:
                cover.append("getrandom with no engine entropy event")
        elif ch == "thread.create":
            nature.append("thread created during the run")
        elif ch in ("proc.child", "proc.exec"):
            nature.append("child process created")
        elif ch in NON_VIRTUAL_CLOCKS:
            cover.append(NON_VIRTUAL_CLOCKS[ch])
        elif ch in ("machine.sysinfo", "machine.cpu"):
            cover.append("machine state read (sysinfo / cpu affinity)")
        elif ch.startswith("net."):
            parts = ch.split(".")
            op, fam = parts[1], parts[-1]
            if op in ("connect", "recvfrom", "recvmsg", "sendmsg", "sendto", "accept", "accept4"):
                if fam == "inet" and engine_net:
                    continue  # blocked or replayed by --det, and recorded as a net event
                nature.append(f"live socket to another process ({fam})")
        # anything else: not information-carrying
    for p in native_reads:
        nature.append("file read by native code during the test (no Python-level open)")
        break
    if nature:
        return "NOT PROVEN, by nature", sorted(set(nature))
    if cover:
        return "NOT PROVEN, coverable", sorted(set(cover))
    return "PROVABLE", []


def native_reads(parsed: dict, audit: dict, paths_controlled) -> list:
    """Read-opens during the test phase with no Python-level open of the same file: made by
    native code. Compared on basenames, so a Python open counts even when the audit hook saw a
    relative path (conservative: it under-reports native reads)."""
    py = {os.path.basename(str(p)) for p in audit["opened"]["test"]}
    out = []
    for p in parsed["opened"]["test"]:
        if paths_controlled(p):
            continue
        if os.path.basename(p) not in py:
            out.append(p)
    return out
