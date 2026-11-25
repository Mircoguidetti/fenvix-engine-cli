#!/usr/bin/env python3
"""Write REPORT.md from the committed rows and hand reads (numbers marked <value><!--key--> for verify.py).

Hand-written text (rule changes after PREREG, hand-read notes, limits) comes from report_notes.md, inserted at
the marked places (``<<name>>`` sections; ``{{key}}`` inside them is replaced by the marked value).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import verify as V  # noqa: E402

NAMES = {"copilot": "Copilot", "devin": "Devin", "jules": "Jules", "codex": "Codex", "claude_code": "Claude Code"}


def notes() -> dict[str, str]:
    p = HERE / "report_notes.md"
    if not p.exists():
        return {}
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
    arows = J.read_jsonl(res / "a_rows.jsonl")
    brows = J.read_jsonl(res / "b_rows.jsonl")
    ha, hs, hb = V.load_hand()
    v = V.values(arows, brows, ha, hs, hb)

    def k(key: str) -> str:
        return f"{v[key]}<!--{key}-->"

    nt = {n: re.sub(r"\{\{([a-z0-9_]+)\}\}", lambda m: k(m.group(1)), t) for n, t in notes().items()}
    first = nt.get("status", "DONE").splitlines()[0]
    L = [first, "", "# Agent tools count: wasted agent fixes on reds already there (A), competing agent pull "
                    "requests (B)", "",
         "Pre-registration: `PREREG.md` (committed before any data; see the git order below). Re-derivation: "
         "`python3 harness/agent_tools_count/verify.py` (exit 0). Report: `python3 harness/agent_tools_count/"
         "report.py`.", "",
         "## Changes after the pre-registration (each with its justification, before any result)", "",
         nt.get("changes", "None."), "",
         "## Route and budget", "",
         f"GitHub Actions in this repository (`.github/workflows/agent-tools-count.yml`, `GITHUB_TOKEN`, GET only). "
         f"{k('chunks')} data chunks ({k('chunks_a')} Count A, {k('chunks_b')} Count B), {k('requests')} REST "
         f"requests in all (probe included). Count A: {k('requests_a')} requests, {k('req_per_pr')} per pull "
         f"request, {k('a_hours')} h of workflow time. Count B: {k('requests_b')} requests, {k('req_per_issue')} per "
         f"issue read, {k('b_hours')} h.", "",
         nt.get("budget", ""), "",
         "## §0 Probe", "", nt.get("probe", ""), ""]
    if arows:
        L += ["## Count A: wasted agent commits on reds that were already there", "",
              f"Frame: Count 2's 1,500 pull requests in its read order; read: {k('a_read')}. Results (after the "
              f"hand read): rateable {k('a_rateable')} = wasted {k('a_wasted')} + not-wasted {k('a_not_wasted')} + "
              f"no-later-commit {k('a_no_later')}; uncertain {k('a_uncertain')}; not rateable (no already-red X at "
              f"any commit) {k('a_not_rateable')}.", "",
              f"**Rate A = {k('a_wasted')} / {k('a_rateable')} = {k('a_rate')}** (Wilson 95% {k('a_lo')} to "
              f"{k('a_hi')}). Rateable pull requests with `files` evidence for at least one X: {k('a_files')} "
              f"({k('a_files_share')}; validity floor 40%).", "",
              "| Family | read | rateable | wasted | not-wasted | no-later-commit | uncertain | Rate A | Wilson 95% | "
              "files evidence |", "|---|---|---|---|---|---|---|---|---|---|"]
        for f, name in list(NAMES.items()) + [("", "**All (pooled)**")]:
            p = f"{f}_" if f else ""
            L.append(f"| {name} | {k(p + 'a_read')} | {k(p + 'a_rateable')} | {k(p + 'a_wasted')} | "
                     f"{k(p + 'a_not_wasted')} | {k(p + 'a_no_later')} | {k(p + 'a_uncertain')} | {k(p + 'a_rate')} | "
                     f"{k(p + 'a_lo')} to {k(p + 'a_hi')} | {k(p + 'a_files_share')} |")
        L += ["", f"Automatic `wasted` before the hand read: {k('a_auto_wasted')} (rules hit, pull requests: (i) "
                  f"{k('a_reason_i')}, (ii) {k('a_reason_ii')}, (iii) {k('a_reason_iii')}, (iv) {k('a_reason_iv')}). Hand read: "
                  f"{k('a_hand_n')} pull requests; codes W-file {k('a_code_w_file')}, W-msg {k('a_code_w_msg')}, "
                  f"W-ci {k('a_code_w_ci')}, R-product {k('a_code_r_product')}, R-own {k('a_code_r_own')}, R-sync "
                  f"{k('a_code_r_sync')}; {k('a_hand_to_not')} became `not-wasted`. Sample of {k('a_sample_n')} "
                  f"`not-wasted`: {k('a_misses')} misses (miss-adjusted Rate A {k('a_miss_adj')}).", "",
              nt.get("hand_a", ""), "",
              "Information (§1.10):", "",
              f"- Rule (i) hits by `in-base` mark (failure files of wasted pull requests): yes {k('a_inbase_yes')}, "
              f"no {k('a_inbase_no')}, base-unknown {k('a_inbase_base_unknown')}.",
              f"- Pull requests with an already-red X at any commit: {k('a_any_x')} of {k('a_read')}.",
              f"- Rateable with k < last commit: {k('a_k_lt_last')}, Rate A on them {k('a_k_lt_last_rate')}.",
              f"- Single-commit pull requests: {k('a_single_commit')} (rateable {k('a_single_commit_rateable')}).",
              f"- Force-push events: {k('a_force_events')} on {k('a_force_prs')} pull requests (force-pushed commits "
              "are invisible).",
              f"- X by kind (rateable): Actions {k('a_x_actions')}, other check run {k('a_x_check')}, status "
              f"{k('a_x_status')}; Actions-only pull requests {k('a_actions_only')}, Rate A {k('a_actions_only_rate')}.",
              f"- Copilot commits: {k('a_copilot_commits')}; with no check: {k('a_copilot_no_checks')}; all check runs "
              f"`action_required`: {k('a_copilot_action_required')}.",
              f"- Rateable pull requests already red only through base runs of event `pull_request`: "
              f"{k('a_pr_event_only')} (limit inherited from Count 2).",
              f"- Count 2's {k('a_c2_n')} `ALREADY_RED` pull requests here: wasted {k('a_c2_wasted')}, not-wasted "
              f"{k('a_c2_not_wasted')}, no-later-commit {k('a_c2_no_later')}, uncertain {k('a_c2_uncertain')}, not "
              f"rateable {k('a_c2_not_rateable')}.",
              f"- Human non-merge commits after k on rateable pull requests: {k('a_human_after')} on "
              f"{k('a_human_after_prs')} pull requests (reported, never counted).", ""]
    if brows:
        L += ["## Count B: competing agent pull requests for one issue", "",
              f"Repositories taken in the seeded order: {k('b_repos')}; read {k('b_repos_read')} (partial at the "
              f"budget end {k('b_repos_partial')}), skipped (no agent pull request since RACE_FROM on the first "
              f"page) {k('b_repos_skipped')}, unreadable {k('b_repos_unreadable')}, truncated at 10 issue pages "
              f"{k('b_repos_truncated')}. Closed issues read: {k('b_issues')} (timeline unreadable "
              f"{k('b_timeline_errors')}).", "",
              f"Agent-addressed issues: {k('b_addressed')} (single {k('b_single')}, sequential {k('b_sequential')}, "
              f"competing {k('b_competing')}). **Rate B = {k('b_competing')} / {k('b_addressed')} = {k('b_rate')}** "
              f"(Wilson 95% {k('b_lo')} to {k('b_hi')}).", "",
              "| Family (first linked agent pull request) | agent-addressed | competing | sequential | Rate B | "
              "Wilson 95% |", "|---|---|---|---|---|---|"]
        for f, name in list(NAMES.items()) + [("", "**All (pooled)**")]:
            p = f"{f}_" if f else ""
            L.append(f"| {name} | {k(p + 'b_addressed')} | {k(p + 'b_competing')} | {k(p + 'b_sequential')} | "
                     f"{k(p + 'b_rate')} | {k(p + 'b_lo')} to {k(p + 'b_hi')} |")
        L += ["", f"How the merged one was chosen (competing issues; labels combine): first-opened "
                  f"{k('b_label_first_opened')}, first-green {k('b_label_first_green')}, only-green "
                  f"{k('b_label_only_green')}, reviewed {k('b_label_reviewed')}, other {k('b_label_other')}, "
                  f"none-merged {k('b_label_none_merged')}.", "",
              f"Hand read (does not change Rate B): competing sample {k('b_hand_comp_issues')} issues, "
              f"{k('b_hand_comp_links')} links, {k('b_hand_comp_not_attempt_links')} marked not-attempt, "
              f"{k('b_hand_comp_lost')} issues with fewer than 2 same-issue links (share {k('b_hand_comp_share')}); "
              f"agent-addressed sample {k('b_hand_rest_issues')} issues, {k('b_hand_rest_links')} links, "
              f"{k('b_hand_rest_not_attempt_links')} not-attempt, {k('b_hand_rest_lost')} issues without a "
              f"same-issue link (share {k('b_hand_rest_share')}). Symmetric corrected rate (information only): "
              f"{k('b_corrected')}.", "",
              nt.get("hand_b", ""), ""]
    if arows and brows:
        L += ["## Decision", "", "```", *V.decision_lines(v), "```", "", nt.get("decision", ""), ""]
    L += ["## Limits", "", nt.get("limits", ""), "", "## Acceptance criteria", "", nt.get("acceptance", ""), ""]
    (HERE / "REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
