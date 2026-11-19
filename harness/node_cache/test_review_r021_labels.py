"""Review r021: the overhead and runtime-identity figures in the node cache report must cover every measured row.

Run: python3 -m pytest -q harness/node_cache/test_review_r021_labels.py
The figures are recomputed from harness/node_cache/results/r*/ with aggregate.py's own analysis (nothing is written).
"""
import importlib.util
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORT = os.path.join(ROOT, "sessions", "2026-11-18-node-cache-proof", "REPORT.md")

spec = importlib.util.spec_from_file_location("node_cache_aggregate", os.path.join(HERE, "aggregate.py"))
agg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agg)


def overhead_rows():
    out = []
    for label in ("r1", "r3", "r4", "r5"):
        for name, shards in agg.load(label).items():
            _rows, over, _n = agg.analyse(name, shards)
            for o in over:
                if o["det_s"] and o["capture_s"]:
                    out.append((label, name, o["i"], o["capture_s"] / o["det_s"] - 1, o.get("packages") or {}))
    return out


def headline():
    text = open(REPORT, encoding="utf-8").read()
    para = text[text.index("* **Overhead**"):]
    para = para[:para.index("\n* ")]
    return para


def test_capture_overhead_range_covers_every_measured_row():
    para = headline()
    m = re.search(r"\+(\d+)% \(vue-core\) to \+(\d+)% \(docusaurus\)", para)
    t = re.search(r"TanStack \+(\d+)[–-](\d+)%", para)
    assert m and t, para
    # "+6% (vue-core) to +13% (docusaurus)": every vue-core and docusaurus row lies in [6, 13]; "TanStack +8-11%"
    span = {"vue-core": (int(m.group(1)), int(m.group(2))), "docusaurus": (int(m.group(1)), int(m.group(2))),
            "tanstack-query": (int(t.group(1)), int(t.group(2)))}
    outside = []
    for label, name, i, ov, _p in overhead_rows():
        if name in span and not span[name][0] <= round(100 * ov) <= span[name][1]:
            outside.append(f"{name} {label} commit {i}: {100 * ov:+.1f}% outside +{span[name][0]}..+{span[name][1]}%")
    assert not outside, outside


def test_runtime_identity_size_covers_every_measured_row():
    para = headline()
    m = re.search(r"up to ([\d,]+) installed files / ([\d.]+) GB", para)
    assert m, para
    files = int(m.group(1).replace(",", ""))
    gb = float(m.group(2))
    biggest = max(overhead_rows(), key=lambda r: r[4].get("files") or 0)
    p = biggest[4]
    assert p["files"] <= files and p["bytes"] / 1e9 <= gb + 0.05, (
        f"{biggest[1]} ({biggest[0]} commit {biggest[2]}): {p['files']} files / {p['bytes'] / 1e9:.2f} GB")
