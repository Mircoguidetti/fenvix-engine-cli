#!/usr/bin/env python3
"""Where do two --det replays of one target first differ, below the digests?

  diagdiff.py RESULTS_DIR NAME [dN]

For each diagnosed target (results/<name>/diag/dN/r1, r2): the browser trace's first divergence (verifier, from
results/<name>.json), the first differing text behind a digest (response bodies, WebSocket frames, final DOM; from the
DETJS_PW_DIAG_DIR files), and the first differing server event of each server part, with its call site.
"""
import json
import re
import sys
from pathlib import Path


def entries(d):
    out = []
    for f in sorted((d / "pages").glob("*.jsonl")) if (d / "pages").is_dir() else []:
        for line in f.read_text(errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def first_text_diff(a, b, ctx=80):
    """Context around the first differing character (common prefix and suffix stripped)."""
    if a == b:
        return None
    n = 0
    m = min(len(a), len(b))
    while n < m and a[n] == b[n]:
        n += 1
    k = 0
    while k < m - n and a[-1 - k] == b[-1 - k]:
        k += 1
    ea, eb = len(a) - k, len(b) - k
    return (f"...{a[max(0, n - ctx):min(ea, n + 3 * ctx) + 20]!r}\n      vs ...{b[max(0, n - ctx):min(eb, n + 3 * ctx) + 20]!r}")


def stream_key(e):
    return (e["op"], re.sub(r"\s\d{3}$", "", e.get("target") or ""))


def compare_pages(r1, r2, limit=4):
    """Pair entries by (op, target) occurrence and report the first pairs whose texts differ."""
    from collections import defaultdict
    seq1, seq2 = defaultdict(list), defaultdict(list)
    for e in r1:
        seq1[stream_key(e)].append(e)
    for e in r2:
        seq2[stream_key(e)].append(e)
    diffs = []
    counts = []
    for k in sorted(set(seq1) | set(seq2)):
        a, b = seq1.get(k, []), seq2.get(k, [])
        if len(a) != len(b):
            counts.append(f"{k[0]} {k[1][:90]}: {len(a)} vs {len(b)} occurrences")
        for i, (x, y) in enumerate(zip(a, b)):
            if x["text"] != y["text"] or x.get("target") != y.get("target"):
                diffs.append((min(x["t"], y["t"]), k, i, x, y))
    diffs.sort(key=lambda z: z[0])
    out = []
    for _, k, i, x, y in diffs[:limit]:
        if k[0] == "server.msg":
            a, b = x["text"].split("\n"), y["text"].split("\n")
            only_a = sorted(set(a) - set(b))[:4]
            only_b = sorted(set(b) - set(a))[:4]
            td = f"{len(a)} vs {len(b)} events; only in r1: {only_a}; only in r2: {only_b}"
        elif k[0] == "dom":
            td = first_text_diff(x["text"], y["text"], 120)
        else:
            td = first_text_diff(x["text"], y["text"]) if x["text"] != y["text"] else f"target {x['target']} vs {y['target']}"
        out.append(f"    {k[0]} {k[1][:100]} #{i + 1}: {td}")
    return out, counts


def main():
    res = Path(sys.argv[1])
    name = sys.argv[2]
    only = sys.argv[3] if len(sys.argv) > 3 else None
    R = json.loads((res / f"{name}.json").read_text())
    for i, D in enumerate(R.get("diagnosis", []), 1):
        slug = f"d{i}"
        if only and slug != only:
            continue
        print(f"===== {name} {slug} {D.get('matched_key') or D['key']}  replays={D['replays']} walls={D.get('walls')}")
        b = D.get("browser") or {}
        print(f"  browser: {b.get('status')} ({b.get('distinct_fingerprints')} fp): {((b.get('divergence') or {}).get('description') or '')[:400]}")
        base = res / name / "diag" / slug
        r1, r2 = entries(base / "r1"), entries(base / "r2")
        diffs, counts = compare_pages(r1, r2)
        if counts:
            print("  occurrence counts differ:")
            for c in counts[:8]:
                print("    " + c)
        if diffs:
            print("  first differing texts:")
            for d in diffs:
                print(d)
        for s in D.get("server", []):
            for t in s.get("tests") or []:
                if t["status"] != "stable":
                    print(f"  server {s['part'][:8]} {t['status']}: {((t.get('divergence') or {}).get('description') or '')[:400]}")
            sm = s.get("summary") or {}
            if sm:
                print(f"  server {s['part'][:8]} summary: tests={sm.get('tests')} stable={sm.get('stable')} reasons={sm.get('reasons')}")


if __name__ == "__main__":
    main()
