#!/usr/bin/env python3
"""R-019c, item 4: compare the reviewer's re-runs (``SAMPLE_DIR``) with the committed round-4 rows.

    python3 compare_sample.py RESULTS_DIR SAMPLE_DIR [--json OUT]

Per case: the committed answer (named commit or input, or unknown with its suspect) against the re-run's, plus
executions. Correctness is recomputed against the row's truth.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rederive as R  # noqa: E402


def answer(kind, r):
    if kind == "d":
        return r.get("finder_named"), R.suspect(r.get("red_side")), r.get("executions")
    fd = r.get("finder") or {}
    return R.named_of(fd), R.suspect(fd.get("why")), fd.get("executions")


def main(res, sample, out=None):
    committed = {}
    for k, i, r, _ in R.load(res):
        committed[(k.split()[0], i)] = (k, r)
    rows = []
    for p in sorted(glob.glob(os.path.join(sample, "*.jsonl"))):
        base = os.path.basename(p)
        kind = "a2" if base.startswith("a-") else "b" if base.startswith("b-") else "d" if base.startswith("d-") \
            else "c"
        for l in open(p):
            if not l.strip():
                continue
            r = json.loads(l)
            i = f"{r['repo']}|{r['victim']}|{r['config']}" if kind == "d" else r["id"]
            ck, cr = committed[(kind, i)]
            a, b = answer(ck, cr), answer(ck, r)
            ok_now = b[0] is not None and b[0] == r["truth"]
            rows.append({"kind": ck, "id": i, "committed": a[0], "rerun": b[0], "same_answer": a[0] == b[0],
                         "committed_suspect": a[1], "rerun_suspect": b[1], "rerun_right": ok_now,
                         "rerun_wrong": b[0] is not None and not ok_now, "exec_committed": a[2], "exec_rerun": b[2]})
    for x in rows:
        print(f"{x['kind']:12s} {x['id'][:60]:60s} same={x['same_answer']!s:5s} right={x['rerun_right']!s:5s} "
              f"wrong={x['rerun_wrong']!s:5s} exec {x['exec_committed']}->{x['exec_rerun']}")
    n = len(rows)
    print(f"cases {n}; same answer {sum(x['same_answer'] for x in rows)}; re-run stated "
          f"{sum(x['rerun'] is not None for x in rows)}, right {sum(x['rerun_right'] for x in rows)}, "
          f"wrong {sum(x['rerun_wrong'] for x in rows)}; same executions "
          f"{sum(x['exec_committed'] == x['exec_rerun'] for x in rows)}")
    if out:
        json.dump(rows, open(out, "w"), indent=1)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[3] if len(a) > 3 and a[2] == "--json" else None)
