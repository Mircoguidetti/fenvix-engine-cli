#!/usr/bin/env python3
"""Re-derive every count in REPORT.md from scan.jsonl (and raw/search_log.jsonl for the
search-level table) and exit non-zero on any mismatch or structural violation.

REPORT.md carries its counts in a block:
    <!-- counts:begin -->
    key = value
    <!-- counts:end -->
Every key in that block must equal the value computed here, and every computed key must be
in the block.

Usage:
  python3 harness/serial_scan/verify_scan.py            # verify REPORT.md
  python3 harness/serial_scan/verify_scan.py --print    # print the computed block
"""
import collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("stated", "implied", "none")


def load():
    return [json.loads(l) for l in open(os.path.join(HERE, "scan.jsonl"))]


def structural(rows):
    errs = []
    seen = set()
    for r in rows:
        if r["repo"] in seen:
            errs.append(f"{r['repo']}: duplicate row")
        seen.add(r["repo"])
        if r["running_serially"]:
            if r["reason_kind"] not in KINDS:
                errs.append(f"{r['repo']}: serial row with reason_kind {r['reason_kind']!r}")
            if not (r["commit"] and r["file"] and r["line"] and r["verbatim_line"]):
                errs.append(f"{r['repo']}: serial row without commit/file/line/verbatim_line")
        else:
            if r["reason_kind"] is not None or r["multi_core_runner"]:
                errs.append(f"{r['repo']}: non-serial row with reason_kind or multi_core_runner set")
        if r["reason_kind"] == "stated":
            if not (r["reason_quote"] and r["reason_file"] and r["reason_line"]):
                errs.append(f"{r['repo']}: stated without verbatim quote and file:line")
            if r["reason_category"] not in ("breakage", "resource", "other"):
                errs.append(f"{r['repo']}: stated without reason_category")
        elif r["reason_quote"]:
            errs.append(f"{r['repo']}: reason_quote on a non-stated row")
    return errs


def file_kind(path):
    b = os.path.basename(path).lower()
    if b == "package.json":
        return "package.json"
    if path.startswith(".github/workflows/"):
        return "workflow"
    if b in ("makefile", "gnumakefile", "justfile") or b.endswith(".mk"):
        return "makefile"
    if re.search(r"(jest|vitest|vite|playwright|ava)\.[\w.]*config|config\.[cm]?[jt]s$|pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|conftest\.py", b):
        return "test_config"
    return "other"


