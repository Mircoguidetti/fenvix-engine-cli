#!/usr/bin/env python3
"""Count tables of REPORT.md from results.jsonl and data/<repo>/{flips,sample}.json (no number typed by hand).

Usage: report.py  -> markdown on stdout
"""
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VS = ["V1", "V2", "V3", "V4", "V5", "V6"]
CLASSES = ["timeout", "date/time assertion", "network error", "file error", "other"]


def main():
    rows = [json.loads(x) for x in open(os.path.join(HERE, "results.jsonl")) if x.strip()]
    for repo in ("ironcurtain", "codex-multi-auth"):
        R = [r for r in rows if r["repo"] == repo]
        d = os.path.join(HERE, "data", repo)
        if not R or not os.path.exists(os.path.join(d, "flips.json")):
            print(f"## {repo}\n\nNo rows.\n")
            continue
        fl = json.load(open(os.path.join(d, "flips.json")))
        sm = json.load(open(os.path.join(d, "sample.json")))
        runs = [json.loads(x) for x in open(os.path.join(d, "runs.jsonl"))]
        finds = [r for r in runs if r["kind"] in ("plain", "det")]
        st = Counter(r["status"] for r in R)
        rep = [r for r in R if r["status"] == "reproduced"]
        print(f"## {repo}\n")
        print(f"Engine `{fl['engine_commit']}`. Find runs (`data/{repo}/runs.jsonl`, kind plain/det):\n")
        print("| run | exit | wall s | outcome counts | command |\n|---|---|---|---|---|")
        cnt = {("plain", 1): fl["plain_counts"][0], ("plain", 2): fl["plain_counts"][1],
               ("det", 1): fl["det_counts"][0], ("det", 2): fl["det_counts"][1]}
        for r in finds:
            print(f"| {r['kind']} {r['rep']} | {r['exit']} | {r['wall_s']} | {json.dumps(cnt[(r['kind'], r['rep'])])} | "
                  f"`{r['cmd']}` |")
        print()
        print(f"- passed in both plain runs: {fl['plain_both_passed']}; of these passed in both `--det` runs: "
              f"{fl['det_both_passed']}")
        print(f"- **flips** (passed in both plain runs, failed/error in both `--det` runs): **{fl['n_flips']}**")
        print(f"- absent from a `--det` run: {fl['n_absent_in_det']}; skipped in a `--det` run: {fl['n_skipped_in_det']}; "
              f"failed in one `--det` run and passed in the other (not flips): {fl['n_mixed_in_det']}")
        print(f"- sampled: {len(sm['sample'])} ({sm['method']}); affected files: "
              f"{len({(r['file'], r['project']) for r in R})}")
        print(f"- V0 control alone (file alone, `--det`, 2 runs): reproduced {st['reproduced']}, "
              f"not reproduced alone {st['not reproduced alone']}, unstable at V0 {st['unstable at V0']}"
              + "".join(f", {k} {v}" for k, v in st.items()
                        if k not in ("reproduced", "not reproduced alone", "unstable at V0")))
        print()
        print("Cumulative cleared (passed in both runs) among the reproduced flips, by first clearing variant:\n")
        print("| | V1 epoch | V2 +tz/locale | V3 +timers real | V4 +net off | V5 +fs off | V6 upper bound |"
              "\n|---|---|---|---|---|---|---|")
        first = Counter(r["first_clearing_variant"] for r in rep)
        cum, line = 0, []
        for v in VS:
            cum += first[v]
            line.append(f"{cum} (+{first[v]})")
        print(f"| cleared, cumulative (of {len(rep)}) | " + " | ".join(line) + " |")
        per = {v: Counter(r["verdicts"][v] for r in rep) for v in VS}
        print("| verdict in this variant | " + " | ".join(
            ", ".join(f"{k} {n}" for k, n in sorted(per[v].items())) for v in VS) + " |")
        remain = [r for r in rep if r["first_clearing_variant"] is None]
        print(f"\nRemain at V6 (not cleared in any variant): **{len(remain)}**"
              + ("".join(f"\n- `{r['test_id']}`: V6 {r['outcomes']['V6']}, V0 `{r['v0_failure_line']}`"
                         for r in remain)))
        nonmono = [r for r in rep if r["first_clearing_variant"] and any(
            r["verdicts"][v] != "cleared" for v in VS[VS.index(r["first_clearing_variant"]):])]
        print(f"\nCleared at a variant but not at every later one: {len(nonmono)}"
              + "".join(f"\n- `{r['test_id']}`: " + ", ".join(f"{v} {r['verdicts'][v]}" for v in VS) for r in nonmono))
        print("\nFailure class (V0 first line) x first clearing variant:\n")
        print("| class | " + " | ".join(VS) + " | none | total |\n|---|" + "---|" * (len(VS) + 2))
        for c in CLASSES:
            cr = [r for r in rep if r["failure_class"] == c]
            ct = Counter(r["first_clearing_variant"] for r in cr)
            print(f"| {c} | " + " | ".join(str(ct[v]) for v in VS) + f" | {ct[None]} | {len(cr)} |")
        msgs = Counter((r["failure_class"], (r["v0_failure_line"] or "").split(" [")[0][:110]) for r in rep)
        print("\nV0 failure lines (first line, grouped):\n\n| class | first clears | n | V0 failure line |\n|---|---|---|---|")
        fc = {}
        for r in rep:
            fc.setdefault((r["failure_class"], (r["v0_failure_line"] or "").split(" [")[0][:110]), Counter())[
                r["first_clearing_variant"]] += 1
        for (c, m), n in sorted(msgs.items(), key=lambda x: (-x[1], x[0])):
            f = ", ".join(f"{k or 'none'} {v}" for k, v in sorted(fc[(c, m)].items(), key=lambda x: str(x[0])))
            print(f"| {c} | {f} | {n} | `{m.replace('|', '/')}` |")
        vr = Counter(r.get("v0_verify", {}).get("divergence_reason") for r in R)
        print("\n`detjs verify --json` on the two V0 traces of each file, `divergence.reason` of the sampled tests: "
              + ", ".join(f"{k} {v}" for k, v in vr.most_common()) + " (None = the two traces agree: stable)\n")


if __name__ == "__main__":
    main()
