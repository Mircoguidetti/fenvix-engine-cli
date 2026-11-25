<<status>>
NOT DONE

<<changes>>
1. 2026-11-25, after the §0 probe, before chunk 1 (no frame data read): Codex agent commits. The probe shows the
   Codex commits of `pawelekbyra/polutek-pl#1281` with no linked author login (`author: null`; git author name equals
   the pull request author). Under PREREG §1.6 (author login equals the pull request author) every Codex commit would
   be `human`. Changed rule: on a pull request whose head ref starts with `codex/`, a commit is the agent's when its
   author login equals the pull request author **or is null** (no linked GitHub account). The commit listing trim now
   also keeps `commit.author.name` (reported, not used by the rule). Code: `rules.is_agent_commit`; test
   `test_agent_commits`.

2. 2026-11-25, after Count A's last chunk, before any Count A result was reported: rules (ii) and (iv) of §1.7,
   under PREREG §1.9 / gate rev 4 note 5. The 30-row `not-wasted` sample (19 rows: fewer than 30 `not-wasted`, so
   all) had **9 misses**: agent commits that plainly fix an X that was red on the base and were not `wasted`
   (`handread_a_sample.jsonl`). Two rule gaps explain them: the fix message rule wanted a CI word within 30
   characters after the verb ("Fixes `TS2322` compilation error during Docker build", "Fixing Portal Build",
   "fix(proto): ... CI runs -D rustdoc::broken_intra_doc_links"), and a commit at which X turns green with no fix
   wording (a mise hash, a rustls bump, a gitops validator change) has no rule at all, because the evidence rule (i)
   finds failure files for only 8.7% of rateable pull requests. Changed rules: (ii) a fix verb (`fix`, `fixes`,
   `fixed`, `fixing`, `repair*`, `resolve*`, `unbreak*`, `unblock*`) anywhere in the message **and** a CI term
   (`ci`, `build(s)`, `test(s)`, `check(s)`, `pipeline(s)`, `lint*`, `clippy`, `workflow(s)`, `e2e`, `compile*`,
   `compilation`, `type-check*`, `rustdoc`) anywhere in the message, same NEW_RED guard; new (iv): the agent commit at
   which X passes (the window end when X's state there is `pass`). Rule (i) and (iii) are unchanged. Every Count A
   row was re-run offline from the committed raw responses (`rerun_a.py`, no request; rows before the change kept as
   `results/a_rows_rule1.jsonl`): 11 rows became `wasted`, none left it; only those 11, and the commits newly hit
   on 2 rows already read, were newly hand-read. The sample is not drawn again (it stays the pre-change draw), and
   with more than 3 misses no miss adjustment applies. Code: `rules.fix_message`, `rules.wasted_reasons`
   (`turns_green`), `pipeline.count_a`; tests `test_wasted_rules`, `test_fix_message_change_2`,
   `test_commit_after_x_passes_again_not_counted`, `test_already_red_at_commit_two_of_four_then_green_is_rateable`.

<<probe>>
Run 45569492615 (2026-11-25), 77 requests, every endpoint HTTP 200 (`results/probe/endpoints.json`, raw JSON
`results/probe/raw.json`, tree listings cut to 200 entries). Logins (`results/probe/logins.json`): Copilot pull
request author `Copilot`, commit author `Copilot` (git name `copilot-swe-agent[bot]`); Devin
`devin-ai-integration[bot]` for both; Jules `google-labs-jules[bot]` for both; Codex pull request author
`pawelekbyra`, commit author login null; Claude Code pull request author `noahgift`, commit author `noahgift`, no
commit with the Claude trailer (that pull request's commits count as human: the undercount the spec lists).
`claude[bot]` was not seen.
