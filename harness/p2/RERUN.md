# P2: rerunning every number

Machine and engine identities: `PREREG.md` §1-2. Every row of `data/*/results.jsonl` carries its command (`cmd`) and
directory (`cwd`); `data/*/fixed.jsonl` rows also carry their environment (secrets redacted).

## Setup (as run on 2026-11-25)

```bash
export FENVIX=/home/user/fenvix-engine-cli PM_WORK=/root/pm          # PM_WORK outside the checkout, not under /tmp
cd $FENVIX && git checkout claude/p2-speed
# baseline engine (release-1 6e79a62) with the branch's harness (gate note 9: after 4c93a55 was pushed)
git worktree add /home/user/fx-base 6e79a62 && (cd /home/user/fx-base && git checkout claude/p2-speed -- harness/parallel_measure)
python3.12 -m venv $PM_WORK/venv/engine && $PM_WORK/venv/engine/bin/pip install maturin pytest
ln -sfn $PM_WORK/venv/engine $PM_WORK/venv/networkx                  # RERUN.md §4 (fenvix_python of most Node specs)
(cd /home/user/fx-base/node && npm run build)                         # addon
(cd /home/user/fx-base && $PM_WORK/venv/engine/bin/maturin build --release -o $PM_WORK/wheels-base)
$PM_WORK/venv/engine/bin/pip install --force-reinstall $PM_WORK/wheels-base/fenvix-*.whl
PM_WORK=$PM_WORK bash harness/p2/setup_repos.sh                       # the 9 repositories: specs.json commit + install
```

A fix head or the final head: build its addon and wheel in its own checkout the same way and reinstall the wheel into
`$PM_WORK/venv/engine` before its re-measure.

## Measure (Phase A; Phase D and the per-fix re-measures are the same with another engine checkout and out dir)

```bash
for r in nestjs-pino agentsys alakajam agentlang yalc ironcurtain codex-multi-auth drydock lerna-lite; do
  harness/p2/run_rounds.sh /home/user/fx-base $FENVIX/harness/p2/data/baseline $r "1 2 3" base1 base2 base3
done
python3 harness/p2/table.py baseline harness/p2/data/baseline > harness/p2/BASELINE.md
```

`run_rounds.sh` runs one measure.py process per round (`--reps 1 --first-rep k --workers 2,4 --timeout 7200`, no
`--skip`), then `post.py` (extracts) and the fixed-epoch runs (`fixed_run.py --engine <checkout> --label <L>`),
committing and pushing `data/` every 30 minutes and after every step. Long repositories are run one round per
harness task (`"1"`, `"2"`, `"3"`, then the fixed labels with rounds `""`).
