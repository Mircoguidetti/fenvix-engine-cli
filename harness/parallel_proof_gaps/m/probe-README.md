# Probe: what calls record the recursive-write roots of step M "after (c)+(b)"

Founder decision D1 = A step 1. Engine: 4b364a38 with a log-only patch in `installFootprint` (not committed): every new
`wr` / `lr` key in a file's footprint appended `{op, set, key, abs, existed, label}` to `/home/user/fp-log/<pid>.log`
through the original `fs.appendFileSync` / `fs.lstatSync`, `existed` taken just before the real call. Run:
`measure.py --reps 1 --workers 4 --skip plain,plain_par,serial` on yalc, drydock, alakajam, ironcurtain,
codex-multi-auth (each exit 0). The patch was reverted afterwards (the worktree is at 4b364a38 again).

- `probe-causes.txt`: per repository, each hazard root (w4) with the calls that recorded it, by (op, existed).
- `probe-calls.jsonl.gz`: every logged call.

`op` is the last wrapped fs function entered in that process; it is stale for a few entries (e.g. `readFileSync` on
alakajam `data/tmp`), so the op is indicative. `existed` and `key` are measured directly.
