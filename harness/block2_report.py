"""Block 2 report: detpy explore + repro vs pytest-randomly seeds (P-010 items 3 and 4).

    python harness/block2_report.py harness/results/block2

Reads <repo>.detpy.block2.json and <repo>.randomly.block2.json and writes REPORT.md,
per-target.csv and summary.json in the same directory.

Definitions
  found within K (detpy)    the target failed in a whole-suite run with some seed 1..K, AND
                            `repro` turned it into a bundle whose --confirm replays all fail with
                            one fingerprint.
  failed within K (both)    the target failed in a whole-suite run with some seed 1..K.
  replays (randomly)        the whole suite re-run --confirm times with the target's first failing
                            --randomly-seed; replays 10/10 when every re-run fails the target.
  cost of K (detpy)         seconds of the seed runs 1..K + seconds of `repro` for the targets
                            first failing within K (search, minimisation, replays).
  cost of K (randomly)      seconds of the seed runs 1..K; its replays are reported apart.
"""

from __future__ import annotations

import collections
import csv
import json
import statistics as st
import sys
from pathlib import Path

KS = (1, 5, 10, 20, 50)


def first_fail(seeds_log: list) -> dict:
    out = {}
    for x in seeds_log:
        for n in x["failing"]:
            out.setdefault(n, x["seed"])
    return out


def load(dirs: list):
    """Per (repository, tool) results; a later directory overrides an earlier one
    (a repository re-measured at a newer commit)."""
    det, rnd, sta, origin = {}, {}, {}, {}
    for d in dirs:
        for tool, store in (("detpy", det), ("randomly", rnd), ("standalone", sta)):
            for p in Path(d).glob(f"*.{tool}.block2.json"):
                data = json.loads(p.read_text())
                store[data["name"]] = data
                origin[(data["name"], tool)] = str(d)
    return det, rnd, sta, origin


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


