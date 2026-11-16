#!/usr/bin/env python3
"""Helpers for running the harness as a GitHub Actions matrix (.github/workflows/harness.yml).

    ci.py candidates --flaky 60            JSON list of candidate repositories (selection stage matrix)
    ci.py select --dir ART --per-pool 25   first 25 candidates per pool that pass the filters, in candidate order
    ci.py timing-pick --dir ART -n 10      repositories for the quiet timing pass (half per pool)
    ci.py aggregate --dir ART --out DIR    merge per-repository outputs and write REPORT.md

The selection rules are the ones of the local round: a candidate is kept when it
clones, installs, collects and its first baseline run takes less than
--max-first-run seconds; candidates are taken in pool order until each pool
has --per-pool repositories. Every rejected candidate is recorded with its reason.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import detpy_harness as H  # noqa: E402


def _emit(name: str, value) -> None:
    text = json.dumps(value, separators=(",", ":"))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{name}={text}\n")
    print(text)


def candidates(args) -> None:
    cfg = json.loads((HERE / "repos.json").read_text())
    flaky, popular = H.load_pools(cfg)
    _emit("matrix", [r["name"] for r in flaky[: args.flaky]] + [r["name"] for r in popular])


def _load(dirpath: Path, pattern: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(dirpath.glob(f"**/{pattern}"))]


def select(args) -> None:
    cfg = json.loads((HERE / "repos.json").read_text())
    flaky, popular = H.load_pools(cfg)
    art = Path(args.dir)
    status = {d["name"]: d for d in _load(art, "*.prepare.json")}
    for sk_list in _load(art, "skipped.json"):
        for sk in sk_list:
            status.setdefault(sk["name"], sk)
    selected, discarded = [], []
    for pool in (flaky[: args.flaky], popular):
        n = 0
        for r in pool:
            st = status.get(r["name"], {"status": "no-result", "detail": "selection job produced no result"})
            if n < args.per_pool and st["status"] == "ok":
                selected.append(r["name"])
                n += 1
            elif st["status"] != "ok":
                discarded.append({"name": r["name"], "kind": r["kind"], "status": st["status"],
                                  "detail": st.get("detail", "")})
    Path(args.selection).write_text(json.dumps({"selected": selected, "discarded": discarded}, indent=2))
    _emit("matrix", selected)


def timing_pick(args) -> None:
    summaries = [s for s in _load(Path(args.dir), "*.summary.json") if s.get("status") == "ok"]
    order = json.loads(Path(args.selection).read_text())["selected"] if args.selection else []
    summaries.sort(key=lambda s: order.index(s["name"]) if s["name"] in order else 1e9)
    half = args.n // 2
    flaky = [s["name"] for s in summaries if s["kind"] == "flaky"][:half]
    popular = [s["name"] for s in summaries if s["kind"] == "popular"][: args.n - len(flaky)]
    picked = flaky + popular
    if len(picked) < args.n:
        picked += [s["name"] for s in summaries if s["name"] not in picked][: args.n - len(picked)]
    _emit("matrix", picked)


def aggregate(args) -> None:
    art, out = Path(args.dir), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.summary.json", "*.csv", "*.timing.json"):
        for p in art.glob(f"**/{pattern}"):
            shutil.copy2(p, out / p.name)
    skipped = []
    if args.selection and Path(args.selection).exists():
        sel = json.loads(Path(args.selection).read_text())
        skipped += sel["discarded"]
        order = sel["selected"]
    else:
        order = []
    measured = {s["name"] for s in _load(out, "*.summary.json")}
    for sk_list in _load(art, "skipped.json"):
        for sk in sk_list:
            if sk["name"] not in measured and sk["name"] in order:
                skipped.append({**sk, "status": f"round: {sk['status']}"})
    for name in order:
        if name not in measured and not any(s["name"] == name for s in skipped):
            skipped.append({"name": name, "kind": "", "status": "round: no-result",
                            "detail": "the matrix job produced no summary (job timeout or crash)"})
    (out / "skipped.json").write_text(json.dumps(skipped, indent=2))
    detpy = H._import_detpy()

    meta = {"set": args.set, "runs": args.runs, "seeds": args.seeds, "confirm": args.confirm, "jobs": 1,
            "timing_runs": args.timing_runs, "detpy": detpy.__version__,
            "executor": f"GitHub Actions matrix, one repository per ubuntu-latest runner (run {args.run_url})",
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "command": f"gh workflow run harness.yml -f runs={args.runs} -f seeds={args.seeds} -f confirm={args.confirm}",
            "order": order,
            "notes": ["The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment "
                      "cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of "
                      "IDoFT, each project pinned at the commit where its flaky tests were detected.",
                      "Selection: the first 25 candidates per pool (in harness/repos.json and "
                      "harness/flaky_candidates.json order) that clone, install, collect and finish their first "
                      f"baseline run within {args.max_first_run:.0f} s; every rejected candidate is listed above."]}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(H.write_report(out, meta))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--flaky", type=int, default=60)
    s = sub.add_parser("select")
    s.add_argument("--dir", required=True)
    s.add_argument("--per-pool", type=int, default=25)
    s.add_argument("--flaky", type=int, default=60)
    s.add_argument("--selection", default="selection.json")
    t = sub.add_parser("timing-pick")
    t.add_argument("--dir", required=True)
    t.add_argument("--selection", default="")
    t.add_argument("-n", type=int, default=10)
    a = sub.add_parser("aggregate")
    a.add_argument("--dir", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--selection", default="")
    a.add_argument("--set", default="mixed")
    for k, v in (("runs", 10), ("seeds", 20), ("confirm", 10), ("timing-runs", 3)):
        a.add_argument(f"--{k}", type=int, default=v)
    a.add_argument("--max-first-run", type=float, default=150)
    a.add_argument("--run-url", default="local")
    args = ap.parse_args()
    {"candidates": candidates, "select": select, "timing-pick": timing_pick, "aggregate": aggregate}[args.cmd](args)


if __name__ == "__main__":
    main()
