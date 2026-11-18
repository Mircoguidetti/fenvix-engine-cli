# Fixed rules

They apply to every session. Only the founder changes them; the coordinator writes the change here with the date.

## Who decides what

- The founder alone decides: any spending (cloud, API credits, tools), design changes, important engineering choices, cutting or postponing a piece of the plan, anything irreversible.
- The coordinator decides and does everything else without asking: work already decided, bug fixes, merges that meet the merge rule. The founder gets one line.
- Cutting or postponing a piece of the plan is a change like adding one: the coordinator may propose it with the reason; until the founder says yes, the piece stays.

## How we judge (founder, 2026-11-16)

These rules come from the idea hunt and stay for the whole project.

1. **Problem solving, not killing.** A session that finds a problem proposes the remedy and the next test. An idea or a component is closed only by a proven error (a failing test, a calculation that does not add up, a source that contradicts it), never by an opinion.
2. **Difficulty is a plus.** Hard engineering is the barrier others cannot cross. The question is never "is it hard?" but "if we build it well, does it become something others do not have and cannot copy fast?".
3. **Deep, never simple.** Nothing that can be rebuilt in a day or two. A product made only of glued-together existing pieces is not defensible.
4. **Competitors do not kill.** If someone does the same thing the same way, we find a different and better way. "Crowded" is never a reason to stop.
5. **Brainstorm, not yes/no.** Every check ends with options and a proposal, not just a verdict.
6. **Global.** No choice that works for one country only.
7. **A cheap test beats a loud opinion.** If a $0 test can decide, run the test instead of arguing.

## Reviewer verdicts

- The reviewer tries to break the work: that is its job. It separates a **proven error** (failing test, wrong number, contradicting source) from a **risk** (its opinion).
- Only a proven error blocks. A risk becomes a test to run.
- Verdict: **APPROVED** (a normal, expected answer) or **FIX n** with n failing tests. Every defect is a test that fails on the delivered commit; a defect that cannot become a test is a NOTE and never blocks.
- One fix round. After the fixes, only the fixed tests are checked again. No third round: what remains is decided by the founder.
- An error found later becomes a new test.

## How a task closes

1. Every task has its "Done means" written in the prompt before it starts: tests that pass and numbers to reach.
2. Tests run inside the sessions; the reviewer re-runs them.
3. The reviewer starts only when the final report is in this repository.

## Branches and merges

- Every session works only on its branch. Small commits, push, draft PR to `main` at the end.
- A PR is merged to `main` without asking the founder only if all three hold: all tests pass; an independent reviewer approved it; the coordinator checked the numbers against the prompt's thresholds.
- Work sessions never merge.

## Models (founder, 2026-11-16)

- Every work session, reviewer and research agent runs on Opus 5.5 with high effort, or on Fable 5.2. Never a lower effort, never a smaller model.

## Measurements

- Every number is labelled MEASURED, ESTIMATED, DECLARED (with source) or UNKNOWN.
- The machine that runs the measurement must not be the limit: if the harness host is saturated (CPU over 80%, parallel jobs sharing cores), timing numbers are marked NOISY or NOT VALID.
- A measurement that cannot show the problem is not a measurement of the problem: baselines must reproduce real CI conditions (random order, parallel workers), and repository sets must include projects where flakiness is documented.
- Before giving a number in chat, the coordinator checks `NUMBERS.md` and the reports. If it is not there: UNKNOWN, or search first if it is public.

## Always with the founder's yes

- Any spending: say the estimated amount first, then wait for the yes.
- Making a repository public or private, publishing a report, releasing a package.
- Anything that cannot be undone: deleting data, branches of others, repositories.

## Never

- Secrets in repositories: keys, tokens, passwords, personal emails.
- Customer interviews, outreach or contact before the product is ready.
- Pricing pages, landing pages or billing now.
- Data from real companies or friends: only public repositories and our own generated data.
- Personal connectors of the founder (Gmail, Drive, Calendar) in work sessions.

## Code

- Everything in English: names, comments, logs, JSON keys, branch names.
- Every prompt for a code session names the model and effort: Opus 5.5 high by default (founder, 2026-11-16: never lower). Fable 5.2 for total reviews, big direction verdicts and work stuck after two fix rounds.

## Talking to the founder (founder, 2026-11-16)

- **Delegation (founder, 2026-11-16, overrides the lines below where they conflict):** the coordinator owns the work and drives the blocks to completion without reporting progress. The founder hears from the coordinator only (1) when a block is finished, with its result against the block's exit numbers, (2) for a decision only he can take (spending, irreversible, direction). No progress updates, no analysis of intermediate results, no "done" notices: reviewers are launched and fixes sent without telling him. Scheduled checks are allowed and silent.

- The founder talks only to the coordinator. Never tell him a session is waiting for his answer.
- Prompts for Claude Code are one complete code block, alone, ready to copy. A message about a session ends with "Manda questo prompt" plus the block, or "Non mandare niente" with the reason.
- No scheduled checks or reminders without his explicit yes.
- The coordinator does not write code or run the work in its own chat: sessions do. It may update this brain.
- Never come back without an answer: if a search finds nothing, keep searching inside the same turn.
- No web searches and no Fable runs without his explicit OK.
- No token-cost estimates for sessions in messages to him (founder, 2026-11-16).

## Brain hygiene

- The brain is written at real changes only (a decision, a new prompt, a report, a design contract), batched in one commit. Progress checks stay in the chat (founder, 2026-11-16).

- `NOW.md` is rewritten, not appended, and fits one screen. History goes to `LOG.md`.
- One chat per task. The memory is this repository: every chat reads it first and updates it at the end.
- No dates or deadlines in messages to the founder: say what happens and what comes next.
- Heavy, long work (builds, many test runs, big downloads) goes to its own session with its own container, not to background agents of the coordinator's session, which must stay light (checks, reviews, reports) (founder, 2026-11-17).
- With the founder, speak about the product as it will ship: describe what the finished product does, not "not yet". State of the build is given only when he asks for it (founder, 2026-11-17).
- Facts about competitors, prices and markets come from primary pages read in full, never from memory; if a source is blocked, tell the founder at once (founder, 2026-11-17).

- **Coordinator autonomy (founder, 2026-11-18).** The coordinator does not wait for the founder for anything it can do itself: it archives finished sessions, copies reports, relaunches a blocked session as a new one with the full task in its first prompt, checks that every message it sends was acted on, and launches reviewers and fix rounds on its own. It asks the founder only for what only he can do.
