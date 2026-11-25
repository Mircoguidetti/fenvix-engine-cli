#!/usr/bin/env bash
# Commit the files this workflow writes (never the work session's files) to the count branch, with retries.
# Used by the 30-minute checkpoint loop and by the final commit step. $1: commit message suffix.
set -u
out=harness/agent_determinism_count/results
[ -d "$out" ] || exit 0
own="rows.jsonl raw chunks.jsonl chunk_errors.jsonl requests_done texts_search_wf.jsonl texts_raw_wf comments.jsonl comments_raw probe_workflow.json probe_workflow_text.json prepass_text.json launch.json discovery_state_text.json discovery/leaf_parts_text.json discovery/restore_text.json discovery/splits_text.jsonl debug"
# leaf files stay out of git (GitHub refuses files over 100 MB): the index with their sha256 is committed instead
python3 harness/agent_determinism_count/parts.py index || true
for i in 1 2 3 4 5 6 7 8; do
  git fetch -q origin "$ADC_BRANCH" && git reset -q --soft "origin/$ADC_BRANCH" && git reset -q
  for p in $own; do if [ -e "$out/$p" ]; then git add -f "$out/$p"; fi; done
  git commit -q -m "agent-determinism-count: results (${1:-checkpoint})" || exit 0
  git push -q origin "HEAD:$ADC_BRANCH" && exit 0
  sleep $((5 + RANDOM % 20))
done
exit 1
