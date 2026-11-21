"""The 55-target table of REPORT.md from the hunt results (hunt-*.json, huntp-*.json, and earlier versions in git).

  python3 tracks/l2-browser-lockstep/harness/report55.py [--git REV ...]

A target counts as reproduced when one seed gave its real failure (first error line, and the failing request where
round 3 recorded one) and all replays of that seed (10) gave the same failure with one fingerprint. For each target
the newest result that reached a verdict is used (the files given last win); every row names its run.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "results"
T55 = json.loads((HERE / "targets55.json").read_text())


def load(path_or_rev):
    if ":" in path_or_rev:
        try:
            return json.loads(subprocess.run(["git", "show", path_or_rev], capture_output=True, text=True, check=True).stdout)
        except Exception:
            return None
    p = Path(path_or_rev)
    return json.loads(p.read_text()) if p.exists() else None


def main():
    sources = sys.argv[1:] or sorted(str(p) for p in RES.glob("hunt*-*.json"))
    best = {}
    for src in sources:
        d = load(src)
        if not d or "hunt" not in d:
            continue
        for t in d["hunt"]["targets"]:
            row = {**t, "run": d.get("run_id"), "engine": (d.get("engine_commit") or "")[:7], "job": d.get("job")}
            prev = best.get(t["key"])
            # a reproduced verdict is kept; otherwise the later source replaces the earlier one
            if prev and prev.get("reproduced") and not row.get("reproduced"):
                continue
            best[t["key"]] = row
    total = 0
    rep = 0
    lines = ["| Project | Target | Real failure (round 3) | Mechanism | Seed with the real failure | Replays with it | Fingerprints | Reproduced | Run, engine |",
             "|---|---|---|---|---|---|---|---|---|"]
    per = {}
    for proj, v in T55.items():
        for t in v["targets"]:
            total += 1
            b = best.get(t["key"])
            real = (t["messages"][0][0] if t["messages"] else "")[:70].replace("|", "/")
            if not b:
                lines.append(f"| {proj} | {t['title'][:60]} | {real} | - | not measured | - | - | **UNKNOWN** | - |")
                per.setdefault(proj, [0, 0])[1] += 1
                continue
            reps = b.get("replays") or []
            match = sum(1 for m in (b.get("replay_match") or []) if m) if b.get("replay_match") else sum(1 for o in reps if o in ("failed", "timedOut"))
            ok = bool(b.get("reproduced"))
            rep += ok
            per.setdefault(proj, [0, 0])
            per[proj][0] += ok
            per[proj][1] += 1
            seed = b.get("seed")
            seed_s = "default" if seed == 0 else (str(seed) if seed is not None else f"none of {len(b.get('tried') or [])}")
            lines.append(f"| {proj} | {t['title'][:60]} | {real} | {b.get('mechanism')}{' (2 workers)' if b.get('job') == 'huntp' else ''} | {seed_s} | "
                         f"{match}/{len(reps) if reps else 0} | {b.get('fingerprints') if b.get('fingerprints') is not None else '-'} | {'**yes**' if ok else 'no'} | {b.get('run')}, {b.get('engine')} |")
    print("\n".join(lines))
    print()
    print(f"Reproduced: {rep} of {total} ({100 * rep / total:.0f}%)")
    for p, (a, n) in per.items():
        print(f"- {p}: {a} of {n}")


if __name__ == "__main__":
    main()
