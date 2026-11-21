"""The Node Block 1 flaky set: the baseline-unstable tests of harness/node/results/node-final/.

    python harness/node_repro/flaky_set.py            # one line per repository (runner, tests, unstable, ...)
    python harness/node_repro/flaky_set.py --json OUT # every unstable test with its repository and pinned commit

A test is in the set when its `baseline_unstable` column is True in `<repo>.csv` (the same set as the 411 of
node-final/REPORT.md, before its exclusion of ids absent from some baseline run).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1] / "node" / "results" / "node-final"


def repos() -> list[dict]:
    out = []
    csv.field_size_limit(1 << 30)
    for summ in sorted(FINAL.glob("*.summary.json")):
        name = summ.name[: -len(".summary.json")]
        s = json.loads(summ.read_text())
        prep = FINAL / f"{name}.prepare.json"
        p = json.loads(prep.read_text()) if prep.exists() else {}
        rows = []
        f = FINAL / f"{name}.csv"
        if f.exists():
            with f.open() as fh:
                rows = [r for r in csv.DictReader(fh) if r.get("baseline_unstable") == "True"]
        out.append({"name": name, "kind": s.get("kind"), "url": s.get("url"), "commit": s.get("commit"),
                    "install": s.get("install"), "runner": p.get("runner"), "runner_version": p.get("runner_version"),
                    "tests": s.get("tests"), "unstable": len(rows), "reproduced_block1": s.get("reproduced"),
                    "baseline_mean_s": s.get("baseline_mean_s"),
                    "targets": [{"id": r["nodeid"], "reproduced_block1": r.get("reproduced") == "True",
                                 "repro_seed": r.get("repro_seed"), "baseline_outcomes": r.get("baseline_outcomes")}
                                for r in rows]})
    return out


def main(argv: list) -> int:
    rs = repos()
    if argv[:1] == ["--json"]:
        Path(argv[1]).write_text(json.dumps(rs, indent=1))
        return 0
    tot = 0
    for r in sorted(rs, key=lambda r: (r["baseline_mean_s"] or 1e9)):
        tot += r["unstable"]
        print(f"{r['name']:32} {str(r['runner']):8} {str(r['runner_version']):8} tests={r['tests']!s:6} "
              f"unstable={r['unstable']:4} block1_reproduced={r['reproduced_block1']!s:4} "
              f"baseline_s={round(r['baseline_mean_s'] or 0, 1)}")
    print(f"total unstable: {tot}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
