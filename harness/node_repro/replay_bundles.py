"""Replay every bundle `run_repro.py` wrote as REPRODUCED, from a fresh process and a cleaned tree:

    python harness/node_repro/replay_bundles.py --work DIR [--repos a,b] [--runs 10]

`python -m detpy.fenvix_js replay BUNDLE --runs N --json` in the directory the tests run from (the bundle's `root`);
one JSON line per bundle in results/<repo>.replay.jsonl (fails, identical fingerprint, same fingerprint as the
bundle, wall seconds). The repository must still be prepared in DIR (run_repro.py --work DIR).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_repro as RR  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--repos", default=None)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args(argv)
    res = HERE / "results"
    for f in sorted(res.glob("*.jsonl")):
        if f.name.endswith(".replay.jsonl"):
            continue
        name = f.stem
        if args.repos and name not in args.repos.split(","):
            continue
        rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        rows = [r for r in rows if r.get("status") == "reproduced"]
        if not rows:
            continue
        out = res / f"{name}.replay.jsonl"
        done = {json.loads(line)["test"] for line in out.read_text().splitlines()} if out.exists() else set()
        p = None
        for r in rows:
            if r["test"] in done:
                continue
            b = r["bundle"]
            src = Path(b["root"])
            if p is None:
                p = RR.NH.Prepared(name=name, url="", kind="")
                p.src, p.node_bin = str(src), RR.node_bin(Path(args.work).resolve())
                RR.NH.snapshot_tree(p)
            RR.NH.clean_tree(p)
            env = RR.NH.node_env(p, {"FENVIX_DETJS": f"node {RR.DETJS}"})
            t0 = time.monotonic()
            pr = subprocess.run([args.python, "-m", "detpy.fenvix_js", "replay", b["bundle"], "--runs", str(args.runs),
                                 "--json"], cwd=src, env=env, capture_output=True, text=True)
            dur = time.monotonic() - t0
            try:
                v = json.loads(pr.stdout)
            except ValueError:
                v = {"error": (pr.stdout + pr.stderr)[-2000:]}
            row = {"repo": name, "test": r["test"], "exit": pr.returncode, "wall_s": round(dur, 1), **v}
            with out.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(f"{name}: {r['test']}: fails {v.get('fails')}/{v.get('runs')} identical {v.get('identical_fingerprint')} "
                  f"matches {v.get('matches_bundle')} ({dur:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
