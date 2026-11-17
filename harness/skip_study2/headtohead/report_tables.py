#!/usr/bin/env python3
"""Markdown tables for REPORT.md from h2h_aggregate.py's JSON (a later run id replaces an earlier one per project and
arm).

    python3 harness/skip_study2/headtohead/report_tables.py h1 h2 h3
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIG = ("home-assistant", "docusaurus", "vue-core")
LIBS = ("arrow attrs boltons click flask isort jinja marshmallow more-itertools pygments sqlparse structlog toolz "
        "werkzeug").split()
ORDER = ("A", "Ae", "Af", "B", "B+", "C")


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def cell(x):
    w = x["wrong"]
    s = f"**{w}** ({x['wrong_incidents']})" if w else "0"
    return s


def table(sums, names, title, sample_note=True):
    out = [f"\n{title}\n", "| project | transitions | rule | time skipped, median / mean | verified skips: all "
           "(extra = not skipped by C) | distinct (unit, cached record) | wrong (distinct) | flaky | set differs, "
           "no failure |", "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for n in names:
        if n not in sums:
            continue
        s = sums[n]
        for r in ORDER:
            if r not in s.get("rules", []):
                continue
            x = s[r]
            out.append(f"| {n} | {s['transitions']} | {r} | {pct(x['time']['median'])} / {pct(x['time']['mean'])} | "
                       f"{x['checked']} ({x['checked_extra']}) | {x['checked_distinct'] or 'n/a'} | {cell(x)} | "
                       f"{x['flaky']} | {x['set_diff']} |")
    return "\n".join(out)


def pooled_table(p, title):
    out = [f"\n{title}\n", "| rule | projects | transitions pooled: median / mean | median of medians / mean of means "
           "| verified skips (extra) | wrong (distinct) | flaky | set |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in ORDER:
        if r not in p:
            continue
        x = p[r]
        out.append(f"| {r} | {x['projects']} | {pct(x['time']['median'])} / {pct(x['time']['mean'])} | "
                   f"{pct(x['median_of_medians'])} / {pct(x['mean_of_means'])} | {x['checked']} ({x['checked_extra']}) "
                   f"| {cell(x)} | {x['flaky']} | {x['set_diff']} |")
    return "\n".join(out)


def ci_table(res):
    """One row per (arm, project, rule) of the realistic CI change arms."""
    out = ["| change | project | rule | time skipped at the landing commit | after landing, mean | stale passes "
           "(test-file x commit, confirmed) | test files broken by the change | broken files the rule reported "
           "as passing | commits with a stale pass |", "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for arm in ("ci-dep", "ci-data", "ci-env"):
        for n, s in sorted((res.get(arm) or {}).items()):
            if n.startswith("_") or not s.get("change"):
                continue
            for r in ORDER:
                if r not in s.get("rules", []):
                    continue
                x = s[r]
                out.append(f"| {arm[3:]} | {n} | {r} | {pct(x.get('landing_share'))} | "
                           f"{pct((x.get('after_share') or {}).get('mean'))} | {cell(x)} | "
                           f"{len(s['broken_by_change'])} | {len(x.get('broken_missed', []))} | "
                           f"{x.get('wrong_commits', 0)} of {s.get('after_landing')} |")
    return "\n".join(out)


def compact(sums, names, show_median=True):
    """One row per project: time skipped per rule (median / mean) and wrong (distinct test files) per rule."""
    out = ["| project | commits | " + " | ".join(ORDER) + " |", "|---|---:|" + "---:|" * len(ORDER)]
    for n in names:
        if n not in sums:
            continue
        s = sums[n]
        cells = []
        for r in ORDER:
            if r not in s.get("rules", []):
                cells.append("n/a")
                continue
            x = s[r]
            t = (f"{pct(x['time']['median'])} / {pct(x['time']['mean'])}" if show_median
                 else pct(x['time']['mean']))
            if x["wrong"]:
                t += f" **({x['wrong']} wrong, {x['wrong_units']} files)**"
            cells.append(t)
        out.append(f"| {n} | {s['transitions']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def ci_compact(res):
    out = ["| change | project | test files broken | " + " | ".join(ORDER) + " | C: time skipped at landing |",
           "|---|---|---:|" + "---:|" * len(ORDER) + "---:|"]
    for arm in ("ci-dep", "ci-data", "ci-env"):
        for n, s in sorted((res.get(arm) or {}).items()):
            if n.startswith("_") or not s.get("change"):
                continue
            cells = []
            for r in ORDER:
                if r not in s.get("rules", []):
                    cells.append("n/a")
                    continue
                x = s[r]
                cells.append(f"**{len(x.get('broken_missed', []))} / {x['wrong']}**" if x["wrong"] else "0")
            out.append(f"| {arm[3:]} | {n} | {len(s['broken_by_change'])} | " + " | ".join(cells) +
                       f" | {pct(s['C'].get('landing_share'))} |")
    return "\n".join(out)


def main(argv):
    if argv and argv[0] == "--compact":
        argv = argv[1:]
        with tempfile.NamedTemporaryFile(suffix=".json") as tf:
            subprocess.run([sys.executable, str(HERE / "h2h_aggregate.py"), *argv, "--json", tf.name], check=True,
                           capture_output=True)
            res = json.loads(Path(tf.name).read_text())
        print("\n### realistic CI changes (cells: broken test files reported as passing / stale passes)\n")
        print(ci_compact(res))
        for arm in ("main", "env", "runtime", "home-root"):
            if arm in res:
                print(f"\n### arm `{arm}` (cells: time skipped median / mean; wrong = confirmed stale passes)\n")
                print(compact(res[arm], list(BIG) + list(LIBS), show_median=(arm == "main")))
        return
    with tempfile.NamedTemporaryFile(suffix=".json") as tf:
        subprocess.run([sys.executable, str(HERE / "h2h_aggregate.py"), *argv, "--json", tf.name], check=True,
                       capture_output=True)
        res = json.loads(Path(tf.name).read_text())
    if any(a.startswith("ci-") for a in res):
        print("\n### realistic CI change arms\n")
        print(ci_table(res))
        for arm in ("ci-dep", "ci-data", "ci-env"):
            for n, s in sorted((res.get(arm) or {}).items()):
                if not n.startswith("_") and s.get("change"):
                    print(f"\n* {arm} / {n}: {s['change'].get('what')}; broken by the change: {s['broken_by_change']}; "
                          f"edits: {[e[1] for e in s.get('edits', [])][:1]}")
    for arm in ("main", "env", "runtime", "home-root"):
        if arm not in res:
            continue
        sums = res[arm]
        print(f"\n### arm `{arm}`")
        print(table(sums, BIG, "Large projects:"))
        print(table(sums, LIBS, "The 14 libraries of the first study:"))
        if "_libraries" in sums:
            print(pooled_table(sums["_libraries"], "Libraries pooled:"))


if __name__ == "__main__":
    main(sys.argv[1:])
