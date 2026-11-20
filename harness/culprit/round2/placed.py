#!/usr/bin/env python3
"""Round-2 code cases (kind a2): the culprit at a random position, and revert-and-reland histories.

Review R-019 H5: in round 1 the planted commit was always the oldest commit of (green, red], so "name the oldest
candidate, run nothing" scored 220/220. Round 2 reuses each round-1 mutation (same green commit g, same one-token
mutation, same red test) but places it differently, inside real commits of the replayed history:

* ``placed``: window = the k first-parent commits after g. A position p in 1..k is drawn; the mutation is folded
  into the p-th commit and kept in every later one (the culprit is a real commit that also carries its own
  changes). Commits before p are the original commits.
* ``reland``: positions p1 < p2 < p3: the mutation lands with commit p1, is undone inside commit p2 (folded into
  its other changes, as a revert that rides along with other work) and lands again with commit p3 (a reland).
  The red at the head comes from p3; p1 is an older transition whose breakage was already fixed.

Truth (independent of the finder and of ``--det``): walk back from the red head one first-parent commit at a time
with plain pytest (``-p no:randomly``, no bytecode) down to the first pass; the truth is the newest commit whose
parent passes. ``--det`` must agree at the truth and at its parent, else the case is dropped (recorded).

    placed.py --cases ROUND1_CASES.jsonl --repo DIR --venv DIR --out cases2.jsonl [--shapes placed,reland]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import checkout, git, git_out, run_det, run_plain  # noqa: E402
from mutants import apply_line, commit, show, tree_with  # noqa: E402

PLAIN = ["-q", "--tb=no", "-p", "no:randomly"]


def chain(repo, g, k, heads) -> list[str]:
    """The k first-parent commits after g, on the first head (round-1 head, else the default branch) that has g on
    its first-parent chain."""
    for h in heads:
        try:
            fp = git(repo, "rev-list", "--first-parent", "--reverse", h).split()
        except RuntimeError:
            continue
        if g in fp:
            i = fp.index(g)
            return fp[i + 1: i + 1 + k]
    return []


def rebuild(repo, g, later, mutated: set, path, old, new, ref) -> list[str]:
    """New commits for ``later`` (oldest first): position i (1-based) carries the mutation when i in ``mutated``.
    Commits before the first mutated position are kept as they are."""
    out, prev, rewritten = [], g, False
    first = min(mutated)
    for i, sha in enumerate(later, start=1):
        if i < first:
            out.append(sha)
            prev = sha
            continue
        msg = git_out(repo, "log", "-1", "--format=%B", sha)
        if i in mutated:
            tree = tree_with(repo, sha, path, old, new)
        else:
            tree = git(repo, "rev-parse", f"{sha}^{{tree}}")
        prev = commit(repo, tree, prev, msg, sha)
        out.append(prev)
        rewritten = True
    assert rewritten
    git(repo, "update-ref", ref, prev)
    return out


def plain_outcome(repo, venv, test) -> str:
    code, _o, _ = run_plain(repo, venv, [*PLAIN, test], timeout=600)
    return {0: "pass", 1: "fail"}.get(code, f"exit{code}")


def walk_truth(repo, venv, g, shas, test) -> tuple[str | None, int, list]:
    """Newest pass->fail transition: walk back from the head to the first pass (plain pytest)."""
    seq = [g, *shas]
    runs, seen = 0, []
    for j in range(len(seq) - 1, -1, -1):
        checkout(repo, seq[j])
        o = plain_outcome(repo, venv, test)
        runs += 1
        seen.append((seq[j][:10], o))
        if o == "pass":
            return (seq[j + 1] if j + 1 < len(seq) else None), runs, seen
        if o != "fail":
            return None, runs, seen
    return None, runs, seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shapes", default="placed,reland")
    ap.add_argument("--seed", default="exact-culprit-round2")
    a = ap.parse_args()
    repo, venv = Path(a.repo).resolve(), Path(a.venv).resolve()
    default = git(repo, "rev-parse", "origin/HEAD")
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out)}
    notes = Path(a.out).with_suffix(".notes")
    for line in open(a.cases):
        c1 = json.loads(line)
        for shape in a.shapes.split(","):
            cid = f"{c1['id']}-{shape}"
            if cid in done:
                continue
            rng = random.Random(f"{a.seed}:{cid}")
            k = c1["k"]
            later = chain(repo, c1["green"], k, [default, c1["head"]])
            k = len(later)
            if shape == "placed":
                if k < 1:
                    continue
                p = rng.randint(1, k)
                mutated, pos = set(range(p, k + 1)), {"p": p}
            else:
                if k < 4:
                    continue
                p1, p2, p3 = sorted(rng.sample(range(1, k + 1), 3))
                mutated, pos = set(range(p1, p2)) | set(range(p3, k + 1)), {"p1": p1, "p2": p2, "p3": p3}
            # the original line must be there, exactly once, wherever the mutation goes
            okline = all(apply_line(show(repo, later[i - 1], c1["file"]) or "", c1["old"], c1["new"]) is not None
                         for i in mutated)
            if not okline:
                with open(notes, "a") as fh:
                    fh.write(f"{cid} skipped: mutation line not present in every mutated commit\n")
                continue
            ref = f"refs/culprit2/{cid}"
            shas = rebuild(repo, c1["green"], later, mutated, c1["file"], c1["old"], c1["new"], ref)
            test = c1["red_test"]
            checkout(repo, c1["green"])
            gp = plain_outcome(repo, venv, test)
            planted = shas[(pos.get("p") or pos.get("p3")) - 1]
            row = {"id": cid, "repo": c1["repo"], "shape": shape, "k": k, "positions": pos, "green": c1["green"],
                   "red_head": shas[-1], "head": default, "file": c1["file"], "line": c1["line"], "old": c1["old"],
                   "new": c1["new"], "red_test": test, "planted_at": planted, "round1": c1["id"],
                   "range": shas}
            if gp != "pass":
                row["dropped"] = f"green {gp} with plain pytest (today's environment)"
            else:
                truth, runs, seen = walk_truth(repo, venv, c1["green"], shas, test)
                row.update({"truth_walk_runs": runs, "truth_walk": seen})
                if truth is None:
                    row["dropped"] = "walk found no pass->fail transition"
                else:
                    row["planted"] = truth  # the field run_code_cases.py reads as the truth
                    par = c1["green"] if truth == shas[0] else shas[shas.index(truth) - 1]
                    checkout(repo, par)
                    dpar = run_det(repo, venv, test)["outcome"]
                    checkout(repo, truth)
                    dt = run_det(repo, venv, test)["outcome"]
                    if (dpar, dt) != ("pass", "fail"):
                        row["dropped"] = f"--det disagrees with plain at the truth: parent {dpar}, truth {dt}"
                    row["truth_is_planted"] = truth == planted
                    row["truth_position"] = shas.index(truth) + 1
            with open(a.out, "a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(f"{cid}: k={k} {pos} truth@{row.get('truth_position')} {row.get('dropped', 'ok')}", flush=True)
    checkout(repo, default)


if __name__ == "__main__":
    main()
