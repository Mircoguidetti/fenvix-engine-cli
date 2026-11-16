#!/usr/bin/env python3
"""Equivalence of two capture tracers on skip decisions.

Compares ``<out>/<repo>.json`` (coverage.py captures) with ``<out>/<repo><tag>.json`` (e.g. ``.sm``, the
sys.monitoring tracer), both written by ``analyze.py --skip-ids``: for every transition and every rule variant,
the sets of skipped tests must be identical. Also lists, for the second analysis, every skipped test whose
outcome on the full rerun at the new commit differs from the reused one, or is a failure (blocking errors).

    python harness/cache_skip/compare_skips.py --out <dir> [--tag .sm] repo1 repo2 ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def compare(out: Path, repo: str, tag: str, work: Path | None) -> dict:
    a = json.loads((out / f"{repo}.json").read_text())
    b = json.loads((out / f"{repo}{tag}.json").read_text())
    ta = {t["i"]: t for t in a["transitions"]}
    tb = {t["i"]: t for t in b["transitions"]}
    res = {"repo": repo, "transitions": 0, "evaluated": 0, "decisions": 0, "skipped_a": 0, "skipped_b": 0,
           "differences": [], "outcome_changed_b": 0, "failing_skipped_b": []}
    for i in sorted(set(ta) | set(tb)):
        x, y = ta.get(i, {}), tb.get(i, {})
        res["transitions"] += 1
        if x.get("status") == "not-evaluated" or y.get("status") == "not-evaluated" or "results" not in x:
            if (x.get("status") == "not-evaluated") != (y.get("status") == "not-evaluated"):
                res["differences"].append({"i": i, "what": "evaluated in one analysis only"})
            continue
        res["evaluated"] += 1
        for key in x["results"]:
            ra, rb = x["results"][key], y["results"].get(key, {})
            sa, sb = set(ra.get("skip_ids", ())), set(rb.get("skip_ids", ()))
            res["decisions"] += x.get("tests", 0)
            res["skipped_a"] += len(sa)
            res["skipped_b"] += len(sb)
            if sa != sb:
                res["differences"].append({"i": i, "sha": x.get("sha"), "rule": key,
                                           "only_coverage": sorted(sa - sb)[:10], "only_tag": sorted(sb - sa)[:10],
                                           "n_only_coverage": len(sa - sb), "n_only_tag": len(sb - sa)})
            res["outcome_changed_b"] += rb.get("outcome_changed", 0)
        if work is not None:
            # a skipped test whose full rerun at the new commit fails or errors (whatever it did before)
            cur = json.loads(next((work / repo / "caps").glob(f"{i:03d}-*.time.json")).read_text())["tests"]
            for key, rb in y["results"].items():
                for nid in rb.get("skip_ids", ()):
                    if cur.get(nid, {}).get("outcome") in ("failed", "error"):
                        res["failing_skipped_b"].append({"i": i, "rule": key, "test": nid})
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default=".sm")
    ap.add_argument("--work", default="", help="work directory of run_repo.py: also check failing skipped tests")
    ap.add_argument("repos", nargs="+")
    a = ap.parse_args(argv)
    bad = 0
    allres = []
    for repo in a.repos:
        r = compare(Path(a.out), repo, a.tag, Path(a.work).resolve() if a.work else None)
        allres.append(r)
        bad += len(r["differences"]) + len(r["failing_skipped_b"])
        print(f"{repo}: {r['evaluated']}/{r['transitions']} transitions, {r['decisions']} decisions over all rules, "
              f"skipped coverage {r['skipped_a']} / {a.tag} {r['skipped_b']}, differences {len(r['differences'])}, "
              f"skipped with changed outcome ({a.tag}) {r['outcome_changed_b']}, "
              f"skipped but failing on the full rerun ({a.tag}) {len(r['failing_skipped_b'])}")
        for d in r["differences"][:5]:
            print("   ", json.dumps(d)[:400])
        for d in r["failing_skipped_b"][:5]:
            print("    FAILING", json.dumps(d)[:300])
    Path(a.out, f"equivalence{a.tag}.json").write_text(json.dumps(allres, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
