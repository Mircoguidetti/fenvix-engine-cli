#!/usr/bin/env python3
"""Aggregates harness/diff_study/results/ into numbers (prints markdown, writes summary.json)."""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import statistics
from pathlib import Path

VARIANTS = ("line", "func_ord", "func", "nosite")


def pct(a, b):
    return f"{a}/{b} = {100 * a / b:.1f}%" if b else f"{a}/0"


def load(d: Path) -> list:
    out = []
    for p in sorted(d.glob("*.json.gz")):
        with gzip.open(p, "rt") as f:
            out.append(json.load(f))
    return out


def is_refactor(spec) -> bool:
    return bool(spec.get("refactor_label") or spec.get("refactor_title"))


def pr_numbers(prs: list) -> dict:
    s = collections.Counter()
    loc = collections.Counter()
    loc_tests = collections.Counter()
    per_pr = []
    for r in prs:
        t = r["tests"]
        both = {n: x for n, x in t.items() if x["fp"]["line"][0] != "-" and x["fp"]["line"][2] != "-"}
        bb = {n: x for n, x in t.items() if x["fp"]["line"][0] != "-" and x["fp"]["line"][1] != "-"}
        s["tests_base_pair"] += len(bb)
        s["base_identical"] += sum(1 for x in bb.values() if x["fp"]["line"][0] == x["fp"]["line"][1])
        s["base_identical_info"] += sum(1 for x in bb.values() if x["ni"] and x["fp"]["line"][0] == x["fp"]["line"][1])
        s["base_pair_info"] += sum(1 for x in bb.values() if x["ni"])
        s["only_base"] += sum(1 for x in t.values() if x["fp"]["line"][0] != "-" and x["fp"]["line"][2] == "-")
        s["only_head"] += sum(1 for x in t.values() if x["fp"]["line"][0] == "-" and x["fp"]["line"][2] != "-")
        s["common"] += len(both)
        s["common_info"] += sum(1 for x in both.values() if x["ni"])
        ident = {v: 0 for v in VARIANTS}
        stable_changed = {v: 0 for v in VARIANTS}
        noisy = {v: 0 for v in VARIANTS}
        for n, x in both.items():
            for v in VARIANTS:
                p = x["fp"][v]
                if "-" in p:
                    p = p.replace("-", "?")
                if p[0] == p[2]:
                    ident[v] += 1
                if p[0] == p[1] and p[2] == p[3] and p[0] != p[2] and "?" not in p:
                    stable_changed[v] += 1
                if p[0] != p[1] or p[2] != p[3]:
                    noisy[v] += 1
        for v in VARIANTS:
            s[f"identical_{v}"] += ident[v]
            s[f"changed_stable_{v}"] += stable_changed[v]
            s[f"noisy_{v}"] += noisy[v]
        s["identical_info"] += sum(1 for x in both.values() if x["ni"] and x["fp"]["line"][0] == x["fp"]["line"][2])
        ident_tests = [x for x in both.values() if x["fp"]["line"][0] == x["fp"]["line"][2]]
        s["identical_runs_changed"] += sum(1 for x in ident_tests if x["runs_changed"])
        s["identical_rets_differ"] += sum(1 for x in ident_tests if x["probe"]["rets"][0] == x["probe"]["rets"][1]
                                          and x["probe"]["rets"][0] != x["probe"]["rets"][2]
                                          and x["probe"]["rets"][2] == x["probe"]["rets"][3])
        s["runs_changed"] += sum(1 for x in both.values() if x["runs_changed"])
        s["outcome_changed"] += sum(1 for x in both.values() if x["o"][0] != x["o"][2])
        # probe-based "behaviour diff" (stable in both pairs, differs across)
        for k in ("rets", "calls", "files"):
            s[f"probe_identical_{k}"] += sum(1 for x in both.values() if x["probe"][k][0] == x["probe"][k][2])
            s[f"probe_changed_stable_{k}"] += sum(1 for x in both.values() if x["probe"][k][0] == x["probe"][k][1]
                                                 and x["probe"][k][2] == x["probe"][k][3]
                                                 and x["probe"][k][0] != x["probe"][k][2] and "-" not in x["probe"][k])
        divs = r["divergences"]
        for n, d in divs.items():
            if n in both:
                loc[d["loc"]] += 1
                s["site_only"] += bool(d.get("site_only"))
        div_line = len(both) - ident["line"]
        per_pr.append({"key": r["key"], "refactor": is_refactor(r["spec"]), "label": r["spec"].get("refactor_label"),
                       "title": r["spec"].get("title", ""), "common": len(both), "div_line": div_line,
                       "div_func_ord": len(both) - ident["func_ord"], "div_func": len(both) - ident["func"],
                       "div_nosite": len(both) - ident["nosite"], "changed_stable": stable_changed["line"],
                       "noisy": noisy["line"], "base_noise": sum(1 for x in bb.values()
                                                                 if x["fp"]["line"][0] != x["fp"]["line"][1]),
                       "runs_changed": sum(1 for x in both.values() if x["runs_changed"]),
                       "rets_changed_stable": sum(1 for x in both.values() if x["probe"]["rets"][0] == x["probe"]["rets"][1]
                                                  and x["probe"]["rets"][2] == x["probe"]["rets"][3]
                                                  and x["probe"]["rets"][0] != x["probe"]["rets"][2]
                                                  and "-" not in x["probe"]["rets"]),
                       "outcome_changed": sum(1 for x in both.values() if x["o"][0] != x["o"][2]),
                       "locs": dict(collections.Counter(d["loc"] for n, d in divs.items() if n in both)),
                       "files": len(r.get("changed", [])), "src_files": len(r["spec"].get("source_files", []))})
    return {"totals": dict(s), "loc": dict(loc), "per_pr": per_pr}


