#!/usr/bin/env python3
"""C5.3 step 2.2: the pool of agent PRs (session side, the account's search budget via `gh api`).

Usage: pool.py [--date YYYY-MM-DD]   (D defaults to today's UTC date; resumable from results/pool_windows.jsonl)

Writes results/pool_windows.jsonl (one row per family and window: query, total_count, rows read, truncated) and
results/pool.jsonl.gz (pool rows after the family rules, de-duplicated by URL; written when every window is done).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

PACE = 3.0
MAX_PAGES = 3
RES = HERE / "results"
RAW = RES / "pool_raw"
_last = [0.0]


def windows(d: dt.date) -> list[tuple[str, str]]:
    out = []
    for i in range(9):
        a = d - dt.timedelta(days=60 - 7 * i)
        b = min(a + dt.timedelta(days=6), d - dt.timedelta(days=1))
        out.append((a.isoformat(), b.isoformat()))
    return out


def search(q: str, page: int) -> dict:
    for attempt in range(8):
        wait = PACE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = subprocess.run(["gh", "api", "-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=100",
                            "-f", f"page={page}"], capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        sys.stderr.write(f"retry {attempt} {q!r} p{page}: {r.stderr.strip()[:300]}\n")
        time.sleep(60)
    raise SystemExit(f"search failed: {q} page {page}")


def slim(it: dict, family: str, window: str) -> dict:
    body = it.get("body") or ""
    return {"family": family, "window": window, "url": it["html_url"],
            "repo": it["repository_url"].split("/repos/", 1)[1], "number": it["number"],
            "author": (it.get("user") or {}).get("login"), "state": it.get("state"),
            "created_at": it.get("created_at"), "merged_at": (it.get("pull_request") or {}).get("merged_at"),
            "family_ok": R.family_ok(family, body)}


def dedupe(rows: list[dict]) -> list[dict]:
    """Family rules applied; one row per URL, first family in R.FAMILIES order, every family recorded."""
    order = {f: i for i, f in enumerate(R.FAMILIES)}
    by_url: dict[str, dict] = {}
    for r in sorted((r for r in rows if r["family_ok"]), key=lambda r: (order[r["family"]], r["url"])):
        if r["url"] in by_url:
            if r["family"] not in by_url[r["url"]]["families"]:
                by_url[r["url"]]["families"].append(r["family"])
            continue
        by_url[r["url"]] = {k: v for k, v in r.items() if k != "family_ok"} | {"families": [r["family"]]}
    return sorted(by_url.values(), key=lambda r: r["url"])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args(argv[1:])
    RAW.mkdir(parents=True, exist_ok=True)
    win_path = RES / "pool_windows.jsonl"
    done = {}
    if win_path.exists():
        for line in win_path.read_text().splitlines():
            w = json.loads(line)
            done[(w["family"], w["window"])] = w
    ds = {w["D"] for w in done.values()}
    d = dt.date.fromisoformat(a.date) if a.date else (dt.date.fromisoformat(ds.pop()) if ds else
                                                       dt.datetime.now(dt.timezone.utc).date())
    for fam in R.FAMILIES:
        for lo, hi in windows(d):
            window = f"{lo}..{hi}"
            if (fam, window) in done:
                continue
            q = f"{R.QUERIES[fam]} created:{window}"
            rows, total = [], None
            for page in range(1, MAX_PAGES + 1):
                res = search(q, page)
                total = res["total_count"]
                rows += [slim(it, fam, window) for it in res["items"]]
                if len(res["items"]) < 100 or len(rows) >= total:
                    break
            with gzip.open(RAW / f"{fam}.jsonl.gz", "at") as f:
                for r in rows:
                    f.write(json.dumps(r, sort_keys=True) + "\n")
            w = {"D": d.isoformat(), "family": fam, "window": window, "query": q, "total_count": total,
                 "rows": len(rows), "truncated": total > len(rows), "at": dt.datetime.now(dt.timezone.utc).isoformat()}
            with win_path.open("a") as f:
                f.write(json.dumps(w, sort_keys=True) + "\n")
            print(fam, window, total, len(rows), "TRUNCATED" if w["truncated"] else "", flush=True)
    raw = [json.loads(x) for p in sorted(RAW.glob("*.jsonl.gz")) for x in gzip.open(p, "rt") if x.strip()]
    pool = dedupe(raw)
    with gzip.open(RES / "pool.jsonl.gz", "wt") as f:
        for r in pool:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    print(f"pool: {len(raw)} rows, {len(pool)} after family rules and URL de-duplication (D = {d})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
