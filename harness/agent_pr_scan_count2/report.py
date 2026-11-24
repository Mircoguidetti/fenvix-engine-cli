#!/usr/bin/env python3
"""Write REPORT.md from the committed rows (numbers marked <value><!--key--> for verify_count2.py).

Hand-written text (changes after pre-registration, hand-check notes, caveats) comes from report_notes.md, inserted
verbatim at the marked places.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import rules as R  # noqa: E402
import stats  # noqa: E402
import verify_count2 as V  # noqa: E402

NAMES = {"copilot": "Copilot", "devin": "Devin", "jules": "Jules", "codex": "Codex", "claude_code": "Claude Code"}


def notes() -> dict[str, str]:
    p = HERE / "report_notes.md"
    out, key = {}, None
    for line in p.read_text().splitlines():
        m = re.match(r"^<<(\w+)>>$", line)
        if m:
            key = m.group(1)
            out[key] = []
        elif key:
            out[key].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def main() -> None:
    res = HERE / "results"
    rows = J.read_jsonl(res / "rows.jsonl")
    v = stats.compute(rows)
    v.update(V.extra_values(rows))
    ck = json.loads((res / "checkpoint.json").read_text())
    nt = notes()

    def k(key: str) -> str:
        return f"{v[key]}<!--{key}-->"

    def fam_row(p: str, name: str) -> str:
        return (f"| {name} | {k(p + 'read')} | {k(p + 'with_failed')} | {k(p + 'already_red')} | {k(p + 'new_red')} | "
                f"{k(p + 'no_base')} | {k(p + 'unreadable')} | {k(p + 'rate')} | {k(p + 'lo')} to {k(p + 'hi')} | "
                f"{k(p + 'unrated_share')} | {k(p + 'sec_already')} ({k(p + 'sec_rate')}) |")

    valid = v["decision_valid"] == "valid"
    stop = ck.get("stopped") or "?"
    met = all(ck["rateable"][f] >= J.QUOTA for f in J.FAMILIES)
    lines = [
        "DONE",
        "",
        "# Count 2: is an agent pull request's red already red on the base?",
        "",
        "Spec: `specs/20261124-agent-pr-scan-count2.md` (md5 1de362e09ce9aa6a62a3fb0184fe1e82). Pre-registration:",
        "`PREREG.md` (commit 454d89a, before any result). Routes: `routes.md`. Re-derivation: "
        "`python3 harness/agent_pr_scan_count2/verify_count2.py` (exit 0).",
        "",
        "## Changes after the pre-registration (each decided before any rate was computed)",
        "",
        nt.get("changes", "None."),
        "",
        "## Route",
        "",
        "Route 1 works: GitHub Actions in this repository (`.github/workflows/agent-pr-count2.yml`, `GITHUB_TOKEN`, "
        "read-only on other repositories), results committed back to this branch by the job and read with "
        f"`git pull --rebase`. {k('chunks')} chunks, {k('requests')} REST requests. Route 2 not attempted (not "
        "needed); route 3 blocked by the session proxy (403). Detail: `routes.md`.",
        "",
        "## Sample",
        "",
        f"Draw prepared to {k('draw_eligible')} eligible PRs ({k('draw_prepared')} sequence positions; the full "
        "interleaved sequence of merged and closed-unmerged pools is longer). PRs read: "
        f"{k('read')} (the first {k('probe_n')} are the route-1 probe). Repository-cap exclusions during the run: "
        f"{k('cap_excluded')}.",
        "",
        f"Stop: `{stop}`. " + ("The quota (40 rateable PRs per family) was met for every family." if met else
                              "The quota was not met for every family; rateable PRs reached per family: " +
                              ", ".join(f"{NAMES[f]} {k(f + '_n_rateable')}" for f in J.FAMILIES) + "."),
        "",
        "Outcomes of the PRs read: no failed check on the last head commit "
        f"{k('no_failed')}; at least one failed check {k('with_failed')}; `pulls/{{n}}` unreadable "
        f"{k('pr_unreadable')}; head checks unreadable {k('head_unreadable')}.",
        "",
        "## Results",
        "",
        "| Family | PRs read | with a failed check | ALREADY_RED | NEW_RED | NO_BASE_SIGNAL | UNREADABLE | primary rate | "
        "Wilson 95% | NO_BASE+UNREADABLE share | secondary already red (share of failed-check PRs) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in J.FAMILIES:
        lines.append(fam_row(f + "_", NAMES[f]))
    lines.append(fam_row("", "**All five (pooled)**"))
    lines += [
        "",
        "Split by pull request state (informational):",
        "",
        "| State | PRs read | with a failed check | ALREADY_RED | NEW_RED | NO_BASE_SIGNAL | UNREADABLE | primary rate | "
        "Wilson 95% | NO_BASE+UNREADABLE share | secondary |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        fam_row("merged_", "merged"),
        fam_row("closed_unmerged_", "closed unmerged"),
        "",
        f"Primary rate (pooled) = ALREADY_RED / (ALREADY_RED + NEW_RED) = {k('already_red')} / {k('n_rateable')} = "
        f"{k('rate')}, Wilson 95% {k('lo')} to {k('hi')}. NO_BASE_SIGNAL + UNREADABLE = {k('no_base')} + "
        f"{k('unreadable')} of {k('with_failed')} PRs with a failed check ({k('unrated_share')}); the validity ceiling "
        "is 50%." + ("" if valid else " **That share exceeds 50%: the primary rate is not a valid answer for idea 3 and "
                                      "is shown only as indicative.**"),
        "",
        "## Decision (pre-registered rule, threshold ASSUMED)",
        "",
        v["_sentence"],
        "",
        nt.get("decision", ""),
        "",
        "## Hand check",
        "",
        f"`random.Random(2).sample(sorted(urls_with_failed_check), 20)`, drawn before any rate was computed: "
        f"{k('hand_n')} PRs, automatic verdict agreed with the hand verdict on first reading for {k('hand_agree')}, "
        f"disagreed for {k('hand_disagree')}. Rows: `handcheck.jsonl` (automatic verdict, hand verdict, four "
        "confirmed fields with notes).",
        "",
        nt.get("handcheck", ""),
        "",
        "## What was verified, reused, and not checked",
        "",
        nt.get("verified", ""),
        "",
    ]
    (HERE / "REPORT.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