def mutant_numbers(muts: list) -> dict:
    st = collections.Counter()
    surv = []
    per_repo = collections.defaultdict(collections.Counter)
    base = {}
    for r in muts:
        if r.get("status") != "ok":
            st[f"shard-{r.get('status')}"] += 1
            continue
        base[r["repo"]] = r.get("baseline")
        for m in r["mutants"]:
            st[m["status"]] += 1
            per_repo[r["repo"]][m["status"]] += 1
            if m["status"] == "survived":
                m = dict(m, repo=r["repo"])
                surv.append(m)
                per_repo[r["repo"]]["det_flag"] += m.get("det_flag_tests", 0) > 0
                per_repo[r["repo"]]["rets_flag"] += m.get("probe_rets_tests", 0) > 0
    flags = {k: sum(1 for m in surv if m.get(k, 0) > 0)
             for k in ("det_flag_tests", "probe_rets_tests", "probe_calls_tests", "probe_files_tests")}
    either = sum(1 for m in surv if m.get("det_flag_tests", 0) > 0 or m.get("probe_rets_tests", 0) > 0)
    srcs = collections.Counter()
    for m in surv:
        for k, v in (m.get("det_sources") or {}).items():
            srcs[k] += 1
    return {"status": dict(st), "survivors": len(surv), "flags": flags, "det_or_rets": either,
            "det_sources": dict(srcs), "per_repo": {k: dict(v) for k, v in per_repo.items()}, "baseline": base,
            "examples": [{k: m.get(k) for k in ("repo", "file", "line", "op", "new_line", "det_flag_tests",
                                                 "probe_rets_tests", "det_example")}
                         for m in surv if m.get("det_flag_tests", 0) > 0][:10]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(Path(__file__).resolve().parent / "results"))
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()
    root = Path(a.results)
    allprs = load(root / "prs")
    status = collections.Counter(r["status"] for r in allprs)
    ok = sorted((r for r in allprs if r["status"] == "ok"), key=lambda r: r["spec"].get("priority", 0))
    chosen = ok[: a.n]
    res = {"attempted": len(allprs), "status": dict(status), "measured": len(chosen),
           "repos": dict(collections.Counter(r["spec"]["repo"] for r in chosen)),
           "refactor_prs": sum(1 for r in chosen if is_refactor(r["spec"])),
           "refactor_label_prs": sum(1 for r in chosen if r["spec"].get("refactor_label")),
           "failures": {r["key"]: (r["status"], r.get("detail", "")[-200:]) for r in allprs if r["status"] != "ok"}}
    res.update(pr_numbers(chosen))
    res["mutants"] = mutant_numbers(load(root / "mutants")) if (root / "mutants").exists() else {}
    (root / "summary.json").write_text(json.dumps(res, indent=1))
    t = res["totals"]
    print(json.dumps({k: v for k, v in res.items() if k not in ("per_pr", "failures")}, indent=1))
    print("a", pct(t.get("base_identical", 0), t.get("tests_base_pair", 0)))
    for v in VARIANTS:
        print("b", v, pct(t.get(f"identical_{v}", 0), t.get("common", 0)))
    pp = res["per_pr"]
    ref = [p for p in pp if p["refactor"]]
    print("d", pct(sum(1 for p in ref if p["div_line"] == 0), len(ref)),
          "nosite", pct(sum(1 for p in ref if p["div_nosite"] == 0), len(ref)))
    for p in pp:
        print(p)


if __name__ == "__main__":
    main()
