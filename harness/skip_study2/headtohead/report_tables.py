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


def main(argv):
    with tempfile.NamedTemporaryFile(suffix=".json") as tf:
        subprocess.run([sys.executable, str(HERE / "h2h_aggregate.py"), *argv, "--json", tf.name], check=True,
                       capture_output=True)
        res = json.loads(Path(tf.name).read_text())
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
