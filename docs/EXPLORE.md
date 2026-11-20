# Nightly exploration

`fenvix explore` runs the whole suite under seeds (each seed shuffles the order and seeds every generator), keeps
the tests that fail under one seed and pass under another, and turns each into a defect bundle (docs/BUNDLE.md).

```bash
fenvix explore --budget 60                     # one hour: seeds 1, 2, ... until the budget is spent
fenvix explore --budget 60 --resume            # continue after the last seed of the previous exploration
fenvix explore --budget 20 --changed-since origin/main   # only the test files changed on this branch
fenvix explore --budget 20 --only-unstable     # only the test files of the tests found flaky last time
fenvix explore --budget 60 --runner unittest -- discover -s tests    # another Python runner
```

Memory between nights: `--resume` reads `<out>/explore-state.json` (`last_seed`) and starts after it, so successive nights
explore new seeds instead of repeating seeds 1..N. Keep `<out>` between runs (the cache step below).

## GitHub Actions: a nightly job

```yaml
name: fenvix-explore
on:
  schedule: [{cron: "17 2 * * *"}]
  workflow_dispatch: {}
jobs:
  explore:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.13"}
      - run: pip install -e . fenvix          # your project and the engine
      - uses: actions/cache@v4                 # the seeds the previous nights explored
        with:
          path: .detpy/repro/explore-state.json
          key: fenvix-explore-${{ github.run_id }}
          restore-keys: fenvix-explore-
      - run: fenvix explore --budget 90 --resume
      - uses: actions/upload-artifact@v4       # the defect bundles: `fenvix replay <dir>` on a laptop
        if: always()
        with: {name: fenvix-defects, path: .detpy/repro/bundles/, if-no-files-found: ignore}
```

The exploration summary (`explore.json`) lists the seeds explored (`seeds_log`), the
flaky failing tests, the always-failing ones (not flaky: broken), the bundles and their families (same first
divergent event, same polluters).
