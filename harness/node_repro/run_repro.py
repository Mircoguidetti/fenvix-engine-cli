"""`fenvix repro` on the Node Block 1 flaky set (the baseline-unstable tests of harness/node/results/node-final/).

    python harness/node_repro/run_repro.py --work DIR --repos valibot,mobx [--max-tests N] [--seeds 20] ...

Per repository: clone at the commit pinned by node-final (`<repo>.summary.json`), install with the command node-final
used, find the test directory as the Block 1 harness does (harness/node/node_harness.py: detect_runner), then run
`python -m detpy.fenvix_js repro TEST --runner R --seeds S --confirm 10` (the repro driver of this branch, through
detjs) on each unstable test, from the installed tree (cleaned before every repro as the Block 1 harness cleans
before every run), in the Block 1 environment (node_harness.node_env: CI=true, ...). Node 22 only (the one
installed here). One JSON line per test in `<out>/<repo>.jsonl`; `report.py` aggregates them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "harness" / "node"))
sys.path.insert(0, str(HERE))
import node_harness as NH  # noqa: E402
import flaky_set  # noqa: E402

DETJS = ROOT / "node" / "bin" / "detjs.js"


def engine_env(detjs: str | None, pythonpath: str | None) -> dict:
    """The engine a run measures: detjs (FENVIX_DETJS) and the detpy package (PYTHONPATH), by default this tree's.
    A frozen copy keeps a long measurement on one engine while the tree changes."""
    out = {"FENVIX_DETJS": f"node {detjs or DETJS}"}
    if pythonpath:
        out["PYTHONPATH"] = pythonpath + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
    return out


def node_bin(work: Path) -> str:
    """A private bin directory with the installed Node 22 (corepack writes its pnpm / yarn shims there)."""
    d = work / "nodebin"
    d.mkdir(parents=True, exist_ok=True)
    real = Path(shutil.which("node")).resolve().parent
    for name in ("node", "npm", "npx", "corepack"):
        if (real / name).exists() and not (d / name).exists():
            (d / name).symlink_to(real / name)
    return str(d)


def repo_entry(name: str, summary: dict) -> dict:
    flaky, popular = NH.load_pools(json.loads((ROOT / "harness" / "node" / "repos.json").read_text()))
    for r in flaky + popular:
        if r.get("name") == name:
            r = dict(r)
            break
    else:
        r = {"name": name, "url": summary["url"], "kind": summary.get("kind", "popular")}
    r.pop("pin", None)
    r["commit"] = summary["commit"]
    r["node"] = 22
    if summary.get("install"):
        r["install"] = ["bash", "-c", INSTALL_HERE.get(name, summary["install"])]  # not a login shell: keep nodebin first
    return r


# Installs that cannot run here as node-final ran them: Corepack fetches Yarn Berry from repo.yarnpkg.com directly,
# which this machine's network (an HTTPS proxy only) cannot reach; the same Yarn 4.10 line from the npm registry.
INSTALL_HERE = {"yup": "COREPACK_ENABLE_STRICT=0 npx -y @yarnpkg/cli-dist@4.10.3 install --immutable"}


def test_dir(p) -> str:
    """Where the tests run from: Playwright's configuration directory, else the runner's (node_harness)."""
    return getattr(p, "pw_dir", "") or p.src


def prepare(name: str, work: Path) -> NH.Prepared | None:
    summary = json.loads((flaky_set.FINAL / f"{name}.summary.json").read_text())
    NH.ensure_node = lambda major: node_bin(work)
    repo = repo_entry(name, summary)
    real_sh = NH.sh

    def sh(cmd, *a, **k):
        # Playwright: the browsers are installed here already (PLAYWRIGHT_BROWSERS_PATH); `install-deps` would run apt
        if any("install-deps" in str(x) for x in cmd):
            return 0, "skipped here: system dependencies of the browsers are installed", 0.0, False
        return real_sh(cmd, *a, **k)

    NH.sh = sh
    try:
        p = NH.prepare(repo, work, None, None, 3600)
    finally:
        NH.sh = real_sh
    if p.status != "ok":
        print(f"{name}: preparation failed: {p.status} {p.detail[-500:]}", flush=True)
        return None
    if p.commit != summary["commit"]:
        print(f"{name}: WARNING checked out {p.commit}, node-final measured {summary['commit']}", flush=True)
    NH.snapshot_tree(p)
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--repos", required=True)
    ap.add_argument("--out", default=str(HERE / "results"))
    ap.add_argument("--seeds", type=int, default=20, help="seeds searched after the fixed order (Block 1 explored 1..20)")
    ap.add_argument("--confirm", type=int, default=10)
    ap.add_argument("--max-runs", type=int, default=150)
    ap.add_argument("--timeout", type=float, default=900, help="seconds per runner run")
    ap.add_argument("--max-tests", type=int, default=0, help="at most N tests per repository (0: all)")
    ap.add_argument("--repo-budget", type=float, default=0, help="stop starting repros in a repository after S seconds")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--detjs", default=None, help="detjs.js to measure (default: this tree's)")
    ap.add_argument("--engine", default=None, help="label of the measured engine (commit), stored in every row")
    ap.add_argument("--pythonpath", default=None, help="directory holding the detpy package to measure (default: installed)")
    ap.add_argument("--only", default=None, help="file of test ids (restrict the set)")
    ap.add_argument("--replay", type=int, default=0, help="then replay each REPRODUCED bundle N times (replay_bundles.py)")
    ap.add_argument("--keep-clones", action="store_true", help="keep each repository installed after its repros")
    args = ap.parse_args(argv)
    work = Path(args.work).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sets = {r["name"]: r for r in flaky_set.repos()}
    only = set(Path(args.only).read_text().split("\n")) if args.only else None
    for name in args.repos.split(","):
        targets = [t["id"] for t in sets[name]["targets"] if only is None or t["id"] in only]
        if not targets:
            continue
        p = prepare(name, work)
        res_file = out / f"{name}.jsonl"
        done = set()
        if res_file.exists():
            done = {json.loads(line)["test"] for line in res_file.read_text().splitlines() if line.strip()}
        if p is None:
            with res_file.open("a") as f:
                f.write(json.dumps({"repo": name, "test": None, "status": "not-prepared"}) + "\n")
            continue
        print(f"{name}: {p.runner} {p.runner_version} in {p.src}; {len(targets)} unstable tests", flush=True)
        t_repo = time.monotonic()
        n = 0
        for test in targets:
            if test in done:
                continue
            if args.max_tests and n >= args.max_tests:
                break
            if args.repo_budget and time.monotonic() - t_repo > args.repo_budget:
                break
            n += 1
            NH.clean_tree(p)
            bundles = out / "bundles" / name
            env = NH.node_env(p, engine_env(args.detjs, args.pythonpath))
            # Block 1 ids are relative to the repository; detjs ids to the directory the tests run from (Playwright:
            # its configuration's directory)
            prefix = os.path.relpath(test_dir(p), p.src).replace(os.sep, "/")
            run_id = test[len(prefix) + 1:] if prefix != "." and test.startswith(prefix + "/") else test
            cmd = [args.python, "-m", "detpy.fenvix_js", "repro", run_id, "--runner", p.runner, "--seeds", str(args.seeds),
                   "--confirm", str(args.confirm), "--max-runs", str(args.max_runs), "--timeout", str(args.timeout),
                   "--out", str(bundles), "--json", "--", *p.pytest_args]
            t0 = time.monotonic()
            r = subprocess.run(cmd, cwd=test_dir(p), env=env, capture_output=True, text=True)
            dur = time.monotonic() - t0
            text = r.stdout
            b = None
            i = text.find("\n{")
            if i >= 0:
                try:
                    b = json.loads(text[i + 1:])
                except ValueError:
                    b = None
            row = {"repo": name, "test": test, "test_run": run_id, "engine": args.engine, "runner": p.runner, "runner_version": p.runner_version,
                   "commit": p.commit, "exit": r.returncode, "wall_s": round(dur, 1),
                   "command": " ".join(cmd[:3] + ["repro", "<test>"] + cmd[5:]), "cwd": os.path.relpath(test_dir(p), work),
                   "status": (b or {}).get("status", "crashed"), "bundle": b,
                   "rendered": text[:i] if i >= 0 else text[-3000:], "stderr": r.stderr[-3000:]}
            with res_file.open("a") as f:
                f.write(json.dumps(row) + "\n")
            shutil.rmtree(bundles / ".work", ignore_errors=True)  # every run's trace: large, not results
            print(f"{name}: {test}: {row['status']} ({dur:.0f} s)", flush=True)
        NH.clean_tree(p)
        if args.replay:
            import replay_bundles

            replay_bundles.main(["--work", str(work), "--repos", name, "--runs", str(args.replay), "--python", args.python,
                                 *(["--detjs", args.detjs] if args.detjs else []),
                                 *(["--pythonpath", args.pythonpath] if args.pythonpath else [])])
        if not args.keep_clones:  # the disk holds one or two installed projects at a time
            shutil.rmtree(work / "src" / name, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
