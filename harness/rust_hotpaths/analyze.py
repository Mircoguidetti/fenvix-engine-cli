#!/usr/bin/env python3
"""Tables of a rust-hotpaths profile run (``tracks/rust-hotpaths/results/<run>/*.json``).

    analyze.py tracks/rust-hotpaths/results/p1

Walls: medians of the unprofiled runs. Overhead shares: py-spy samples (250 Hz, --native) of one profiled run per
variant, per bucket (``profile.classify``); the share of a bucket in an overhead is (samples in the slower variant -
samples in the faster one) / (total samples of the slower - total of the faster). Buckets whose difference is
negative are sampling noise and are reported as such.
"""

from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys


def med(v):
    return st.median(v) if v else float("nan")


def load(d):
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        r = json.load(open(f))
        name = f"{r['spec']}" + ("" if r.get("shard") in (None, "0/1") else f" {r['shard']}")
        out[name] = r
    return out


def walls_table(runs: dict) -> str:
    rows = ["| project | tests | plain pytest | --det | cold --det-cache | warm --det-cache | --det / plain | "
            "cold / plain | cold / --det | warm / plain |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in runs.items():
        w = {k: med(v) for k, v in r["walls"].items()}
        engines = r.get("engines") or ["new"]
        n = None
        for k, v in r.get("cache", {}).items():
            if k.startswith("C") and v:
                n = v[0].get("n")
        for e in engines:
            b = w.get(f"B:{e}", w.get("B"))
            c, wm, p = w.get(f"C:{e}"), w.get(f"W:{e}"), w.get("P0")
            if c is None or p is None:
                continue
            label = name if len(engines) == 1 else f"{name} [{e}]"
            rows.append(f"| {label} | {n} | {p:.1f}s | {b:.1f}s | {c:.1f}s | {wm:.1f}s | {b / p:.2f}x | {c / p:.2f}x | "
                        f"{c / b:.2f}x | {wm / p:.2f}x |")
    return "\n".join(rows)


def shares(slow: dict, fast: dict) -> tuple[int, list]:
    """(sample difference, [(bucket, diff, share)]) between two classified profiles."""
    bs, bf = slow.get("buckets", {}), fast.get("buckets", {})
    tot = slow.get("samples", 0) - fast.get("samples", 0)
    out = []
    for k in sorted(set(bs) | set(bf)):
        d = bs.get(k, 0) - bf.get(k, 0)
        out.append((k, d, d / tot if tot > 0 else float("nan")))
    out.sort(key=lambda x: -x[1])
    return tot, out


def shares_table(runs: dict, slow_key: str, fast_key: str, title: str) -> str:
    names = [n for n, r in runs.items() if slow_key in r.get("profiles", {}) and fast_key in r.get("profiles", {})]
    if not names:
        return ""
    per = {n: shares(runs[n]["profiles"][slow_key], runs[n]["profiles"][fast_key]) for n in names}
    buckets = []
    for n in names:
        for k, d, _ in per[n][1]:
            if k not in buckets:
                buckets.append(k)
    rows = [f"**{title}** (`{slow_key}` - `{fast_key}`, py-spy samples at 250 Hz; share of the difference)", "",
            "| bucket | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in buckets:
        cells = []
        for n in names:
            m = {b: (d, s) for b, d, s in per[n][1]}
            d, s = m.get(k, (0, 0.0))
            cells.append(f"{d:+d} ({100 * s:.0f}%)" if d else "")
        rows.append(f"| {k} | " + " | ".join(cells) + " |")
    rows.append("| **total** | " + " | ".join(f"{per[n][0]:+d}" for n in names) + " |")
    return "\n".join(rows)


CAPTURE = ("record.facts", "record.loop", "record.children", "record.save", "record.other", "lines", "switch.sockets",
           "audit", "env", "startup.identity", "startup.capture", "check", "follow")
DET = ("compile", "det.plugin", "det.clock", "det.seeds", "det.fsorder", "det.network")


def attributed_table(runs: dict, slow_key: str, fast_key: str, buckets, title: str) -> str:
    """Samples of the overhead-only buckets in the slower variant (minus the faster one's), as a share of the sample
    difference; the remainder is interpreter slowdown not attributed to a frame (and sampling noise)."""
    names = [n for n, r in runs.items() if slow_key in r.get("profiles", {}) and fast_key in r.get("profiles", {})]
    if not names:
        return ""
    rows = [f"**{title}** (`{slow_key}` vs `{fast_key}`; py-spy samples at 250 Hz, one profiled run each)", "",
            "| bucket | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    data = {}
    for n in names:
        a, b = runs[n]["profiles"][slow_key], runs[n]["profiles"][fast_key]
        tot = a["samples"] - b["samples"]
        d = {k: a["buckets"].get(k, 0) - b["buckets"].get(k, 0) for k in buckets}
        d = {k: v for k, v in d.items() if v > 0}
        data[n] = (tot, d)
    order = sorted({k for _, d in data.values() for k in d}, key=lambda k: -sum(data[n][1].get(k, 0) for n in names))
    for k in order:
        rows.append(f"| {k} | " + " | ".join(
            (f"{data[n][1][k]} ({100 * data[n][1][k] / data[n][0]:.0f}%)" if k in data[n][1] and data[n][0] > 0 else "")
            for n in names) + " |")
    rows.append("| not attributed (interpreter slowdown, noise) | " + " | ".join(
        f"{data[n][0] - sum(data[n][1].values())} ({100 * (data[n][0] - sum(data[n][1].values())) / data[n][0]:.0f}%)"
        if data[n][0] > 0 else "" for n in names) + " |")
    rows.append("| **difference** | " + " | ".join(f"{data[n][0]}" for n in names) + " |")
    return "\n".join(rows)


def main(argv):
    d = argv[1]
    runs = load(d)
    print(walls_table(runs))
    print()
    keys = set()
    for r in runs.values():
        keys |= set(r.get("profiles", {}))
    engines = sorted({k.split(":", 1)[1] for k in keys if ":" in k})
    for e in engines:
        b = f"B:{e}" if any(f"B:{e}" in r.get("profiles", {}) for r in runs.values()) else "B"
        print(attributed_table(runs, f"C:{e}", b, CAPTURE, f"Capture overhead (cold - --det), engine {e}"))
        print()
        print(attributed_table(runs, b, "P0", DET, f"--det overhead (--det - plain), engine {e}"))
        print()
        if "-v" in argv:
            print(shares_table(runs, f"C:{e}", b, f"All buckets, cold - --det, engine {e}"))
            print()
    for name, r in runs.items():
        eq = r.get("equivalence")
        if eq:
            for e, v in eq.items():
                print(f"- {name}: {e} vs {r['engines'][0]}: {v['entries']} cold entries, {v['n_store_diffs']} store "
                      f"differences (fingerprint only: {v['n_fingerprint_only']}), {v['n_receipt_diffs']} warm "
                      f"decision differences of {v['n_receipts']}"
                      + (f"; run-to-run noise excluded (same engine, two rounds): {v['noise']['store']} entries, "
                         f"{v['noise']['receipts']} decisions" if "noise" in v else ""))


if __name__ == "__main__":
    main(sys.argv)
