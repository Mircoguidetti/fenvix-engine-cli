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

<<probe>>
Run 45569492615 (2026-11-25), 77 requests, every endpoint HTTP 200 (`results/probe/endpoints.json`, raw JSON
`results/probe/raw.json`, tree listings cut to 200 entries). Logins (`results/probe/logins.json`): Copilot pull
request author `Copilot`, commit author `Copilot` (git name `copilot-swe-agent[bot]`); Devin
`devin-ai-integration[bot]` for both; Jules `google-labs-jules[bot]` for both; Codex pull request author
`pawelekbyra`, commit author login null; Claude Code pull request author `noahgift`, commit author `noahgift`, no
commit with the Claude trailer (that pull request's commits count as human: the undercount the spec lists).
`claude[bot]` was not seen.
