"""REPORT-3 tables from a run's results directory (tracks/parallel-proof/results/<run_id>/).

Walks (``*-walk50-s<k>/walk.json``): per repository, every shard's commits, cold commits (the shard's first) apart.
Reuse by test time = sum of the truth run's per-test time of the reused tests / sum over all tests of the truth run.
Usage: python report3_tables.py RESULTS_DIR
"""

import collections
import glob
import json
import os
import sys


def walks(root: str) -> str:
    by_repo = collections.defaultdict(list)
    for p in sorted(glob.glob(os.path.join(root, "*-walk50-s*", "walk.json"))):
        name = os.path.basename(os.path.dirname(p)).rsplit("-walk50-", 1)[0]
        d = json.load(open(p))
        for c in d["commits"]:
            by_repo[name].append((os.path.basename(os.path.dirname(p)), c))
    out = ["| repository | shards | commits (warm) | tests per commit | reused, warm commits (count) | reused by test "
           "time, warm commits | commits with >= 50 % reused | wrong reuses | flaky rechecks | carried / recorded | "
           "a_par wall s (warm median) | truth wall s (median) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for repo, rows in sorted(by_repo.items()):
        shards = sorted({s for s, _ in rows})
        warm = [c for _, c in rows if not c.get("shard_first")]
        tests = [c["a_par"]["tests"] for _, c in rows if "a_par" in c]
        reused = sum(c["a_par"]["reused"] for c in warm)
        total = sum(c["a_par"]["tests"] for c in warm)
        rt = sum(c["a_par"].get("reused_time_s", 0) for c in warm)
        tt = sum(c["b"].get("test_time_s", 0) for c in warm)
        half = sum(1 for c in warm if c["a_par"]["tests"] and c["a_par"]["reused"] >= 0.5 * c["a_par"]["tests"])
        wrong = sum(len(c["a_par"].get("wrong_reuses", [])) for _, c in rows)
        flaky = sum(len(c["a_par"].get("flaky", [])) for _, c in rows)
        car = sum(c["a_par"].get("carried_of_recorded", 0) for _, c in rows)
        rec = sum(c["a_par"].get("recorded", 0) or 0 for _, c in rows)
        walls = sorted(c["a_par"]["wall_s"] for c in warm)
        bw = sorted(c["b"]["wall_s"] for _, c in rows)
        med = lambda v: v[len(v) // 2] if v else None  # noqa: E731
        out.append(f"| {repo} | {len(shards)} | {len(rows)} ({len(warm)}) | {min(tests)}-{max(tests)} | "
                   f"{reused} of {total} ({100 * reused / max(total, 1):.1f} %) | {100 * rt / max(tt, 1e-9):.1f} % | "
                   f"{half} of {len(warm)} | {wrong} | {flaky} | {car} / {rec} | {med(walls)} | {med(bw)} |")
    return "\n".join(out)


def per_commit(root: str, repo: str) -> str:
    out = ["| shard | commit | sha | reused | ran | recorded | reused by time | miss reasons | wrong |",
           "|---|---|---|---|---|---|---|---|---|"]
    for p in sorted(glob.glob(os.path.join(root, f"{repo}-walk50-s*", "walk.json"))):
        s = os.path.basename(os.path.dirname(p)).rsplit("-", 1)[1]
        for c in json.load(open(p))["commits"]:
            a = c["a_par"]
            tt = c["b"].get("test_time_s") or 0
            out.append(f"| {s} | {c['i']} | {c['sha'][:8]} | {a['reused']} | {a['ran']} | {a['recorded']} | "
                       f"{100 * a.get('reused_time_s', 0) / max(tt, 1e-9):.0f} % | {a.get('miss_reasons')} | "
                       f"{len(a.get('wrong_reuses', []))} |")
    return "\n".join(out)


if __name__ == "__main__":
    root = sys.argv[1]
    print(walks(root))
    for repo in sys.argv[2:]:
        print()
        print(per_commit(root, repo))
