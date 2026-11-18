#!/usr/bin/env python3
"""Canonical form of a ``--det-cache`` store (``proof-cache.json``) for comparing two engines.

File and set indices are store-specific: every entry is resolved to (path, content digest) lists; the key, the
runtime digest (it includes detpy's own distribution), the run id and the duration are left out, and the\ndigest of the engine's clock shim is masked.

    canon.py STORE_A STORE_B   -> prints the differences (exit 1 if any)
"""

import json
import re
import sys

# the clock shim followed children load is built from the engine itself: its digest differs between engines
_SHIM = re.compile(r"/clockshim-[0-9a-f]+\.so$")


def _data(data):
    return [[p, "<engine clock shim>"] if _SHIM.search(p) else [p, d] for p, d in data]


def canon(path: str) -> dict:
    s = json.load(open(path))
    files, sets = s["files"], s["sets"]

    def fset(i):
        return sorted((files[f]["path"], files[f]["content"]) for f in sets[i])

    out = {}
    for nid, e in s["tests"].items():
        u = e["units"]
        units = sorted((files[u[i]]["path"], files[u[i]]["content"], files[u[i]]["units"][u[i + 1]]["q"])
                       for i in range(0, len(u), 2))
        out[nid] = {"outcome": e["outcome"], "report": e.get("report"), "fingerprint": e["fingerprint"],
                    "config": e["config"], "epoch": e["epoch"], "env": e["env"], "data": _data(e["data"]),
                    "content": fset(e["content"]), "skeleton": fset(e["skeleton"]), "hooks": fset(e["hooks"]),
                    "units": units}
    return {"tests": out, "written": s.get("written", {})}


def diff(a: dict, b: dict, limit: int = 20) -> list:
    d = []
    if a["written"] != b["written"]:
        d.append("written differs")
    ta, tb = a["tests"], b["tests"]
    for nid in sorted(set(ta) | set(tb)):
        if nid not in ta or nid not in tb:
            d.append(f"{nid}: only in {'A' if nid in ta else 'B'}")
        elif ta[nid] != tb[nid]:
            ks = [k for k in ta[nid] if ta[nid][k] != tb[nid].get(k)]
            d.append(f"{nid}: differs in {ks}")
        if len(d) >= limit:
            break
    return d


if __name__ == "__main__":
    a, b = canon(sys.argv[1]), canon(sys.argv[2])
    d = diff(a, b)
    print(f"A {len(a['tests'])} entries, B {len(b['tests'])} entries, {len(d)} difference(s)")
    for x in d:
        print(" ", x)
    sys.exit(1 if d else 0)
