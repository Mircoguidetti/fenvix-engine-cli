#!/usr/bin/env python3
"""Step 4 helper: the names of the tests that broke upstream, from check-run annotations and outputs.

Job logs of other repositories are not readable with the workflow token (401/410 in dv1); check-run annotations and
the check-run output text often are. For every pair of ``ci-status.json`` with a newly failed check, this saves the
annotations and the output summary/text of the failed check runs of C.

    GITHUB_TOKEN=... python3 harness/dep_verdict/annotations.py --ci ci-status.json --commits commits.json --out ann.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from ci_status import API, get

TEST = re.compile(r"((?:[\w./-]+/)?test_[\w]+\.py(?:::[\w\[\]./:-]+)?)")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", required=True)
    ap.add_argument("--commits", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    token = os.environ["GITHUB_TOKEN"]
    ci = json.loads(Path(a.ci).read_text())
    allc = json.loads(Path(a.commits).read_text())
    res = {}
    for name, rows in ci.items():
        owner, repo = allc[name]["url"].rstrip("/").split("/")[-2:]
        for row in rows:
            if not row["new_failed"]:
                continue
            d = get(f"{API}/repos/{owner}/{repo}/commits/{row['sha']}/check-runs?per_page=100&filter=all", token)
            runs = [r for r in (d.get("check_runs") or []) if r["name"] in row["new_failed"]
                    and r["conclusion"] in ("failure", "timed_out")]
            out = []
            for r in runs[:8]:
                ann = get(f"{API}/repos/{owner}/{repo}/check-runs/{r['id']}/annotations?per_page=100", token)
                ann = ann if isinstance(ann, list) else [ann]
                o = r.get("output") or {}
                text = "\n".join(str(o.get(k) or "") for k in ("title", "summary", "text"))
                msgs = "\n".join(f"{x.get('path')}:{x.get('title')}:{x.get('message')}" for x in ann if isinstance(x, dict))
                tests = sorted(set(TEST.findall(text + "\n" + msgs)))
                out.append({"name": r["name"], "id": r["id"], "app": (r.get("app") or {}).get("slug"),
                            "annotations": ann[:60], "output": text[:4000], "tests": tests[:200]})
            res.setdefault(name, []).append({"sha": row["sha"], "runs": out})
            print(name, row["sha"][:10], [(x["name"][:40], len(x["annotations"]), len(x["tests"])) for x in out], flush=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
