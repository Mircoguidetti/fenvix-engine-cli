"""Review R-019: checks of the committed result rows (no engine needed). Each fails today.

    python -m pytest -p no:cacheprovider harness/culprit/review_r019/test_ground_truth.py
"""

from __future__ import annotations

import glob
import inspect
import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "results"
sys.path.insert(0, str(HERE.parent))


def rows(pattern):
    return [json.loads(l) for f in sorted(glob.glob(str(RES / pattern))) for l in open(f) if l.strip()]


A = [r for r in rows("a-*.jsonl") if r.get("green_run") == "pass" and r.get("red_run") == "fail"]
C = [r for r in rows("c-final.jsonl") + rows("c-node.jsonl") if "finder" in r]
D = [r for r in rows("d.jsonl") if "finder_correct" in r]


def is_commit(t):
    return isinstance(t, str) and len(t) == 40 and all(ch in "0123456789abcdef" for ch in t)


def test_planted_culprit_is_not_always_the_first_commit_of_the_range():
    """mutants.build_chain commits the mutant on the green commit itself, and nocode.edit_tree_commits commits the
    fixture edit right after the green commit: the culprit is always the oldest commit of (green, red]. Every
    commit replay of every such case was red, so 'name the oldest candidate, run nothing' scores the same."""
    import mutants

    planted_on_green = "tree_with(repo, g, path, old, new), g," in inspect.getsource(mutants.build_chain)
    commit_cases = A + [r for r in C if is_commit(r["truth"])]
    replays = [s["outcome"] for r in commit_cases for s in r["finder"]["steps"] if s["why"] == "bisect candidates"]
    trivial = sum(1 for r in commit_cases
                  if r["finder_correct"] and all(s["outcome"] == "fail" for s in r["finder"]["steps"]))
    assert "pass" in replays, (
        f"{len(commit_cases)} commit cases, {len(replays)} candidate replays, 0 passed: the ground truth cannot tell "
        f"the finder from 'oldest candidate' ({trivial} of {len(commit_cases)} right with 0 executions); "
        f"mutants.build_chain plants on the green commit: {planted_on_green}")


def test_fourteen_no_code_reds_are_no_code():
    """'14 of 14 no-code reds attributed to the right input': half of the 14 single changes are fixture edits,
    i.e. commits, which plain git bisect also finds (7 of 7)."""
    singles = [r for r in C if not r.get("decoy")]
    no_code = [r for r in singles if not is_commit(r["truth"])]
    assert len(singles) == 14
    assert len(no_code) == 14, (
        f"only {len(no_code)} of the 14 are no-code (inputs: {sorted({r['truth'] for r in no_code})}); "
        f"{len(singles) - len(no_code)} are commits")


def test_median_executions_with_one_confirmation_replay():
    """The finder never replays its answer (REPORT decision 2: +1 to +2 per case for a product). The wrong answers
    of test_wrong_culprits.py are stated with 0 to 2 executions and no check. With one confirmation replay per case
    the median is no longer <= 3."""
    ex = [r["finder"]["executions"] for r in A] + [r["finder"]["executions"] for r in C] + [r["executions"] for r in D]
    assert len(ex) == 303 and st.median(ex) == 3
    assert st.median([x + 1 for x in ex]) <= 3, f"median with one confirmation replay: {st.median([x + 1 for x in ex])}"


def test_rebuild_criterion_includes_old_commits_that_could_not_run():
    """The NO criterion is 'the old environment cannot be rebuilt in more than 20% of cases'. The 3 / 36 figure
    covers only kind c: environments of one 8-commit window, rebuilt at the original path. In kind a, attempts at
    old green commits that today's environment could not run were dropped and replaced by nearer distances
    (generation-notes.txt); they are in no denominator."""
    unusable = {}
    for line in open(RES / "generation-notes.txt"):
        name, *kv = line.split()
        d = dict(x.split("=") for x in kv)
        if int(d["unusable"]):
            unusable[name] = int(d["unusable"])
    summary = json.load(open(RES / "summary.json"))
    rebuild_cases = summary["overall"]["rebuild_cases"]
    assert not unusable, (
        f"{sum(unusable.values())} attempts at old green commits could not run in today's environment ({unusable}) and are "
        f"outside the rebuild figure ({summary['overall']['rebuild_failed']} / {rebuild_cases}, all kind c)")