def compute(rows):
    c = collections.OrderedDict()
    serial = [r for r in rows if r["running_serially"]]
    mc = [r for r in serial if r["multi_core_runner"]]
    c["repositories_examined"] = len(rows)
    c["repositories_examined_readable"] = sum(1 for r in rows if r["readable"])
    c["repositories_running_serially"] = len(serial)
    for k in KINDS:
        c[f"serial.{k}"] = sum(1 for r in serial if r["reason_kind"] == k)
    for cat in ("breakage", "resource", "other"):
        c[f"serial.stated.{cat}"] = sum(1 for r in serial if r["reason_kind"] == "stated" and r["reason_category"] == cat)
    c["serial_on_multi_core_runner"] = len(mc)
    for k in KINDS:
        c[f"multi_core.{k}"] = sum(1 for r in mc if r["reason_kind"] == k)
    for cat in ("breakage", "resource", "other"):
        c[f"multi_core.stated.{cat}"] = sum(1 for r in mc if r["reason_kind"] == "stated" and r["reason_category"] == cat)
    nps = [r for r in serial if not r["playwright_scaffold_default"]]
    c["serial.playwright_scaffold_default"] = len(serial) - len(nps)
    c["serial_excluding_playwright_scaffold"] = len(nps)
    for k in KINDS:
        c[f"serial_excluding_playwright_scaffold.{k}"] = sum(1 for r in nps if r["reason_kind"] == k)
    mcn = [r for r in mc if not r["playwright_scaffold_default"]]
    c["multi_core_excluding_playwright_scaffold"] = len(mcn)
    c["multi_core_excluding_playwright_scaffold.stated.breakage"] = sum(
        1 for r in mcn if r["reason_kind"] == "stated" and r["reason_category"] == "breakage")
    for src in ("same_file", "doc", "commit_message"):
        c[f"serial.stated.source.{src}"] = sum(1 for r in serial if r["reason_kind"] == "stated" and r["reason_source"] == src)
    lines = collections.Counter((os.path.basename(r["file"]), r["verbatim_line"].strip()) for r in serial)
    c["serial.rows_sharing_identical_flag_line_with_another_repo"] = sum(
        1 for r in serial if lines[(os.path.basename(r["file"]), r["verbatim_line"].strip())] > 1)
    for kind in ("package.json", "workflow", "makefile", "test_config", "other"):
        ks = [r for r in serial if file_kind(r["file"]) == kind]
        c[f"file_kind.{kind}.serial"] = len(ks)
        for k in KINDS:
            c[f"file_kind.{kind}.{k}"] = sum(1 for r in ks if r["reason_kind"] == k)
    # sampling arm: repositories reached only through flag-alone queries vs through any
    # flag+reason-word query (the latter over-samples suites that state a reason)
    qkind = {}
    for l in open(os.path.join(HERE, "raw", "search_log.jsonl")):
        s = json.loads(l)
        qkind[s["query"]] = s["kind"]
    for arm in ("flag_only", "flag_word"):
        def in_arm(r):
            kinds = {qkind[q] for q in (r["search_queries"] or [])}
            return ("flag+word" in kinds) == (arm == "flag_word")
        a = [r for r in serial if in_arm(r)]
        am = [r for r in a if r["multi_core_runner"]]
        c[f"arm.{arm}.examined"] = sum(1 for r in rows if in_arm(r))
        c[f"arm.{arm}.serial"] = len(a)
        for k in KINDS:
            c[f"arm.{arm}.serial.{k}"] = sum(1 for r in a if r["reason_kind"] == k)
        c[f"arm.{arm}.serial.stated.breakage"] = sum(1 for r in a if r["reason_kind"] == "stated" and r["reason_category"] == "breakage")
        c[f"arm.{arm}.multi_core"] = len(am)
        for k in KINDS:
            c[f"arm.{arm}.multi_core.{k}"] = sum(1 for r in am if r["reason_kind"] == k)
        c[f"arm.{arm}.multi_core.stated.breakage"] = sum(1 for r in am if r["reason_kind"] == "stated" and r["reason_category"] == "breakage")
    runners = sorted({r["runner"] for r in rows if r["runner"]})
    for ru in runners:
        rs = [r for r in serial if r["runner"] == ru]
        c[f"runner.{ru}.examined"] = sum(1 for r in rows if r["runner"] == ru)
        c[f"runner.{ru}.serial"] = len(rs)
        for k in KINDS:
            c[f"runner.{ru}.{k}"] = sum(1 for r in rs if r["reason_kind"] == k)
        c[f"runner.{ru}.multi_core"] = sum(1 for r in rs if r["multi_core_runner"])
        c[f"runner.{ru}.multi_core.stated.breakage"] = sum(
            1 for r in rs if r["multi_core_runner"] and r["reason_kind"] == "stated" and r["reason_category"] == "breakage")
    nsr = collections.Counter(r["not_serial_reason"] or r["error"] for r in rows if not r["running_serially"])
    for i, (k, v) in enumerate(sorted(nsr.items(), key=lambda x: (-x[1], str(x[0])))):
        c[f"not_serial[{k}]"] = v
    # search-level (GitHub total_count, DECLARED by GitHub; re-derived from the raw log)
    for l in open(os.path.join(HERE, "raw", "search_log.jsonl")):
        s = json.loads(l)
        if s["page"] == 1:
            c[f"search[{s['runner']}|{s['kind']}|{s['query']}]"] = s["total_count"]
    return c


def block(c):
    return "\n".join(f"{k} = {v}" for k, v in c.items())


def main():
    rows = load()
    c = compute(rows)
    if "--print" in sys.argv:
        print(block(c))
        return 0
    errs = structural(rows)
    rep = open(os.path.join(HERE, "REPORT.md")).read()
    m = re.search(r"<!-- counts:begin -->\n(.*?)\n<!-- counts:end -->", rep, re.S)
    if not m:
        errs.append("REPORT.md has no counts block")
    else:
        got = {}
        for ln in m.group(1).splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("```"):
                continue
            k, _, v = ln.rpartition(" = ")
            got[k] = v
        for k, v in c.items():
            if k not in got:
                errs.append(f"REPORT.md missing count {k}")
            elif got[k] != str(v):
                errs.append(f"REPORT.md {k} = {got[k]} but scan.jsonl gives {v}")
        for k in got:
            if k not in c:
                errs.append(f"REPORT.md has count {k} that verify_scan.py does not derive")
        # headline numbers quoted in prose must match too
        for key in c:
            tag = f"<!--{key}-->"
            for mm in re.finditer(re.escape(tag) + r"\*{0,2}(\d+)", rep):
                if mm.group(1) != str(c[key]):
                    errs.append(f"REPORT.md prose {key} = {mm.group(1)} but scan.jsonl gives {c[key]}")
    if errs:
        for e in errs:
            print("MISMATCH:", e)
        return 1
    print(f"OK: {len(c)} counts in REPORT.md re-derived from scan.jsonl; structural checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
