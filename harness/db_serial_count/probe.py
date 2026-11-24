#!/usr/bin/env python3
"""§0 route probe: run `postgres jest path:.github/workflows` on one route and write the raw response.

Usage: probe.py <route-name>   (GITHUB_TOKEN set -> urllib with that token; otherwise `gh api`)
Writes results/probe_<route-name>.json: status, rate headers, full JSON body.
"""
import datetime as dt
import json
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghapi  # noqa: E402

Q = "postgres jest path:.github/workflows"


def main() -> int:
    route = sys.argv[1]
    c = ghapi.from_env()
    path = "search/code?" + urllib.parse.urlencode({"q": Q, "per_page": 100, "page": 1})
    st, data, hd = c.get(path, search=True)
    keep = {k: v for k, v in hd.items() if k.lower().startswith("x-ratelimit") or k.lower() == "date"}
    out = {"route": route, "query": Q, "path": path, "status": st, "headers": keep,
           "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "body": data}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"probe_{route}.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    tc = data.get("total_count") if isinstance(data, dict) else None
    print(f"probe {route}: HTTP {st}, total_count {tc}, incomplete {isinstance(data, dict) and data.get('incomplete_results')}, "
          f"rate {keep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
