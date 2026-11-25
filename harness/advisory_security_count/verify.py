#!/usr/bin/env python3
"""Re-derive the count from committed files; exit 1 on any mismatch.

Checks: (1) PREREG.md was committed before the first data file (git order); (2) the frame and the reading order
re-derive from the committed listing; (3) every label validates against the closed lists, labels form a prefix of
the reading order, and every included row's quote is a verbatim (whitespace-collapsed) substring of its stored
material — a row whose quote fails is counted `unclear` by the report and listed here; (4) the double-read sample
equals the seeded one; (5) every logged request is GET and none hits a search endpoint; (6) every <n><!--key--> in
REPORT.md equals the re-computed value and REPORT.md equals report.py's output byte for byte.
"""
from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import doubleread as DR  # noqa: E402
import fetch as F  # noqa: E402
import reading as RD  # noqa: E402
import report as REP  # noqa: E402
import rules as R  # noqa: E402

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print("MISMATCH", msg)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout


def check_prereg_first() -> None:
    def first_commit(path: str) -> str | None:
        out = git("log", "--diff-filter=A", "--format=%H %ct", "--reverse", "--", path).split("\n")
        return out[0] if out and out[0] else None

    pre = first_commit("PREREG.md")
    data = [first_commit(p) for p in ("data/budget.json", "data/listing_meta.json", "probe")]
    data = [d for d in data if d]
    if not pre:
        err("PREREG.md has no commit")
        return
    pre_t = int(pre.split()[1])
    for d in data:
        if int(d.split()[1]) < pre_t or git("merge-base", "--is-ancestor", pre.split()[0], d.split()[0]) is None:
            err(f"data commit {d} precedes PREREG.md")
    print("prereg commit", pre.split()[0][:7], "precedes", len(data), "first data commits")


def check_frame() -> None:
    frame = F.frame_rows(F.load_listing())
    committed = [json.loads(x) for x in gzip.open(F.DATA / "frame.jsonl.gz", "rt")]
    if frame != committed:
        err("frame.jsonl.gz does not re-derive from the listing")
    order = R.reading_order([r["ghsa_id"] for r in frame if r["route"]])
    if order != RD.order():
        err("order.json does not re-derive from the frame")


def check_labels() -> None:
    labs, order, mats = RD.load_labels(), RD.order(), F.load_material()
    read = [g for g in order if g in labs]
    if read != order[:len(read)] or len(read) != len(labs):
        err("labels are not exactly a prefix of the reading order")
    for g in read:
        for e in R.validate_label(labs[g]):
            err(f"{g}: {e}")
        if labs[g]["inclusion"] == "included" and not R.quote_ok(labs[g]["quote"], R.material_text(mats[g])):
            print("quote not verbatim (row counted unclear):", g)
    for g, lab in DR.load2(REP.CHECKPOINT).items():
        for e in R.validate_label(lab):
            err(f"second reader {g}: {e}")


def check_sample() -> None:
    p = DR.cp_dir(REP.CHECKPOINT) / "input.jsonl"
    if not p.exists():
        return
    ids = [json.loads(x)["ghsa_id"] for x in p.read_text().splitlines() if x.strip()]
    if ids != R.double_read_input_order(DR.sample(REP.CHECKPOINT)):
        err("double-read input is not the seeded sample in Random(7) order")


def check_requests() -> None:
    for p in sorted(F.DATA.glob("requests*.jsonl")):
        for r in REP.read_jsonl(p):
            if r["method"] != "GET" or "/search/" in r["path"]:
                err(f"{p.name}: forbidden request {r['method']} {r['path']}")


def check_report() -> None:
    v = REP.compute()
    expected = REP.render(v)
    txt = (HERE / "REPORT.md").read_text()
    keys = re.findall(r"([^\s(>]+?)<!--([a-z0-9_A-Z-]+)-->", txt)
    if not keys:
        err("REPORT.md has no keyed numbers")
    for val, key in keys:
        if key not in v:
            err(f"REPORT.md key {key} unknown")
        elif str(v[key]) != val:
            err(f"REPORT.md {key}: {val} != re-computed {v[key]}")
    if txt != expected:
        err("REPORT.md differs from report.py output")
    print(len(keys), "keyed numbers checked; first line:", txt.splitlines()[0])


def main() -> None:
    check_prereg_first()
    check_frame()
    check_labels()
    check_sample()
    check_requests()
    check_report()
    if errors:
        print(len(errors), "mismatch(es)")
        sys.exit(1)
    print("verify: OK")


if __name__ == "__main__":
    main()
