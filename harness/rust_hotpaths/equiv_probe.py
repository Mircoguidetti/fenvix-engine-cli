#!/usr/bin/env python3
"""Old vs new on a real environment (run with the project's interpreter, detpy installed):

* file facts (``detpy._codefacts.facts``) of the project's Python files against the old module
  (``tests/rust_hotpaths_ref/_ref_codefacts.py``);
* runtime identity per distribution (``_core.dist_identity``) against ``importlib.metadata``.

    python equiv_probe.py --root SRC [--max-files N]   -> JSON on stdout
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

REF = Path(__file__).resolve().parents[2] / "tests" / "rust_hotpaths_ref"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--max-files", type=int, default=3000)
    a = ap.parse_args()
    sys.path.insert(0, str(REF))
    import _ref_codefacts as ref
    from importlib import metadata

    from detpy import _codefacts as new
    from detpy import _core

    out = {}
    files = []
    for r, dirs, fs in os.walk(a.root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules"))
        files += [os.path.join(r, f) for f in sorted(fs) if f.endswith(".py")]
    random.Random(0).shuffle(files)
    files = files[: a.max_files]
    bad, t_old, t_new = [], 0.0, 0.0
    for p in files:
        try:
            text = open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        t = time.perf_counter()
        o = ref.facts(text, "c", "pkg.mod", False)
        t_old += time.perf_counter() - t
        t = time.perf_counter()
        n = new.facts(text, "c", "pkg.mod", False)
        t_new += time.perf_counter() - t
        if o != n:
            bad.append(os.path.relpath(p, a.root))
    out["facts"] = {"files": len(files), "differ": len(bad), "examples": bad[:20], "old_s": round(t_old, 2),
                    "new_s": round(t_new, 2)}
    dbad, n, fast = [], 0, 0
    for d in metadata.distributions():
        n += 1
        got = _core.dist_identity(d._path) if type(d) is metadata.PathDistribution else None
        if got is None:
            continue
        fast += 1
        try:
            name = (d.metadata.get("Name") or "?") if d.metadata is not None else "?"
            try:
                rec = d.read_text("RECORD") or ""
            except Exception:
                rec = ""
            old = (name, d.version, _core.digest(rec.encode()))
        except Exception as e:  # the old path raised: the fast path must not have answered
            old = repr(e)
        if got != old:
            dbad.append(str(d._path))
    out["distributions"] = {"n": n, "fast": fast, "differ": len(dbad), "examples": dbad[:20]}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
