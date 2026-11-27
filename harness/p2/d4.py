#!/usr/bin/env python3
"""P2 D4: is the shift towards `diverged` at fix-1 beyond the baseline engine's own range?

Per repository and w, over every round of both engines on the same boot (data/base-b = baseline engine, data/fix-1 =
fix engine), and the three rounds of the first boot (data/baseline, baseline engine):
  - per round: par wall s, verify `diverged` count, hazard re-run files (trace header meta.hazard_rerun);
  - the baseline engine's range of `diverged` over its rounds, and how many fix rounds fall above it;
  - "newly diverged": tests `diverged` in a fix round that the baseline engine never showed `diverged` in any of its
    rounds (both boots), per fix round, and the hazard re-runs they caused (a file is re-run only when a hazard names
    it, so a newly diverged test causes one only when its file is in meta.hazard_rerun.files).
Usage: d4.py --repo R [--repo R2 ...] [--json OUT]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import correctness  # noqa: E402

DATA = os.path.join(HERE, "data")


def rounds_of(d, n):
    out = []
    for i in range(1, 20):
        if os.path.exists(os.path.join(d, f"verify{i}w{n}.json")) or os.path.exists(os.path.join(d, f"verify{i}w{n}.json.gz")):
            out.append(i)
    return out


def header(path):
    """The trace's header line (the first line), read in chunks: it can be large."""
    with open(path, "rb") as f:
        buf = b""
        while True:
            c = f.read(1 << 20)
            if not c:
                break
            buf += c
            j = buf.find(b"\n")
            if j >= 0:
                buf = buf[:j]
                break
    return json.loads(buf)


def par_wall(d, i, n):
    p = os.path.join(os.path.dirname(d), "results.jsonl")
    repo = os.path.basename(d)
    if not os.path.exists(p):
        return None
    w = None
    for line in open(p):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("repo") == repo and o.get("kind") == "par" and o.get("rep") == i and o.get("workers") == n:
            w = o.get("wall_s")
    return w


def rerun_files(d, i, n):
    p = os.path.join(d, f"P{i}w{n}.jsonl")
    if not os.path.exists(p):
        return None
    m = (header(p).get("meta") or {}).get("hazard_rerun")
    return sorted(m["files"]) if m else []


def analyse(repo):
    dirs = {"baseline": os.path.join(DATA, "baseline", repo), "base-b": os.path.join(DATA, "base-b", repo),
            "fix-1": os.path.join(DATA, "fix-1", repo)}
    res = {"repo": repo, "w": {}}
    for n in correctness.WORKERS:
        per = {}
        for name, d in dirs.items():
            rows = []
            for i in rounds_of(d, n):
                cls = correctness.verify_classes(d, i, n) or {}
                rows.append({"round": i, "par_wall_s": par_wall(d, i, n),
                             "diverged": sum(1 for c in cls.values() if c == "diverged"),
                             "rerun_files": rerun_files(d, i, n), "_div": {k for k, c in cls.items() if c == "diverged"}})
            per[name] = rows
        base_rows = per["baseline"] + per["base-b"]
        ever = set().union(*[r["_div"] for r in base_rows]) if base_rows else set()
        lo = min(r["diverged"] for r in base_rows)
        hi = max(r["diverged"] for r in base_rows)
        lo_b = min(r["diverged"] for r in per["base-b"])
        hi_b = max(r["diverged"] for r in per["base-b"])
        base_rerun_sets = {tuple(r["rerun_files"] or []) for r in base_rows if r["rerun_files"] is not None}
        for r in per["fix-1"]:
            new = sorted(r["_div"] - ever)
            files = set(r["rerun_files"] or [])
            r["newly_diverged"] = len(new)
            r["newly_diverged_in_rerun_files"] = sum(1 for k in new if k.split("::", 1)[0] in files)
            r["rerun_files_seen_with_baseline_engine"] = tuple(r["rerun_files"] or []) in base_rerun_sets
        fix = [r["diverged"] for r in per["fix-1"]]
        res["w"][n] = {
            "rounds": {k: [{x: y for x, y in r.items() if x != "_div"} for r in v] for k, v in per.items()},
            "baseline_engine_range_all": [lo, hi], "baseline_engine_range_same_boot": [lo_b, hi_b],
            "fix_range": [min(fix), max(fix)],
            "fix_rounds_above_baseline_range_same_boot": sum(1 for x in fix if x > hi_b),
            "fix_rounds_above_baseline_range_all": sum(1 for x in fix if x > hi),
            "fix_rounds_below_baseline_range_same_boot": sum(1 for x in fix if x < lo_b),
        }
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    out = [analyse(r) for r in a.repo]
    for o in out:
        for n, x in o["w"].items():
            print(f"{o['repo']} w{n}: diverged baseline engine {x['baseline_engine_range_all']} (same boot "
                  f"{x['baseline_engine_range_same_boot']}), fix {x['fix_range']}, fix rounds above same-boot range "
                  f"{x['fix_rounds_above_baseline_range_same_boot']}/{len(x['rounds']['fix-1'])}, below "
                  f"{x['fix_rounds_below_baseline_range_same_boot']}")
            for k in ("baseline", "base-b", "fix-1"):
                for r in x["rounds"][k]:
                    extra = ""
                    if k == "fix-1":
                        extra = (f", newly diverged {r['newly_diverged']} (in re-run files {r['newly_diverged_in_rerun_files']})"
                                 f", re-run set seen with baseline engine {r['rerun_files_seen_with_baseline_engine']}")
                    print(f"  {k} r{r['round']}: par {r['par_wall_s']} s, diverged {r['diverged']}, "
                          f"hazard re-run files {None if r['rerun_files'] is None else len(r['rerun_files'])}{extra}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, default=list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
