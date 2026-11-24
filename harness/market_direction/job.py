#!/usr/bin/env python3
"""Workflow entry point: one request file -> one task. Kinds: probe (§0.3 retention, §0.5 route) and pairs (§1.2-1.5)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import ghapi

HERE = Path(__file__).resolve().parent
RES = HERE / "results"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def last_page(hd: dict) -> int | None:
    link = {k.lower(): v for k, v in hd.items()}.get("link", "")
    m = re.search(r'[?&]page=(\d+)>; rel="last"', link)
    return int(m.group(1)) if m else None


def retention(c: ghapi.Client, repo: str) -> dict:
    calls = []

    def get(path):
        st, data, hd = c.get(path)
        calls.append({"path": path, "status": st, "total_count": (data or {}).get("total_count")
                      if isinstance(data, dict) else None,
                      "created_at": [r.get("created_at") for r in (data or {}).get("workflow_runs", [])]
                      if isinstance(data, dict) else None,
                      "link": {k.lower(): v for k, v in hd.items()}.get("link")})
        return st, data, hd

    out = {"repo": repo, "calls": calls}
    st, data, hd = get(f"repos/{repo}/actions/runs?per_page=1")
    if st != 200:
        out.update(ok=False, why=f"status {st}")
        return out
    tc = data.get("total_count") or 0
    lp = last_page(hd) or 1
    st2, d2, _ = get(f"repos/{repo}/actions/runs?per_page=1&page={lp}")
    spec_oldest = (d2.get("workflow_runs") or [{}])[0].get("created_at") if st2 == 200 and d2 else None
    out.update(total_count=tc, last_page=lp, spec_last_page_created_at=spec_oldest)
    if tc <= 1000:
        out.update(ok=spec_oldest is not None, oldest=spec_oldest, method="last page")
        return out
    # PREREG §0.3 interpretation: the listing is capped at 1,000 -> day bisection on created=<D
    lo, hi = dt.date(2015, 1, 1), dt.date.fromisoformat(now()[:10]) + dt.timedelta(days=1)

    def any_before(d: dt.date) -> bool | None:
        s, x, _ = get(f"repos/{repo}/actions/runs?per_page=1&created=%3C{d.isoformat()}")
        return None if s != 200 else (x.get("total_count") or 0) > 0

    if any_before(lo):
        out.update(ok=False, why="runs before 2015-01-01")
        return out
    while (hi - lo).days > 1:  # invariant: none before lo, some before hi
        mid = lo + dt.timedelta(days=(hi - lo).days // 2)
        r = any_before(mid)
        if r is None:
            out.update(ok=False, why="error during bisection")
            return out
        lo, hi = (lo, mid) if r else (mid, hi)
    out.update(ok=True, oldest=lo.isoformat(), method="day bisection (listing capped at 1,000)")
    return out


def probe(req: dict) -> None:
    c = ghapi.from_env(code_per_min=4)
    out = RES / "probe"
    out.mkdir(parents=True, exist_ok=True)
    route = {"at": now()}
    st, data, hd = c.get("repos/nodejs/node")
    route["repos_nodejs_node"] = {"status": st, "full_name": (data or {}).get("full_name") if isinstance(data, dict)
                                  else None, "ratelimit": {k: v for k, v in hd.items()
                                                           if k.lower().startswith("x-ratelimit")}}
    st, data, hd = c.get("search/repositories?q=" + ghapi.q('language:"Go" stars:100..200 archived:false fork:false')
                         + "&sort=updated&per_page=5", "repo")
    route["repo_search"] = {"status": st, "total_count": (data or {}).get("total_count") if isinstance(data, dict)
                            else None, "body": data if st != 200 else None,
                            "ratelimit": {k: v for k, v in hd.items() if k.lower().startswith("x-ratelimit")}}
    # code search once, no retry loop beyond the client's own (bounded here by one raw attempt)
    s, h, d = c._once("search/code?q=" + ghapi.q("filename:AGENTS.md path:/") + "&per_page=1")
    route["code_search"] = {"status": s, "total_count": d.get("total_count") if isinstance(d, dict) else None,
                            "body": d if s != 200 else None,
                            "ratelimit": {k: v for k, v in h.items() if k.lower().startswith("x-ratelimit")}}
    (out / "route_workflow.json").write_text(json.dumps(route, indent=1, sort_keys=True))
    ret = [retention(c, r) for r in ("nodejs/node", "python/cpython", "microsoft/vscode")]
    (out / "retention.json").write_text(json.dumps({"at": now(), "repos": ret}, indent=1, sort_keys=True))
    print(json.dumps(route, sort_keys=True)[:2000])
    for r in ret:
        print(r["repo"], r.get("ok"), r.get("oldest"), r.get("method"), r.get("why"))


def web_fetch(req: dict) -> None:
    """Part 2 fetches (Python requests, PREREG constants) for {"kind": "web", "out": <dir under results/>,
    "urls": {name: url}}: per URL the status, final URL, hops, the §2.3 text and the full page (gzip)."""
    import gzip
    import web
    out = RES / req["out"]
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, url in req["urls"].items():
        r = web.fetch(url)
        text, src = web.class_text(r["text"]) if r["status"] == 200 else ("", "")
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
        with gzip.open(out / f"{slug}.html.gz", "wt") as f:
            f.write(r["text"])
        rec = {k: r.get(k) for k in ("url", "final_url", "status", "hops", "error", "at")}
        rec.update(name=name, text=text, text_source=src, first_2kb=r["text"][:2048], length=len(r["text"]))
        (out / f"{slug}.json").write_text(json.dumps(rec, indent=1, sort_keys=True))
        summary.append({k: rec[k] for k in ("name", "url", "final_url", "status", "text", "text_source", "at")})
        print(json.dumps(summary[-1])[:300], flush=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    req = json.loads(Path(ap.parse_args().request).read_text())
    kind = req.get("kind")
    if kind == "probe":
        probe(req)
    elif kind == "web":
        web_fetch(req)
    elif kind == "pairs":
        import pairs
        pairs.run(req)
    else:
        print(f"unknown request kind {kind!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
