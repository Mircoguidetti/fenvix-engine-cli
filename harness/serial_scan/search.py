#!/usr/bin/env python3
"""Step 1: collect candidate files from GitHub code search.

Every query and its total_count (as reported by GitHub, DECLARED) is logged to
raw/search_log.jsonl; every hit is written to raw/hits.jsonl. Search results are
only candidates: examine.py re-reads each file and decides with a regex whether
a serial flag is really there.

Usage: python3 harness/serial_scan/search.py [max_pages_per_query]
"""
import json, subprocess, sys, time, os

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")

# (runner, kind, query). kind = "flag" (flag alone) or "flag+word" (flag and a reason word).
QUERIES = [
    # Jest
    ("jest", "flag", '"--runInBand" filename:package.json'),
    ("jest", "flag", 'runInBand path:.github/workflows'),
    ("jest", "flag", 'maxWorkers 1 filename:jest.config.js'),
    ("jest", "flag", 'maxWorkers 1 filename:jest.config.ts'),
    ("jest", "flag+word", 'runInBand flaky'),
    ("jest", "flag+word", 'runInBand database'),
    ("jest", "flag+word", 'runInBand "shared"'),
    ("jest", "flag+word", 'runInBand port'),
    ("jest", "flag+word", 'maxWorkers 1 race'),
    # Vitest
    ("vitest", "flag", 'singleFork true filename:vitest.config.ts'),
    ("vitest", "flag", 'singleThread true filename:vitest.config.ts'),
    ("vitest", "flag", 'fileParallelism false filename:vitest.config.ts'),
    ("vitest", "flag", 'fileParallelism false filename:vitest.config.mts'),
    ("vitest", "flag+word", 'singleFork database'),
    ("vitest", "flag+word", 'fileParallelism false database'),
    ("vitest", "flag+word", 'singleFork flaky'),
    # node:test
    ("node:test", "flag", '"--test-concurrency=1"'),
    # pytest
    ("pytest", "flag", '"-p no:xdist"'),
    ("pytest", "flag", '"-p no:xdist" path:.github/workflows'),
    ("pytest", "flag", '"-n 0" pytest path:.github/workflows'),
    ("pytest", "flag+word", '"no:xdist" database'),
    ("pytest", "flag+word", '"no:xdist" flaky'),
    # Go
    ("go", "flag", '"go test" "-p 1" filename:Makefile'),
    ("go", "flag", '"go test" "-p 1" path:.github/workflows'),
    ("go", "flag", '"go test" "-parallel 1"'),
    ("go", "flag+word", '"go test" "-p 1" database'),
    ("go", "flag+word", '"go test" "-p 1" race'),
    # Rust
    ("cargo", "flag", '"--test-threads=1" path:.github/workflows'),
    ("cargo", "flag", '"--test-threads=1" filename:Makefile'),
    ("cargo", "flag+word", '"--test-threads=1" database'),
    ("cargo", "flag+word", '"--test-threads=1" shared'),
    # AVA / tap / mocha
    ("ava", "flag", '"ava --serial" filename:package.json'),
    ("tap", "flag", '"tap" "--jobs=1" filename:package.json'),
    ("mocha", "flag", '"mocha" "--jobs 1"'),
    # Playwright (scaffold default line is tagged separately in examine.py)
    ("playwright", "flag", 'workers 1 filename:playwright.config.ts'),
    ("playwright", "flag+word", 'workers 1 filename:playwright.config.ts database'),
]


def search(q, page):
    for attempt in range(6):
        p = subprocess.run(["gh", "api", "-X", "GET", "search/code", "-f", f"q={q}",
                            "-f", "per_page=100", "-f", f"page={page}"],
                           capture_output=True, text=True)
        if p.returncode == 0:
            return json.loads(p.stdout)
        err = p.stderr + p.stdout
        if "rate limit" in err.lower() or "403" in err or "secondary" in err.lower():
            time.sleep(30 * (attempt + 1))
            continue
        if "422" in err:  # past the 1000-result window
            return None
        time.sleep(10)
    return None


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    os.makedirs(RAW, exist_ok=True)
    done = set()
    log_path = os.path.join(RAW, "search_log.jsonl")
    if os.path.exists(log_path):
        for l in open(log_path):
            r = json.loads(l)
            done.add((r["query"], r["page"]))
    with open(log_path, "a") as log, open(os.path.join(RAW, "hits.jsonl"), "a") as hits:
        for runner, kind, q in QUERIES:
            for page in range(1, max_pages + 1):
                if (q, page) in done:
                    continue
                d = search(q, page)
                time.sleep(7)  # code search: 10 requests/minute
                if d is None:
                    break
                items = d.get("items", [])
                log.write(json.dumps({"runner": runner, "kind": kind, "query": q, "page": page,
                                      "total_count": d.get("total_count"),
                                      "incomplete_results": d.get("incomplete_results"),
                                      "items": len(items),
                                      "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
                log.flush()
                for it in items:
                    hits.write(json.dumps({"runner": runner, "kind": kind, "query": q,
                                           "repo": it["repository"]["full_name"],
                                           "fork": it["repository"].get("fork"),
                                           "path": it["path"], "sha": it["sha"]}) + "\n")
                hits.flush()
                print(runner, kind, q, page, d.get("total_count"), len(items), flush=True)
                if len(items) < 100:
                    break


if __name__ == "__main__":
    main()
