"""Derive the 20 qualifying repositories and their timed-step fields from db-serial-count at 85b36b2452df.

The copy list (five code files, four data files) is written with ``git show <rev>:<path>`` into a scratch
directory in the same relative layout; nothing is merged or imported across branches. Requires PyYAML 6.0.2
(the pin in ``harness/db_serial_count/requirements.txt`` at that revision).

    python3 harness/db_copies_read/derive.py [--src <scratch root>] [--out harness/db_copies_read/repos.json]
"""
from __future__ import annotations

import argparse
import collections
import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

BASE = "85b36b2452df"
SUB = "harness/db_serial_count"
COPY = ["status.py", "perworker.py", "discover.py", "rules.py", "ghapi.py", "results/rows.jsonl",
        "results/perworker_eval.jsonl", "results/perworker_search.jsonl", "handcheck.jsonl"]
EXPECTED = {"qualifying": 20, "per_worker": 11, "handcheck_failed": 4, "not_qualifying": 4336, "excluded": 3265,
            "uncertain": 314}
REPORT_LIST = sorted("""trustedoss/trusca XChain-Platform/xchain-indexer smartcontractkit/chainlink-aptos nikhilvdev/healix
delentia-labs/Delentia-OS zmadon8/Quill abhinavrathee/RetryRail tina4stack/tina4-python
kutschersteffen-cmd/Agentic-Research-Pipeline brunolnetto/sose mudassir709/Football-AI-tactical-Analyst SR2501/hoops-gm
Ashfaque386/TradingOS-2.0 penghaibin9/saas bertalan/mpmv Deodat-Lawson/LaunchStack MadeByGFK/StackSift
elavoaiservice/alphagasiq GetStream/Agents eddiezgq/freecad-ai-parts""".split(), key=str.lower)


def copy_files(dest: Path, rev: str = BASE) -> Path:
    for f in COPY:
        p = dest / SUB / f
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as fh:
            subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{rev}:{SUB}/{f}"], stdout=fh, check=True)
    return dest


def load_qualifying(src: Path) -> tuple[collections.Counter, list[dict]]:
    d = str(src / SUB)
    for m in ("status", "perworker", "discover", "rules", "ghapi"):
        sys.modules.pop(m, None)
    sys.path.insert(0, d)
    try:
        status = importlib.import_module("status")
        rows = status.load_rows()
        counts = collections.Counter(status.final_class(r) for r in rows)
        q = [r for r in rows if status.final_class(r) == "qualifying"]
    finally:
        sys.path.remove(d)
        for m in ("status", "perworker", "discover", "rules", "ghapi"):
            sys.modules.pop(m, None)
        sys.modules["rules"] = R  # keep this package's rules importable
    return counts, q


def fields(row: dict) -> dict:
    """Timed-step fields from the ge_10 pair with the largest pair-level median (Current state rules 1-3, gate M2)."""
    meta = row.get("meta") or {}
    name = meta.get("full_name") or row["repo"]
    pairs = [p for p in row["pairs"] if p.get("stage") == "ge_10"]
    pairs.sort(key=lambda p: -(p["timing"].get("median_s") or -1))
    chosen, others = pairs[0], pairs[1:]
    t = chosen["timing"]
    steps = [s for s in chosen["steps"] if s.get("index") == t["step_index"]]
    if len(steps) != 1 or steps[0].get("status") != "serial":
        raise SystemExit(f"{name}: step_index {t['step_index']} does not map to exactly one serial step")
    chk = R.pick_runner_check(steps[0], t["kind"])
    if chk is None:
        raise SystemExit(f"{name}: no serial checks[] line whose command word is {t['kind']}")
    return {
        "repo": name,
        "html_url": meta.get("html_url") or f"https://github.com/{name}",
        "default_branch": meta.get("default_branch"),
        "file": chosen["file"], "job": chosen["job"],
        "median_s": t["median_s"], "kind": t["kind"], "reason": t["reason"], "wd": t.get("wd") or "",
        "step_index": t["step_index"],
        "runner_line": chk["line"], "runner_src": chk.get("src") or chosen["file"], "via": chk.get("via") or [],
        "step_commands": steps[0].get("commands") or [],
        "other_ge10_pairs": [{"file": p["file"], "job": p["job"], "median_s": p["timing"].get("median_s")}
                             for p in others],
    }


def derive(src: Path) -> dict:
    counts, q = load_qualifying(src)
    out = sorted((fields(r) for r in q), key=lambda x: x["repo"].lower())
    return {"base": BASE, "counts": dict(counts), "repos": out}


def check(d: dict) -> list[str]:
    errs = []
    for k, v in EXPECTED.items():
        if d["counts"].get(k) != v:
            errs.append(f"count {k}: {d['counts'].get(k)} != {v}")
    names = [r["repo"] for r in d["repos"]]
    if [n.lower() for n in names] != [n.lower() for n in REPORT_LIST]:
        errs.append(f"names differ from REPORT's Qualifying list: {sorted(set(names) ^ set(REPORT_LIST))}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--out", default=str(HERE / "repos.json"))
    a = ap.parse_args()
    src = Path(a.src) if a.src else copy_files(Path(tempfile.mkdtemp(prefix="dcr-derive-")))
    d = derive(src)
    errs = check(d)
    print(json.dumps(d["counts"], sort_keys=True))
    if errs:
        print("STOP: " + "; ".join(errs))
        return 1
    Path(a.out).write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    print(f"wrote {a.out}: {len(d['repos'])} repositories")
    return 0


if __name__ == "__main__":
    sys.exit(main())
