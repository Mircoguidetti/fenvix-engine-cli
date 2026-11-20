#!/usr/bin/env python3
"""Review R-022b: docs/JVM.md describes the skip rule and the limits as they are after the R-022 fixes.

REPORT-2 (sessions/2026-11-18-jvm-l0) says the decider is now Rust (crates/fenvix-skip), that the
shared-state rule decides reuse of tests that read mutable static state, that processes and project
native code make a test not reusable, that D5's residual (the virtual scheduler's real-time fallback
under load) is a Level 1 limit "documented with the test", and lists inputs that are still not keyed.
The user-facing documentation of the JVM shell is docs/JVM.md (section "Skip with proof", limits
V1-V18). Each check below greps it for one of these statements. Exit 1 when one is missing.

  python3 jvm/test/check_r022b_docs.py
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "JVM.md")

CHECKS = [
    ("decider is crates/fenvix-skip (not fenvix_skip.py)", r"fenvix-skip"),
    ("shared-state rule (mutable static reads, order in B)", r"(?i)shared[- ]state|mutable static"),
    ("child processes / project native code: not reusable", r"(?is)skip with proof.*(ProcessBuilder|child process).{0,200}not reusable"),
    ("class lookups (Class.forName) and getResources in the key", r"(?i)forName|getResources"),
    ("D5: virtual scheduler real-time fallback under load (limit)", r"(?i)real[- ]time fallback|fallback.{0,80}(load|real time)"),
    ("inputs still not keyed (Locale/TimeZone defaults, JDK global state)", r"(?i)not keyed|Locale\.setDefault"),
]


def main():
    text = open(DOC).read()
    ok = True
    for name, rx in CHECKS:
        hit = re.search(rx, text) is not None
        ok &= hit
        print(f"{'ok ' if hit else 'BAD'} {name}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
