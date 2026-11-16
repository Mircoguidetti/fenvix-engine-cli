#!/usr/bin/env python3
"""Aggregate ``analyze.py`` outputs into the tables of docs/CACHE-SKIP-STUDY.md.

    python harness/cache_skip/aggregate.py harness/cache_skip/results > tables.md
Also writes ``<dir>/summary.json``.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

V = ("closure", "file", "line", "file+guard", "line+guard")


def pct(x, nd=0):
    return "n/a" if x is None else f"{100 * x:.{nd}f}%"


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def main(d: str) -> int:
    d = Path(d)
    repos = [json.loads(p.read_text()) for p in sorted(d.glob("*.json")) if p.name != "summary.json"]
    out = {"repos": {}, "overall": {}}
    L = []
    pooled = {f"{cm}/{v}": {"share_time": [], "share_count": [], "share_wall": []}
              for cm in ("strict", "relaxed") for v in V}
    rows = []
    for r in repos:
        ok = [t for t in r["transitions"] if t.get("status") == "ok"]
        if not ok:
            continue
        s = r["summary"]
        rec = {"tests": ok[-1]["tests"], "evaluated": len(ok), "transitions": len(r["transitions"]),
               "config_strict": s["config_strict"], "config_relaxed": s["config_relaxed"],
               "config_kinds": s["config_kinds"], "overhead_median": (s.get("overhead") or {}).get("median"),
               "plain_wall_median": (s.get("plain_wall") or {}).get("median"), "stale": s.get("stale"),
               "det_source": s.get("det_source"),
               "test_time_median": med([t["test_time"] for t in ok])}
        for key in pooled:
            for m in ("share_time", "share_count", "share_wall"):
                xs = [t["results"][key][m] for t in ok]
                pooled[key][m] += xs
                rec[f"{key}:{m}:median"] = med(xs)
                rec[f"{key}:{m}:mean"] = mean(xs)
            rec[f"{key}:outcome_changed"] = sum(t["results"][key]["outcome_changed"] for t in ok)
            rec[f"{key}:skipped"] = sum(t["results"][key]["skip"] for t in ok)
            if "path_changed" in ok[0]["results"][key]:
                rec[f"{key}:path_changed"] = sum(t["results"][key].get("path_changed", 0) for t in ok)
        # no-change transitions: share of time that is *structurally* not skippable (non-det, subprocess, net)
        base = {}
        for t in ok:
            for k, v in t["base_reasons_time"].items():
                base[k] = base.get(k, 0.0) + v / t["test_time"] / len(ok) if t["test_time"] else 0
        rec["base_reasons_time_share_mean"] = base
        # transitions where at least one Python file executed by tests changed
        rec["src_transitions"] = sum(1 for t in ok if t.get("py_changed"))
        rec["formatting_only_py"] = sum(t.get("py_formatting_only", 0) for t in ok)
        rec["py_changed_total"] = sum(t.get("py_changed", 0) for t in ok)
        rec["module_level_py"] = sum(t.get("py_module_level", 0) for t in ok)
        out["repos"][r["repo"]] = rec
        rows.append((r["repo"], rec))

    def overall(key, m):
        per_repo = [rec[f"{key}:{m}:median"] for _, rec in rows]
        per_repo_mean = [rec[f"{key}:{m}:mean"] for _, rec in rows]
        return {"median_of_repo_medians": med(per_repo), "mean_of_repo_means": mean(per_repo_mean),
                "pooled_median": med(pooled[key][m]), "pooled_mean": mean(pooled[key][m]),
                "min_repo_median": min(per_repo) if per_repo else None,
                "max_repo_median": max(per_repo) if per_repo else None,
                "min_repo_mean": min(per_repo_mean) if per_repo_mean else None,
                "max_repo_mean": max(per_repo_mean) if per_repo_mean else None,
                "transitions": len(pooled[key][m])}
    for key in pooled:
        out["overall"][key] = {m: overall(key, m) for m in ("share_time", "share_count", "share_wall")}

    # Table 1: share of test time skippable per commit, strict config rule
    L.append("| repo | tests | commits evaluated | config commits (strict / relaxed) | "
             + " | ".join(f"{v} median / mean" for v in V) + " |")
    L.append("|---|---:|---:|---:|" + "---:|" * len(V))
    for name, rec in rows:
        L.append(f"| {name} | {rec['tests']} | {rec['evaluated']}/{rec['transitions']} | "
                 f"{rec['config_strict']} / {rec['config_relaxed']} | "
                 + " | ".join(f"{pct(rec[f'strict/{v}:share_time:median'])} / {pct(rec[f'strict/{v}:share_time:mean'])}"
                              for v in V) + " |")
    o = out["overall"]
    L.append("| **median of repo values** | | | | " + " | ".join(
        f"**{pct(o[f'strict/{v}']['share_time']['median_of_repo_medians'])} / "
        f"{pct(o[f'strict/{v}']['share_time']['mean_of_repo_means'])}**" for v in V) + " |")
    L.append("| **pooled (all commits)** | | | | " + " | ".join(
        f"{pct(o[f'strict/{v}']['share_time']['pooled_median'])} / {pct(o[f'strict/{v}']['share_time']['pooled_mean'])}"
        for v in V) + " |")
    L.append("")
    # Table 2: test count share and relaxed config
    L.append("| repo | count: file / line (median, mean) | count: file+guard / line+guard (median, mean) | "
             "relaxed config: file / line+guard time (median, mean) | wall share line+guard (mean) |")
    L.append("|---|---:|---:|---:|---:|")
    for name, rec in rows:
        c = lambda k, m: pct(rec[f"{k}:{m}"])  # noqa: E731
        L.append(f"| {name} | {c('strict/file', 'share_count:median')}, {c('strict/file', 'share_count:mean')} / "
                 f"{c('strict/line', 'share_count:median')}, {c('strict/line', 'share_count:mean')} | "
                 f"{c('strict/file+guard', 'share_count:median')}, {c('strict/file+guard', 'share_count:mean')} / "
                 f"{c('strict/line+guard', 'share_count:median')}, {c('strict/line+guard', 'share_count:mean')} | "
                 f"{c('relaxed/file', 'share_time:median')}, {c('relaxed/file', 'share_time:mean')} / "
                 f"{c('relaxed/line+guard', 'share_time:median')}, {c('relaxed/line+guard', 'share_time:mean')} | "
                 f"{c('strict/line+guard', 'share_wall:mean')} |")
    L.append("")
    # Table 3: cost, safety, staleness
    L.append("| repo | plain serial run (median s) | capture overhead (median) | skipped tests (line+guard, all commits) "
             "| outcome changed although skipped (file / line / line+guard) | executed path changed although skipped "
             "(file / line / line+guard) | stale map (age 1-9): unsafe skips file / line / file+guard / line+guard "
             "| transitions with an unsafe stale skip (line) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, rec in rows:
        st = rec["stale"] or {}
        g = lambda v, k: st.get(v, {}).get(k, "n/a")  # noqa: E731
        L.append(f"| {name} | {rec['plain_wall_median']:.1f} | {pct(rec['overhead_median'])} | "
                 f"{rec['strict/line+guard:skipped']} | "
                 f"{rec['strict/file:outcome_changed']} / {rec['strict/line:outcome_changed']} / "
                 f"{rec['strict/line+guard:outcome_changed']} | "
                 f"{rec.get('strict/file:path_changed', 'n/a')} / {rec.get('strict/line:path_changed', 'n/a')} / "
                 f"{rec.get('strict/line+guard:path_changed', 'n/a')} | "
                 f"{g('file', 'unsafe_tests')} / {g('line', 'unsafe_tests')} / {g('file+guard', 'unsafe_tests')} / "
                 f"{g('line+guard', 'unsafe_tests')} | {g('line', 'transitions_with_unsafe')}/{g('line', 'transitions')} |")
    L.append("")
    print("\n".join(L))
    (d / "summary.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "harness/cache_skip/results"))
