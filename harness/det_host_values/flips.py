#!/usr/bin/env python3
"""Step 3, flips on the whole lists (plain detjs): the branch engine's `pins.py find` output against the trunk
baseline (harness/det_pins/data/<repo>/flips.json, engine e7338950 = f67be4a3 in node/src, node/bin, crates).
Every remaining flip with its first failure line; flips whose first line matches pins.py's ENV_RE are listed apart
and kept out of the AC2 bound.

    python3 harness/det_host_values/flips.py <find dir>      (holds <repo>/flips.json and engine.commit)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "det_pins"))
import pins  # noqa: E402

BOUND = {"ironcurtain": 20, "codex-multi-auth": 60}


def first(exc):
    if not exc:
        return ""
    return pins.first_line(exc[0] if exc and isinstance(exc[0], list) else exc) or ""


def main(d):
    print(f"engine (branch): {open(os.path.join(d, 'engine.commit')).read().strip()}")
    summary = []
    detail = []
    for repo, bound in BOUND.items():
        p = os.path.join(d, repo, "flips.json")
        if not os.path.exists(p):
            summary.append(f"| {repo} | (not measured) | | | | |")
            continue
        b = json.load(open(p))
        t = json.load(open(os.path.join(HERE, "..", "det_pins", "data", repo, "flips.json")))
        env, rest = [], []
        for fid in b["flips"]:
            line = first(b["flip_exceptions"].get(fid))
            (env if pins.ENV_RE.search(line) else rest).append((fid, line))
        ok = "met" if len(rest) <= bound else "MISSED"
        summary.append(f"| {repo} | {t['n_flips']} | {b['n_flips']} | {len(env)} | {len(rest)} | <= {bound}: {ok} |")
        detail.append(f"\n### {repo}: remaining flips ({len(rest)}), first failure line of the first --det run\n")
        detail.append(f"plain passed in both: {b['plain_both_passed']} (trunk {t['plain_both_passed']}); --det passed in both: "
                      f"{b['det_both_passed']} (trunk {t['det_both_passed']}); failed in one --det run only: {b['n_mixed_in_det']}; "
                      f"absent / skipped in a --det run: {b['n_absent_in_det']} / {b['n_skipped_in_det']}\n")
        detail.append("| test | first failure line |\n|---|---|")
        for fid, line in sorted(rest):
            detail.append(f"| `{fid}` | `{line[:200]}` |")
        detail.append(f"\nENV ({len(env)}): " + ("none" if not env else ""))
        for fid, line in sorted(env):
            detail.append(f"- `{fid}`: `{line[:200]}`")
    print("\n| repository | flips trunk | flips branch | of which ENV | AC2 count (branch - ENV) | bound |")
    print("|---|---|---|---|---|---|")
    print("\n".join(summary))
    print("\n".join(detail))


if __name__ == "__main__":
    main(sys.argv[1])
