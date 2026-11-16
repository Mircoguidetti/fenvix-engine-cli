#!/usr/bin/env python3
"""Compare two captures of the same commit (e.g. coverage.py vs sys.monitoring):
per context and file, the executed line sets, plus the audit-hook data.

    python harness/cache_skip/compare_capture.py <stem> [<tag_a> <tag_b>]

``<stem>`` is ``<work>/<repo>/caps/<i>-<sha>``; tags default to "" and ".sm".
Exit status 0 when the captures are identical.
"""

from __future__ import annotations

import gzip
import json
import pickle
import sys


def load(stem: str, tag: str) -> tuple[dict, dict]:
    with gzip.open(f"{stem}{tag}.cov.pkl.gz", "rb") as fh:
        cov = pickle.load(fh)
    files = cov["files"]
    out: dict[str, dict[str, frozenset]] = {}
    for c, ids in cov["ctx"].items():
        per = out.setdefault(c, {})
        for b in ids:
            fi, lines = cov["blobs"][b]
            per[files[fi]] = per.get(files[fi], frozenset()) | frozenset(lines)
    cap = json.loads(open(f"{stem}{tag}.cap.json").read())
    return out, cap


def compare(stem: str, ta: str = "", tb: str = ".sm", show: int = 10) -> int:
    a, ca = load(stem, ta)
    b, cb = load(stem, tb)
    diffs = []
    for c in sorted(set(a) | set(b)):
        pa, pb = a.get(c, {}), b.get(c, {})
        for f in sorted(set(pa) | set(pb)):
            la, lb = pa.get(f, frozenset()), pb.get(f, frozenset())
            if la != lb:
                diffs.append((c, f, sorted(la - lb)[:8], sorted(lb - la)[:8]))
    other = [k for k in ("fs", "spawn", "net", "first_seen", "order") if ca.get(k) != cb.get(k)]
    other += [f"fixtures:{n}" for n, r in ca["tests"].items() if r.get("fixtures") != cb["tests"].get(n, {}).get("fixtures")]
    print(f"{stem}: contexts {len(a)}/{len(b)}, line-set differences {len(diffs)}, other differences {other[:10]}")
    for d in diffs[:show]:
        print(f"  ctx={d[0]!r} file={d[1]} only-{ta or 'a'}={d[2]} only-{tb}={d[3]}")
    return 1 if diffs or other else 0


if __name__ == "__main__":
    sys.exit(compare(*sys.argv[1:]))
