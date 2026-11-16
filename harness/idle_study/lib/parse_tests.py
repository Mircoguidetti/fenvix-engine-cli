#!/usr/bin/env python3
"""Per-test outcomes of one run.

usage: parse_tests.py KIND RESULTS_DIR TEST_LOG OUT.json
KIND: junit   - every *.xml under RESULTS_DIR (pytest, vitest, playwright, mocha xunit, cypress)
      django  - the verbose (-v 2) unittest/Django output in TEST_LOG
      jest    - every *.json under RESULTS_DIR written by `jest --json`
Output: {"tests": {test_id: {"s": "pass"|"fail"|"skip", "m": message-or-""}}, "parser": KIND}
"""
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

kind, rdir, log, out = sys.argv[1:5]
tests = {}
RANK = {"skip": 0, "pass": 1, "fail": 2}


def put(tid, status, msg=""):
    old = tests.get(tid)
    if old is None or RANK[status] > RANK[old["s"]]:
        tests[tid] = {"s": status, "m": (msg or "")[:1500]}
    elif status == old["s"] and msg and not old["m"]:
        old["m"] = msg[:1500]


def parse_junit():
    for path in sorted(glob.glob(os.path.join(rdir, "**", "*.xml"), recursive=True)):
        try:
            root = ET.parse(path).getroot()
        except Exception:
            continue
        suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
        for suite in suites:
            host = suite.get("hostname") or ""
            host = "" if host in ("", "localhost") or "." in host else host
            for tc in suite.findall("testcase"):
                cls = tc.get("classname") or suite.get("name") or ""
                tid = f"{host + '|' if host else ''}{cls}::{tc.get('name')}"
                fail = tc.find("failure")
                if fail is None:
                    fail = tc.find("error")
                if fail is not None:
                    msg = (fail.get("message") or "") + "\n" + (fail.text or "")
                    put(tid, "fail", msg.strip())
                elif tc.find("skipped") is not None:
                    put(tid, "skip")
                else:
                    put(tid, "pass")


def parse_django():
    try:
        txt = open(log, errors="replace").read()
    except OSError:
        return
    txt = re.sub(r"\x1b\[[0-9;]*m", "", txt)
    pat = re.compile(
        r"^(test\w*) \(([\w.]+)\)(?:\n[^\n]*?)?\s\.\.\.\s(ok|FAIL|ERROR|skipped|expected failure|unexpected success)",
        re.M,
    )
    for m in pat.finditer(txt):
        name, where, res = m.groups()
        tid = where if where.endswith("." + name) else f"{where}.{name}"
        if res in ("ok", "expected failure"):
            put(tid, "pass")
        elif res == "skipped":
            put(tid, "skip")
        else:
            put(tid, "fail")
    # failure details
    blk = re.compile(r"^(?:FAIL|ERROR): (test\w*) \(([\w.]+)\)[^\n]*\n-{20,}\n(.*?)(?=^={20,}|^-{20,}|\Z)", re.M | re.S)
    for m in blk.finditer(txt):
        name, where, body = m.groups()
        tid = where if where.endswith("." + name) else f"{where}.{name}"
        lines = [l for l in body.strip().splitlines() if l.strip()]
        msg = "\n".join(lines[-12:])
        put(tid, "fail", msg)


def parse_jest():
    for path in sorted(glob.glob(os.path.join(rdir, "**", "*.json"), recursive=True)):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        for tr in d.get("testResults", []):
            f = os.path.relpath(tr.get("name", ""), os.getcwd())
            for a in tr.get("assertionResults", []):
                tid = f"{f}::{a.get('fullName')}"
                st = a.get("status")
                if st == "passed":
                    put(tid, "pass")
                elif st == "failed":
                    put(tid, "fail", "\n".join(a.get("failureMessages") or []))
                else:
                    put(tid, "skip")


{"junit": parse_junit, "django": parse_django, "jest": parse_jest}[kind]()
with open(out, "w") as f:
    json.dump({"parser": kind, "tests": tests}, f)
print(f"parsed {len(tests)} tests ({sum(1 for t in tests.values() if t['s'] == 'fail')} failed)")
