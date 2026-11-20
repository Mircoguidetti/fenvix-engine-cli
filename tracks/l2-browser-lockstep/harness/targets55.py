"""The fair target set of round 3 (55 tests that both passed and failed in E1: 6 projects, 30 plain + stressed runs
each), with what a reproduction must match: the first failure line of each failing run.

  python3 tracks/l2-browser-lockstep/harness/targets55.py > tracks/l2-browser-lockstep/harness/targets55.json
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

R3 = Path(__file__).resolve().parents[2] / "l2-browser-r3" / "results"
FAIL = ("failed", "timedOut")


def first_line(e):
    e = re.sub(r"\x1b\[[0-9;]*m", "", e or "")
    for ln in e.splitlines():
        ln = ln.strip()
        if ln:
            return ln[:200]
    return ""


STEP = re.compile(r"\u2192 (GET|POST|PUT|PATCH|DELETE|HEAD) (https?://[^\s?]+)")


def step_of(e):
    """The request a runner API failure was on (its call log's first line): method and URL without the query."""
    m = STEP.search(re.sub(r"\x1b\[[0-9;]*m", "", e or ""))
    return f"{m.group(1)} {m.group(2)}" if m else None


def main():
    out = {}
    for f in sorted(R3.glob("e1-*.json")):
        r = json.loads(f.read_text())
        if r.get("status") not in ("ok", "running"):
            continue
        name = r["name"]
        hist, errs, steps = {}, {}, {}
        for x in r.get("runs") or []:
            ph = x["phase"]
            kind = "stress" if ph.endswith("stress") else "plain" if ph.endswith("plain") else None
            if kind is None:
                continue
            for k, o in (x.get("outcomes") or {}).items():
                hist.setdefault(k, {"plain": [], "stress": []})[kind].append(o)
            for k, e in (x.get("errors") or {}).items():
                errs.setdefault(k, []).append(first_line(e))
                if step_of(e):
                    steps.setdefault(k, []).append(step_of(e))
        tl = []
        for k, h in sorted(hist.items()):
            allr = h["plain"] + h["stress"]
            nf = sum(o in FAIL for o in allr)
            npass = sum(o == "passed" for o in allr)
            if nf == 0 or npass == 0:
                continue
            msgs = Counter(m for m in errs.get(k, []) if m)
            tl.append({"key": k, "file": Path(k.split("::")[0]).name, "title": k.split("::")[-1],
                       "failed_plain": sum(o in FAIL for o in h["plain"]), "runs_plain": len(h["plain"]),
                       "failed_stress": sum(o in FAIL for o in h["stress"]), "runs_stress": len(h["stress"]),
                       "timed_out": sum(o == "timedOut" for o in allr), "messages": msgs.most_common(3),
                       "steps": Counter(steps.get(k, [])).most_common(3)})
        out[name] = {"run_id": r.get("run_id"), "pw_dir": r.get("pw_dir"), "pw_args": r.get("pw_args"), "targets": tl}
    json.dump(out, sys.stdout, indent=1)
    print(file=sys.stderr)
    print({n: len(v["targets"]) for n, v in out.items()}, sum(len(v["targets"]) for v in out.values()), file=sys.stderr)


if __name__ == "__main__":
    main()
