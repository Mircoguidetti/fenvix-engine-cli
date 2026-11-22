"""``detpy cache``: inspect, explain, bound and clear a ``--det-cache`` directory (audit G-1510, G-1509).

* ``detpy cache stats DIR``: entries, outcomes, store and history sizes, the latest run's reuse counts;
* ``detpy cache explain DIR TEST``: what the stored entry of one test depends on (its data inputs by kind, the
  environment variables, the configuration and runtime digests, its predecessors) and why it was or was not reused
  in the latest run (and in the kept history of runs);
* ``detpy cache gc DIR [--max-age DAYS] [--max-mb MB]``: drop entries recorded more than DAYS ago, then the oldest
  until the store is under MB (the reuse check never trusts an entry it cannot prove, so dropping only costs a rerun);
* ``detpy cache clear DIR``: remove the directory's cache files.
Read-only except ``gc`` and ``clear``."""

from __future__ import annotations

import json
import os
import shutil
import time
from collections import Counter

from . import _core
from ._proof import load_store

STORE = "proof-cache.json"


def _receipts(d: str) -> list:
    p = os.path.join(d, "receipts.jsonl")
    if not os.path.exists(p):
        return []
    with open(p) as fh:
        return [json.loads(x) for x in fh if x.strip()]


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(path) for f in fs)


def stats(d: str) -> dict:
    s = load_store(os.path.join(d, STORE)) if os.path.exists(os.path.join(d, STORE)) else {"tests": {}}
    tests = s.get("tests") or {}
    rec = _receipts(d)
    return {
        "dir": d, "entries": len(tests), "outcomes": dict(Counter(e.get("outcome") for e in tests.values())),
        "placements": dict(Counter(e.get("placement") or "serial" for e in tests.values())),
        "store_bytes": _size(os.path.join(d, STORE)) if os.path.exists(os.path.join(d, STORE)) else 0,
        "dir_bytes": _size(d) if os.path.isdir(d) else 0,
        "latest_run": {"tests": len(rec), "reused": sum(1 for r in rec if r.get("reused")),
                       "reasons": dict(Counter((r.get("why") or "").split(":")[0] for r in rec if not r.get("reused")))},
        "history_runs": len(os.listdir(os.path.join(d, "receipts"))) if os.path.isdir(os.path.join(d, "receipts")) else 0,
    }


def explain(d: str, nodeid: str) -> dict:
    s = load_store(os.path.join(d, STORE))
    e = (s.get("tests") or {}).get(nodeid)
    out: dict = {"test": nodeid}
    if e is None:
        out["entry"] = None
    else:
        kinds = Counter((v.split(":")[0] if ":" in v else v) for _, v in e.get("data") or [])
        out["entry"] = {
            "outcome": e.get("outcome"), "recorded_run": e.get("run"), "key": e.get("key"),
            "placement": e.get("placement") or "serial", "config": e.get("config"), "runtime": e.get("runtime"),
            "epoch": e.get("epoch"), "environment_variables": [k for k, _ in e.get("env") or []],
            "data_inputs": len(e.get("data") or []), "data_kinds": dict(kinds),
            "project_files": sorted({k for k, _ in e.get("data") or [] if not k.startswith(("/", "\x01"))})[:50],
            "needs": e.get("needs"),
        }
    hist = []
    hd = os.path.join(d, "receipts")
    runs = sorted(os.listdir(hd)) if os.path.isdir(hd) else []
    for name in runs[-10:]:
        with open(os.path.join(hd, name)) as fh:
            for x in fh:
                if x.strip():
                    r = json.loads(x)
                    if r.get("nodeid") == nodeid:
                        hist.append({"run": name[:-6], "reused": r.get("reused"), "why": r.get("why")})
    out["latest"] = next((r for r in _receipts(d) if r.get("nodeid") == nodeid), None)
    out["history"] = hist
    return out


def gc(d: str, max_age_days: float | None, max_mb: float | None) -> dict:
    """Drop old entries through the engine's own store (so the file stays a valid store)."""
    store = _core.ProofCache(d, os.getcwd())
    s = load_store(os.path.join(d, STORE))
    tests = s.get("tests") or {}
    now = time.time()

    def recorded(e) -> float:
        r = (e.get("run") or "")[:15]
        try:
            return time.mktime(time.strptime(r, "%Y%m%dT%H%M%S")) - time.timezone
        except ValueError:
            return 0.0

    drop = []
    if max_age_days:
        drop = [n for n, e in tests.items() if now - recorded(e) > max_age_days * 86400]
    for n in drop:
        store.remove(n)
    store.save()
    if max_mb:
        order = sorted((recorded(e), n) for n, e in tests.items() if n not in drop)
        while order and os.path.getsize(os.path.join(d, STORE)) > max_mb * 2**20:
            batch = order[:max(1, len(order) // 10)]
            order = order[len(batch):]
            for _, n in batch:
                store.remove(n)
                drop.append(n)
            store.save()
    return {"dropped": len(drop), "store_bytes": os.path.getsize(os.path.join(d, STORE))}


def clear(d: str) -> dict:
    if not os.path.isdir(d):
        return {"removed": False}
    if not os.path.exists(os.path.join(d, STORE)) and not os.path.exists(os.path.join(d, "receipts.jsonl")):
        raise SystemExit(f"detpy cache clear: {d} is not a --det-cache directory")
    shutil.rmtree(d)
    return {"removed": True}


def main(args) -> int:
    if args.action == "stats":
        res = stats(args.dir)
    elif args.action == "explain":
        if not args.test:
            raise SystemExit("detpy cache explain DIR TEST")
        res = explain(args.dir, args.test)
    elif args.action == "gc":
        res = gc(args.dir, args.max_age, args.max_mb)
    else:
        res = clear(args.dir)
    print(json.dumps(res, indent=2, default=str))
    return 0
