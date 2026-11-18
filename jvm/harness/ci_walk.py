#!/usr/bin/env python3
"""Matrix of (repository, shard) for the skip walk; aggregate of the shards."""
import glob, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def matrix(names, shards):
    m = [f"{n}:{k}" for n in names.split(",") for k in range(shards)]
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
        f.write(f"matrix={json.dumps(m)}\n")


def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def aggregate(d):
    L = ["# Skip with proof on Java/Kotlin repositories (JVM shell)\n",
         "Every commit's whole suite ran with the capture on (`--det --deps`); each reuse decided by the proof rule from the "
         "previous commit's capture was checked against that commit's fresh outcome. MEASURED on GitHub-hosted runners. "
         "The per-module column is an ESTIMATED model of Gradle's build cache for test tasks (a module's tests are reused "
         "only when every output file of the module and its jar list are unchanged; per task, not per test).\n",
         "| repository | tool | transitions | tests (median) | time skipped with proof, median / mean | tests skipped, median | "
         "verified reuses | wrong | flaky | per-module cache model: time skipped, median / mean | top rerun reasons |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    tot = {"verified": 0, "wrong": 0, "flaky": 0}
    out = {}
    for repo_dir in sorted(glob.glob(os.path.join(d, "*"))):
        shards = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(repo_dir, "shard*.json")))]
        if not shards:
            continue
        rows = [r for s in shards for r in s["rows"] if r.get("prev")]
        seen, uniq = set(), []
        for r in rows:
            if (r["prev"], r["sha"]) not in seen:
                seen.add((r["prev"], r["sha"]))
                uniq.append(r)
        rows = uniq
        if not rows:
            continue
        sh = [r["share_time_skipped"] for r in rows if r.get("share_time_skipped") is not None]
        st = [r["share_tests_skipped"] for r in rows if r.get("share_tests_skipped") is not None]
        mc = [r["module_cache_share_time"] for r in rows if r.get("module_cache_share_time") is not None]
        ver = sum(r["verified"] for r in rows)
        wrong = sum(len(r["wrong"]) for r in rows)
        flaky = sum(len(r["flaky"]) for r in rows)
        reasons = {}
        for r in rows:
            for k, v in r.get("rerun_reasons", {}).items():
                reasons[k] = reasons.get(k, 0) + v
        top = ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:4])
        tot["verified"] += ver
        tot["wrong"] += wrong
        tot["flaky"] += flaky
        name = os.path.basename(repo_dir)
        tool = shards[0]["spec"]["tool"]
        tests = statistics.median([r["tests"] for r in rows])
        L.append(f"| {name} | {tool} | {len(rows)} | {tests:.0f} | **{pct(statistics.median(sh) if sh else None)} / "
                 f"{pct(statistics.mean(sh) if sh else None)}** | {pct(statistics.median(st) if st else None)} | {ver} | {wrong} | {flaky} | "
                 f"{pct(statistics.median(mc) if mc else None)} / {pct(statistics.mean(mc) if mc else None)} | {top} |")
        out[name] = {"transitions": len(rows), "median": statistics.median(sh) if sh else None, "mean": statistics.mean(sh) if sh else None,
                     "verified": ver, "wrong": wrong, "flaky": flaky, "module_cache_median": statistics.median(mc) if mc else None,
                     "module_cache_mean": statistics.mean(mc) if mc else None, "reasons": reasons}
    L.append(f"\nVerified reuses: {tot['verified']}; wrong: **{tot['wrong']}**; flaky (failed fresh, passed and failed on reruns): {tot['flaky']}.\n")
    open(os.path.join(d, "REPORT.md"), "w").write("\n".join(L) + "\n")
    json.dump({"repos": out, "totals": tot}, open(os.path.join(d, "summary.json"), "w"), indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    if sys.argv[1] == "matrix":
        matrix(sys.argv[2], int(sys.argv[3]))
    else:
        aggregate(sys.argv[2])
