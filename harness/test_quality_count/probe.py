#!/usr/bin/env python3
"""§0.2 probes (only after the coordinator's "search budget free"): (a) `stryker path:.github/workflows`, (b) one
query of each §1.B shape, (c) one real §4.3 issues query. Usage: probe.py session|workflow.
Writes results/probe_<route>.json with every response (status, rate headers, total_count, incomplete_results)."""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import ghapi  # noqa: E402

CODE = ["stryker path:.github/workflows",                      # (a)
        "stryker filename:package.json",                        # (b) term + filename:
        "mutants filename:mutants.toml path:.cargo"]            # (b) term + filename: + path:
ISSUES = ["repo:stryker-mutator/stryker-js stryker (slow OR timeout OR minutes OR hours OR expensive) "
          "created:>=2024-01-01 is:issue",                      # (c) form fixed after the first probe's 422
          "repo:stryker-mutator/stryker-js stryker (slow OR timeout OR minutes OR hours OR expensive) "
          "created:>=2024-01-01 is:pull-request"]
RATE_KEYS = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-used", "x-ratelimit-resource", "retry-after")


def one(c: ghapi.Client, kind: str, q: str) -> dict:
    base = "search/code" if kind == "code" else "search/issues"
    path = base + "?" + urllib.parse.urlencode({"q": q, "per_page": 30 if kind == "issues" else 100})
    log: list = []
    c.log = log
    st, data, hd = c.get(path, search=kind)
    h = {k.lower(): v for k, v in hd.items()}
    d = data if isinstance(data, dict) else {"raw": str(data)[:300]}
    return {"kind": kind, "q": q, "status": st, "attempts": log,
            "headers": {k: h.get(k) for k in RATE_KEYS if k in h},
            "total_count": d.get("total_count"), "incomplete_results": d.get("incomplete_results"),
            "items": len(d.get("items") or []), "message": d.get("message"),
            "first_items": [{"repo": (x.get("repository") or {}).get("full_name"), "path": x.get("path"),
                             "url": x.get("html_url"), "title": x.get("title")} for x in (d.get("items") or [])[:3]],
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def flags(res: list[dict]) -> list[str]:
    """§0.2: a shape answered 422, an error, or total_count 0 (gate note 10) must be fixed or dropped."""
    out = []
    for r in res:
        if r["status"] != 200:
            out.append(f"{r['kind']} '{r['q']}': HTTP {r['status']} {r.get('message') or ''}".strip())
        elif r["kind"] == "code" and not r["total_count"]:
            out.append(f"code '{r['q']}': total_count 0")
    return out


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    route = argv[0] if argv else "session"
    discover.require_budget_free()
    c = ghapi.Client(use_gh=True) if route == "session" else ghapi.from_env()
    res = [one(c, "code", q) for q in CODE] + [one(c, "issues", q) for q in ISSUES]
    out = {"route": route, "results": res, "flags": flags(res)}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"probe_{route}.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    for r in res:
        print(f"{route} {r['kind']:<6} HTTP {r['status']} total_count={r['total_count']} "
              f"incomplete={r['incomplete_results']} {r['q']}")
    for f in out["flags"]:
        print("FLAG", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
