#!/bin/bash
# regenerate TABLE-c.md + results-c.jsonl from the raw files (session C)
H=/home/user/fenvix-engine-cli/harness/parallel_measure; O=/home/user/pm/out-c-d13
cd $H; running="$1"
if [ -n "$running" ]; then grep -v "\"repo\": \"$running\"" $O/results.jsonl > $O/results-done.jsonl; else cp $O/results.jsonl $O/results-done.jsonl; fi
cp $O/results-done.jsonl results-c.jsonl
{
echo "# TABLE-c (measurement session C)"
echo
echo "Machine: 4 CPUs, Intel Xeon @ 2.30GHz, 15 GB. Every number is MEASURED by the command recorded in the raw jsonl (\`cmd\`), medians of 3 rounds, unless marked otherwise. Harness: claude/parallel-measure c55bfd60 (lerna-lite, yalc) / 14132eda (D18 per-repository TMPDIR; later rows), measure.py unchanged otherwise; engine: trunk bfaf70b4."
echo
echo "## Idea verdict (founder rule, coordinator 2026-11-22; idea_verdict_c.py)"
echo
python3 idea_verdict_c.py $O/results-done.jsonl
echo
echo "## Rows — raw: results-c.jsonl"
echo
python3 table.py $O/results-done.jsonl specs.json
echo
echo "## Pre-D13 rows (harness f4686992, engine 5a6463fd, kept apart) — raw: results-c-pre-d13.jsonl"
echo
python3 table.py results-c-pre-d13.jsonl specs.json
echo
cat TABLE-c.notes.md
} > TABLE-c.md
