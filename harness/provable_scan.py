#!/usr/bin/env python3
"""What the accounting table refuses, listed by shape, so a red does not have to come from CI one name at a time.

The `_thread.lock` red (CI 44959416348) was a TYPE whose methods the table listed and whose construction it did
not: `threading.Lock` IS the class `_thread.lock`, so the sensor reported the type's name and every test that took
a lock came out NOT PROVEN. This script asks the table about every callable of the modules it enumerates and sorts
the refusals into types and functions, which is the list of channels to cover later that the closing rule asks for
(DECISIONS 2026-11-21: "a channel where the engine answers NOT PROVEN is not a defect; it goes on a list").

    python3 harness/provable_scan.py              # the two lists
    python3 harness/provable_scan.py --types      # only the types (the `_thread.lock` shape)

A refusal here is NOT a defect: it is a test the customer cannot skip or spread across cores, which is the cost
the rule is paid in. A refusal that an ORDINARY test reaches is worth covering; `posix.setresuid` is not.
"""

from __future__ import annotations

import argparse
import importlib
import inspect

from detpy import _core

# The modules the table enumerates (crates/detpy-core/src/provable.rs, `module_policy`): anything outside this set
# is Unknown, which is refused as a whole and needs no scan.
ENUMERATED = [
    "builtins", "posix", "time", "_io", "_socket", "_thread", "_random", "select", "_sqlite3", "sys", "gc",
    "resource", "_imp", "marshal", "zipimport", "_warnings", "atexit", "_tracemalloc", "faulthandler",
    "_tokenize", "_locale", "_ssl", "fcntl", "termios", "mmap", "signal", "_posixsubprocess", "_multiprocessing",
    "pwd", "grp", "syslog", "_uuid",
]


def scan() -> tuple[list[str], list[str]]:
    types_, funcs = [], []
    for m in ENUMERATED:
        try:
            mod = importlib.import_module(m)
        except Exception:
            continue   # not on this platform or this build
        for n in sorted(dir(mod)):
            if n.startswith("__"):
                continue
            obj = getattr(mod, n, None)
            if not callable(obj):
                continue
            if _core.provable_account(m, n) == "unaccounted":
                (types_ if inspect.isclass(obj) else funcs).append(f"{m}.{n}")
    return types_, funcs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", action="store_true", help="only the types")
    a = ap.parse_args()
    types_, funcs = scan()
    print(f"types the table refuses: {len(types_)}")
    for x in types_:
        print(f"  {x}")
    if a.types:
        return
    print(f"\nfunctions the table refuses: {len(funcs)}")
    for x in funcs:
        print(f"  {x}")


if __name__ == "__main__":
    main()