def main(d: Path, extra: list | None = None) -> dict:
    det, rnd, sta, origin = load([d, *(extra or [])])
    repos = sorted(set(det) | set(rnd))
    rows = []
    per_repo = {}
    for name in repos:
        D, Rn = det.get(name), rnd.get(name)
        targets = (D or Rn)["targets"]
        dff = first_fail(D["seeds_log"]) if D else {}
        rff = first_fail(Rn["seeds_log"]) if Rn else {}
        bundles = {b["test"]: b for b in (D or {}).get("bundles", [])}
        # Block 1 rule (review E3): a target that fails under every --det seed is
        # broken by Level 0, not found; same view for pytest-randomly's runs.
        d_always = set((D or {}).get("always_failing", []))
        r_always = {t for t in targets if Rn and Rn["seeds_log"] and all(t in x["failing"] for x in Rn["seeds_log"])}
        for t in targets:
            b = bundles.get(t, {})
            rp = (Rn or {}).get("replays", {}).get(t, {})
            status = b.get("status", "not-failed" if D else "no-data")
            if t in d_always:
                status = "broken-by-L0 (fails under every seed)"
            rows.append({
                "repo": name, "test": t, "randomly_always_fails": t in r_always,
                "detpy_first_fail_seed": dff.get(t) if t not in d_always else None, "detpy_status": status,
                "detpy_config": b.get("config"), "detpy_kind": b.get("kind"),
                "prefix_length": b.get("prefix_length"), "minimal_length": b.get("minimal_length"),
                "polluters": " ; ".join(b.get("polluters") or []), "setters": " ; ".join(b.get("setters") or []),
                "replay_fails": (b.get("replay") or {}).get("fails"), "replay_runs": (b.get("replay") or {}).get("runs"),
                "identical_fingerprint": (b.get("replay") or {}).get("identical_fingerprint"),
                "divergence_reason": (b.get("divergence") or {}).get("reason"),
                "repro_runs": b.get("runs"), "repro_seconds": b.get("seconds"),
                "randomly_first_fail_seed": rff.get(t) if Rn else None,
                "randomly_replay_fails": rp.get("fails"), "randomly_replay_runs": rp.get("runs"),
                "has_detpy": D is not None, "has_randomly": Rn is not None,
            })
        cost = {}
        for K in KS:
            c = {}
            if D:
                seeds_s = sum(x["seconds"] for x in D["seeds_log"] if x["seed"] <= K)
                rep_s = sum(b.get("seconds") or 0 for t, b in bundles.items() if dff.get(t) and dff[t] <= K)
                c["detpy_explore_s"], c["detpy_repro_s"] = seeds_s, rep_s
                c["detpy_seeds_run"] = sum(1 for x in D["seeds_log"] if x["seed"] <= K)
            if Rn:
                c["randomly_s"] = sum(x["seconds"] for x in Rn["seeds_log"] if x["seed"] <= K)
                c["randomly_seeds_run"] = sum(1 for x in Rn["seeds_log"] if x["seed"] <= K)
            cost[K] = c
        per_repo[name] = {
            "targets": len(targets), "cost": cost,
            "detpy_seeds": len(D["seeds_log"]) if D else 0, "randomly_seeds": len(Rn["seeds_log"]) if Rn else 0,
            "families_divergence": len((D or {}).get("families_by_divergence", {})),
            "families_polluter": len((D or {}).get("families_by_polluter", {})),
            "bundles_reproduced": sum(1 for b in bundles.values() if b.get("status") == "reproduced"),
            "flaky_failing_all": len((D or {}).get("flaky_failing", [])),
            "flaky_failing_non_target": len(set((D or {}).get("flaky_failing", [])) - set(targets)),
            # Reruns are paid once per distinct first-failing seed, shared by the
            # targets of that seed (review E1).
            "randomly_replay_s": sum(sum(secs) for secs in {r["seed"]: r.get("seconds", [])
                                                         for r in (Rn or {}).get("replays", {}).values()}.values()),
            "detpy_explore_s": sum(x["seconds"] for x in (D or {}).get("seeds_log", [])),
            "detpy_repro_s": sum(b.get("seconds") or 0 for b in bundles.values()),
            "randomly_seeds_s": sum(x["seconds"] for x in (Rn or {}).get("seeds_log", [])),
            "origin_detpy": origin.get((name, "detpy")), "origin_randomly": origin.get((name, "randomly")),
            "cpu_detpy": (D or {}).get("runner", {}).get("cpu_model"),
            "cpu_randomly": (Rn or {}).get("runner", {}).get("cpu_model"),
        }
    with open(d / "per-target.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["repo"])
        w.writeheader()
        w.writerows(rows)

    both = [r for r in rows if r["has_detpy"] and r["has_randomly"]]
    total = len(rows)
    S = {"targets": total, "repos": len(repos), "repos_with_both": sum(1 for n in repos if n in det and n in rnd),
         "targets_with_both": len(both), "by_K": {}}
    for K in KS:
        dfail = sum(1 for r in both if r["detpy_first_fail_seed"] and r["detpy_first_fail_seed"] <= K)
        dfound = sum(1 for r in both if r["detpy_first_fail_seed"] and r["detpy_first_fail_seed"] <= K
                     and r["detpy_status"] == "reproduced")
        rfail = sum(1 for r in both if r["randomly_first_fail_seed"] and r["randomly_first_fail_seed"] <= K)
        rrep = sum(1 for r in both if r["randomly_first_fail_seed"] and r["randomly_first_fail_seed"] <= K
                   and r["randomly_replay_runs"] and r["randomly_replay_fails"] == r["randomly_replay_runs"])
        dmin = [per_repo[n]["cost"][K].get("detpy_explore_s", 0) + per_repo[n]["cost"][K].get("detpy_repro_s", 0)
                for n in repos if n in det and n in rnd]
        rmin = [per_repo[n]["cost"][K].get("randomly_s", 0) for n in repos if n in det and n in rnd]
        dany = sum(1 for r in both if r["detpy_first_fail_seed"] and r["detpy_first_fail_seed"] <= K
                   and r["detpy_status"] in ("reproduced", "replay-unstable") and r["replay_runs"]
                   and r["replay_fails"] == r["replay_runs"])
        # pytest-randomly reruns paid for the seeds that first failed a target <= K (once per seed).
        rr_s = 0.0
        for n in repos:
            if n in rnd:
                seen = {}
                for r in rnd[n].get("replays", {}).values():
                    if r["seed"] <= K:
                        seen[r["seed"]] = sum(r.get("seconds", []))
                rr_s += sum(seen.values())
        rflaky = sum(1 for r in both if r["randomly_first_fail_seed"] and r["randomly_first_fail_seed"] <= K
                     and not r["randomly_always_fails"])
        rflaky10 = sum(1 for r in both if r["randomly_first_fail_seed"] and r["randomly_first_fail_seed"] <= K
                       and not r["randomly_always_fails"] and r["randomly_replay_runs"]
                       and r["randomly_replay_fails"] == r["randomly_replay_runs"])
        S["by_K"][K] = {"detpy_failed": dfail, "detpy_found_replayed": dfound, "detpy_found_any_fp": dany,
                        "randomly_failed_not_always": rflaky, "randomly_10_of_10_not_always": rflaky10,
                        "randomly_failed": rfail, "randomly_rerun_minutes_total": rr_s / 60,
                        "detpy_explore_minutes_total": sum(per_repo[n]["cost"][K].get("detpy_explore_s", 0)
                                                           for n in repos if n in det) / 60,
                        "detpy_repro_minutes_total": sum(per_repo[n]["cost"][K].get("detpy_repro_s", 0)
                                                         for n in repos if n in det) / 60,
                        "randomly_failed_and_replays_10_of_10": rrep,
                        "detpy_minutes_per_repo_median": st.median(dmin) / 60 if dmin else None,
                        "detpy_minutes_per_repo_max": max(dmin) / 60 if dmin else None,
                        "detpy_minutes_total": sum(dmin) / 60,
                        "randomly_minutes_per_repo_median": st.median(rmin) / 60 if rmin else None,
                        "randomly_minutes_per_repo_max": max(rmin) / 60 if rmin else None,
                        "randomly_minutes_total": sum(rmin) / 60}
    rep = [r for r in rows if r["detpy_status"] == "reproduced"]
    S["reproduced"] = len(rep)
    S["replay_10_of_10_identical"] = sum(1 for r in rep if r["replay_fails"] == r["replay_runs"] and r["identical_fingerprint"])
    S["minimal_length_median"] = st.median([r["minimal_length"] for r in rep]) if rep else None
    S["minimal_length_max"] = max([r["minimal_length"] for r in rep]) if rep else None
    S["prefix_length_median"] = st.median([r["prefix_length"] for r in rep]) if rep else None
    S["prefix_length_max"] = max([r["prefix_length"] for r in rep]) if rep else None
    S["polluter_named"] = sum(1 for r in rep if r["polluters"])
    S["setter_named"] = sum(1 for r in rep if r["setters"])
    S["kinds"] = dict(collections.Counter(r["detpy_kind"] for r in rep))
    S["divergence_reasons"] = dict(collections.Counter(r["divergence_reason"] for r in rep))
    S["detpy_status"] = dict(collections.Counter(r["detpy_status"] for r in rows if r["has_detpy"]))
    S["repro_runs_median"] = st.median([r["repro_runs"] for r in rep]) if rep else None
    S["repro_seconds_median"] = st.median([r["repro_seconds"] for r in rep]) if rep else None
    S["repro_seconds_max"] = max([r["repro_seconds"] for r in rep]) if rep else None
    S["families_divergence"] = sum(p["families_divergence"] for p in per_repo.values())
    S["families_polluter"] = sum(p["families_polluter"] for p in per_repo.values())
    S["bundles"] = sum(p["bundles_reproduced"] for p in per_repo.values())
    S["flaky_failing_non_target"] = sum(p["flaky_failing_non_target"] for p in per_repo.values())
    rr = [r for r in both if r["randomly_replay_runs"]]
    S["randomly_replayed"] = len(rr)
    S["randomly_replay_10_of_10"] = sum(1 for r in rr if r["randomly_replay_fails"] == r["randomly_replay_runs"])
    S["randomly_replay_some"] = sum(1 for r in rr if 0 < r["randomly_replay_fails"] < r["randomly_replay_runs"])
    S["randomly_replay_none"] = sum(1 for r in rr if r["randomly_replay_fails"] == 0)
    S["randomly_replay_minutes_total"] = sum(p["randomly_replay_s"] for p in per_repo.values()) / 60
    sb = [b for x in sta.values() for b in x.get("bundles", [])]
    srep = [b for b in sb if b.get("status") == "reproduced"]
    S["standalone"] = {
        "repos": len(sta), "targets": len(sb), "statuses": dict(collections.Counter(b.get("status") for b in sb)),
        "reproduced": len(srep),
        "kinds": dict(collections.Counter(b.get("kind") for b in srep)),
        "polluter_named": sum(1 for b in srep if b.get("polluters")),
        "setter_named": sum(1 for b in srep if b.get("setters")),
        "cause_named": sum(1 for b in srep if b.get("polluters") or b.get("setters")),
        "identical_fingerprint": sum(1 for b in srep if (b.get("replay") or {}).get("identical_fingerprint")),
        "minimal_length_median": st.median([b["minimal_length"] for b in srep]) if srep else None,
        "minimal_length_max": max([b["minimal_length"] for b in srep]) if srep else None,
        "configs_searched_median": st.median([b.get("configs_searched", 0) for b in srep]) if srep else None,
        "seconds_median": st.median([b.get("seconds") or 0 for b in srep]) if srep else None,
        "minutes_total": sum(x.get("seconds", 0) for x in sta.values()) / 60,
    } if sta else None
    S["cpu_differs"] = sum(1 for p in per_repo.values() if p["cpu_detpy"] and p["cpu_randomly"]
                           and p["cpu_detpy"] != p["cpu_randomly"])
    S["per_repo"] = per_repo
    (d / "summary.json").write_text(json.dumps(S, indent=1))
    write_md(d, S, rows, per_repo)
    return S


def write_md(d: Path, S: dict, rows: list, per_repo: dict) -> None:
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    n = S["targets_with_both"]
    L = ["# Block 2: detpy explore + repro vs pytest-randomly seeds\n",
         f"Run: {meta.get('run', 'local')}. Targets: the {S['targets']} Block 1 baseline-unstable tests "
         f"({S['repos']} repositories, same pins). Seeds 1..{meta.get('seeds', 50)}, whole suite per seed, serial; "
         f"{meta.get('confirm', 10)} replays. Every number MEASURED (timings NOISY: hosted runners). "
         f"Comparison on the {n} targets of the {S['repos_with_both']} repositories measured with both tools.\n",
         "## Share found within K seeds\n",
         "A target that fails under **every** seed of a tool is not counted as found by that tool (Block 1 rule: "
         "under detpy it is broken by Level 0; under pytest-randomly it always fails in that environment).\n",
         "| K | detpy: fails | detpy: replays 10/10 | detpy: replays 10/10, one fingerprint | pytest-randomly: fails | "
         "pytest-randomly: seed rerun fails 10/10 | detpy explore / repro min (total) | randomly seeds / reruns min (total) |",
         "|---:|---:|---:|---:|---:|---:|---|---|"]
    for K, v in S["by_K"].items():
        L.append(f"| {K} | {v['detpy_failed']} ({pct(v['detpy_failed'], n)}) | {v['detpy_found_any_fp']} "
                 f"({pct(v['detpy_found_any_fp'], n)}) | {v['detpy_found_replayed']} ({pct(v['detpy_found_replayed'], n)}) | "
                 f"{v['randomly_failed_not_always']} ({pct(v['randomly_failed_not_always'], n)}) | "
                 f"{v['randomly_10_of_10_not_always']} ({pct(v['randomly_10_of_10_not_always'], n)}) | "
                 f"{v['detpy_explore_minutes_total']:.1f} / {v['detpy_repro_minutes_total']:.1f} | "
                 f"{v['randomly_minutes_total']:.1f} / {v['randomly_rerun_minutes_total']:.1f} |")
    L.append("")
    L.append(f"Timings NOISY: in {S['cpu_differs']} of {S['repos']} repositories the two tools ran on different CPU models.\n")
    if S.get("standalone"):
        sa = S["standalone"]
        L.append("## Standalone `detpy repro <target>` (the developer's command, no exploration hint)\n")
        L.append(f"* {sa['targets']} targets in {sa['repos']} repositories: {sa['statuses']}")
        L.append(f"* reproduced {sa['reproduced']}; cause named {sa['cause_named']} ({pct(sa['cause_named'], sa['reproduced'])}): "
                 f"polluter {sa['polluter_named']}, state setter {sa['setter_named']}; kinds {sa['kinds']}")
        L.append(f"* identical fingerprint over the replays: {sa['identical_fingerprint']}; minimal order median "
                 f"{sa['minimal_length_median']}, max {sa['minimal_length_max']}; configurations searched median "
                 f"{sa['configs_searched_median']}; seconds per target median {sa['seconds_median']}; "
                 f"{sa['minutes_total']:.1f} min in total\n")
    L.append("## Bundles\n")
    L.append(f"* reproduced (bundle written, {S['replay_10_of_10_identical']} replay 10/10 with one fingerprint): "
             f"{S['reproduced']}; statuses {S['detpy_status']}")
    L.append(f"* order before the target: median {S['prefix_length_median']}, max {S['prefix_length_max']} tests; "
             f"minimal order (with the target): median {S['minimal_length_median']}, max {S['minimal_length_max']}")
    L.append(f"* polluter named: {S['polluter_named']} ({pct(S['polluter_named'], S['reproduced'])}); state setter "
             f"named (brittle): {S['setter_named']} ({pct(S['setter_named'], S['reproduced'])}); kinds {S['kinds']}")
    L.append(f"* first diverging event of the bundles: {S['divergence_reasons']}")
    L.append(f"* repro cost per test: median {S['repro_runs_median']} pytest runs, {S['repro_seconds_median']} s "
             f"(max {S['repro_seconds_max']} s)")
    L.append(f"* deduplication: {S['bundles']} bundles in {S['families_polluter']} polluter families and "
             f"{S['families_divergence']} first-diverging-event families; flaky failing tests outside the targets: "
             f"{S['flaky_failing_non_target']}")
    L.append(f"* pytest-randomly same-seed reruns: {S['randomly_replayed']} targets re-run; 10/10 {S['randomly_replay_10_of_10']}, "
             f"some {S['randomly_replay_some']}, none {S['randomly_replay_none']}; {S['randomly_replay_minutes_total']:.1f} min")
    L.append("")
    L.append("## Per repository\n")
    L.append("| repo | targets | detpy found ≤50 | randomly failed ≤50 | randomly 10/10 | detpy min (K=50, explore+repro) | randomly min (K=50) | bundles / families |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---|")
    for name, p in per_repo.items():
        rs = [r for r in rows if r["repo"] == name]
        df = sum(1 for r in rs if r["detpy_status"] == "reproduced" and r["detpy_first_fail_seed"])
        rf = sum(1 for r in rs if r["randomly_first_fail_seed"])
        r10 = sum(1 for r in rs if r["randomly_replay_runs"] and r["randomly_replay_fails"] == r["randomly_replay_runs"])
        c = p["cost"][50]
        dm = (c.get("detpy_explore_s", 0) + c.get("detpy_repro_s", 0)) / 60
        L.append(f"| {name} | {p['targets']} | {df if rs and rs[0]['has_detpy'] else 'n/a'} | "
                 f"{rf if rs and rs[0]['has_randomly'] else 'n/a'} | {r10 if rs and rs[0]['has_randomly'] else 'n/a'} | "
                 f"{dm:.1f} | {c.get('randomly_s', 0) / 60:.1f} | {p['bundles_reproduced']} / "
                 f"{p['families_polluter']} |")
    (d / "REPORT.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    s = main(Path(sys.argv[1]), [Path(x) for x in sys.argv[2:]])
    print(json.dumps({k: v for k, v in s.items() if k != "per_repo"}, indent=1))
