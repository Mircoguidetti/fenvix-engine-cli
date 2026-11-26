# Step M: measurements of spec parallel-proof-gaps

Nine pool repositories (`harness/parallel_measure/specs.json`), each through `harness/parallel_measure/measure.py` via
`run_point.sh` (serial w1, parallel w2 and w4, `fenvix verify`; phases plain and plain_par skipped). `--reps 1` unless
stated. Speed ratio ("misura A", founder decision 2026-11-26) = parallel wall / serial wall of the same round; lower is
better. The tables per point are in `m/` (`*.md`; raw rows `*-results.jsonl`); output dirs are named in `m/*-dir*.txt`.

## Points

| point | engine | what it adds | table |
|---|---|---|---|
| before | f3c6711d (release-1 sources) | - | m/before.md |
| cb | 4b364a38 | (c) skip dirs + (b) recursive roots | m/cb.md |
| cb2 | 4b364a38 + D1 = A mkdir fix | wr root only at the first missing dir | m/cb2.md |
| cb3 | 4b364a38 + mkdir fix + B1 + C1 (m/cb3-engine.diff) | plain listing only vs dirname; mkdir of an existing dir is a read | m/cb3.md |
| a | c657dd55 | + (a) shared services | m/a.md (vs cb3), m/a-vs-before.md |
| a2 | f80ce6cf, REPS=2 | + remote hosts recorded, never paired (D1 = A) | m/a2.md |
| cold | cb42cccf, 3 fresh dirs (agentsys, alakajam) | + alakajam A fixes (re-run accounting, outcomes) | m/cold.md |

## Stop history

1. **cb** (vs before, best-worker wall): codex +64.5 %, ironcurtain +120.1 %, yalc +36.0 %, drydock +26.2 %. Cause:
   mkdir -p of existing dirs recorded as recursive roots ('/tmp', the tmpdir, '.'); m/probe-README.md. Fix: founder
   D1 = A (wr root only at the first missing directory).
2. **cb2**: codex +57.8 %, ironcurtain +54.9 %. Cause: one file listing /tmp paired with per-test dirs under it by the
   ancestor-listing rule (m/cb2-roots.txt). Fix: B1 (a plain listing conflicts only with dirname(D)); C1 added.
   **cb3**: not triggered (worst ironcurtain +21.5 %).
3. **a** (vs cb3): codex +27.1 % (4 shared-service hazards, one on tcp:raw.githubusercontent.com:443), lerna-lite
   +47.2 % (no (a) hazard; cb3's lerna time was the outlier). Founder: D1 = A (remote hosts never paired), D2 = A
   (re-measure with 2 rounds).
4. **a2** (misura A, round 1 cold vs before): agentsys w4 +29.2 %, alakajam w2 +30.9 %, w4 +43.3 %. Round 2 was warm
   (learned costs and together-groups), so only round 1 judged. Founder "alakajam A": explain the incomplete re-run,
   fix, re-measure with 3 cold rounds.
5. **cold** (mean of 3 cold ratios vs before): alakajam w2 +29.0 %, w4 +48.5 %; agentsys within (+10.8 %, +18.5 %).
   Founder STOP 5 "alakajam ok": accepted as the price of a real shared-state hazard (the sqlite under data/tmp: its
   tests remove and recreate data/tmp; the recursive-write root "data" puts 21-22 of 27 files into the one-lane
   re-run, 11 before (b)); (b) unchanged. Step M closed.

## Wall seconds (speed ratio) per point, round 1

| repository | w | before wall s (ratio) | cb wall s (ratio) | cb2 wall s (ratio) | cb3 wall s (ratio) | a wall s (ratio) | a2 r1 wall s (ratio) |
|---|---|---|---|---|---|---|---|
| agentlang | 2 | 74.48 (0.913) | 65.72 (1.004) | 55.93 (0.668) | 73.78 (0.968) | 80.59 (0.902) | 88.39 (0.936) |
| agentlang | 4 | 80.67 (0.989) | 66.62 (1.018) | 60.37 (0.722) | 74.33 (0.975) | 78.7 (0.881) | 87.32 (0.924) |
| agentsys | 2 | 24.1 (0.986) | 19.52 (1.283) | 18.25 (0.916) | 22.23 (1.253) | 24.05 (1.184) | 27.38 (1.202) |
| agentsys | 4 | 18.7 (0.765) | 18.82 (1.237) | 16.4 (0.823) | 20.82 (1.174) | 20.25 (0.997) | 22.51 (0.989) |
| alakajam | 2 | 93.78 (1.100) | 92.13 (1.825) | 75.84 (1.050) | 95.46 (1.366) | 96.05 (1.350) | 116.16 (1.440) |
| alakajam | 4 | 70.75 (0.830) | 76.52 (1.516) | 70.65 (0.978) | 84.5 (1.209) | 86.34 (1.213) | 95.97 (1.189) |
| codex-multi-auth | 2 | 336.51 (0.834) | 496.24 (1.345) | 471.11 (1.239) | 345.96 (0.778) | 422.29 (0.937) | 400.93 (0.840) |
| codex-multi-auth | 4 | 288.57 (0.716) | 474.75 (1.287) | 455.34 (1.197) | 288.44 (0.648) | 366.59 (0.813) | 363.44 (0.762) |
| drydock | 2 | 278.73 (0.686) | 267.07 (0.701) | 249.19 (0.657) | 313.31 (0.702) | 372.38 (0.736) | 342.8 (0.720) |
| drydock | 4 | 189.28 (0.466) | 238.93 (0.627) | 178.06 (0.470) | 218.01 (0.488) | 252.24 (0.498) | 237.17 (0.498) |
| ironcurtain | 2 | 185.7 (0.913) | 240.22 (1.211) | 164.29 (0.734) | 122.32 (0.459) | 181.36 (0.690) | 159.12 (0.547) |
| ironcurtain | 4 | 100.74 (0.495) | 221.74 (1.118) | 156.07 (0.697) | 156.88 (0.588) | 104.62 (0.398) | 125.9 (0.433) |
| lerna-lite | 2 | 1136.76 (1.893) | 1111.6 (1.888) | 1109.9 (1.874) | 1137.2 (1.869) | 1143.75 (1.887) | 819.68 (1.361) |
| lerna-lite | 4 | 905.06 (1.507) | 906.19 (1.539) | 889.46 (1.501) | 626.51 (1.030) | 922.05 (1.521) | 913.41 (1.516) |
| nestjs-pino | 2 | 12.96 (0.511) | 12.24 (0.645) | 10.55 (0.260) | 13.36 (0.654) | 13.39 (0.519) | 15.69 (0.574) |
| nestjs-pino | 4 | 9.94 (0.392) | 8.01 (0.422) | 6.77 (0.167) | 8.9 (0.435) | 9.2 (0.356) | 10.48 (0.383) |
| yalc | 2 | 111.37 (1.226) | 128.81 (1.597) | 91.27 (1.121) | 83.91 (0.936) | 87.38 (0.861) | 103.28 (0.956) |
| yalc | 4 | 87.8 (0.966) | 119.4 (1.480) | 78.2 (0.960) | 67.25 (0.750) | 77.55 (0.764) | 82.53 (0.764) |

| repository | before serial s | cb serial s | cb2 serial s | cb3 serial s | a serial s | a2 r1 serial s | proven % w4 (before -> a2 r1) |
|---|---|---|---|---|---|---|---|
| agentlang | 81.6 | 65.47 | 83.67 | 76.21 | 89.32 | 94.47 | 0.0 -> 0.0 |
| agentsys | 24.44 | 15.22 | 19.92 | 17.74 | 20.31 | 22.77 | 69.3 -> 69.8 |
| alakajam | 85.27 | 50.47 | 72.22 | 69.89 | 71.16 | 80.69 | 0.0 -> 0.0 |
| codex-multi-auth | 403.28 | 368.87 | 380.28 | 444.96 | 450.65 | 477.14 | 0.0 -> 0.0 |
| drydock | 406.42 | 380.88 | 379.18 | 446.5 | 506.11 | 476.02 | 0.0 -> 0.0 |
| ironcurtain | 203.36 | 198.41 | 223.94 | 266.7 | 262.92 | 290.79 | 0.0 -> 0.0 |
| lerna-lite | 600.42 | 588.65 | 592.42 | 608.32 | 606.16 | 602.47 | 0.0 -> 0.0 |
| nestjs-pino | 25.37 | 18.99 | 40.55 | 20.44 | 25.82 | 27.33 | 95.9 -> 95.9 |
| yalc | 90.86 | 80.66 | 81.42 | 89.63 | 101.49 | 108.04 | 0.0 -> 0.0 |

The serial wall moves between points by up to +43 % (ironcurtain) with no lanes or hazards involved: machine noise is
of the order of the effects, which is why the founder judged by the ratio. Proven share is unchanged at every point
(only agentsys and nestjs-pino prove anything; the others read native addons outside tests on any engine).

## 2-round re-measure (a2) and 3 cold rounds

m/a2.md: per round walls, hazards, re-run files; round 2 is warm (yalc w4 hazards 121 -> 0, codex w4 363 -> 157 s).
m/a2-ratio-by-point.txt: agentsys and alakajam ratios at every point.

| repository | w | ratio before (par s / serial s) | cold rounds: ratio (par s / serial s) | mean ratio | change | hazards per round | re-run complete per round | proven % per round (before) |
|---|---|---|---|---|---|---|---|---|
| agentsys | 2 | 0.986 (24.1 / 24.44) | 0.765 (24.85 / 32.48); 1.234 (24.08 / 19.51); 1.278 (24.88 / 19.47) | 1.092 | +10.8 % | 6 / 6 / 6 | True / True / True | 69.9 / 69.9 / 69.9 (69.4) |
| agentsys | 4 | 0.765 (18.7 / 24.44) | 0.580 (18.84 / 32.48); 1.048 (20.45 / 19.51); 1.092 (21.26 / 19.47) | 0.907 | +18.5 % | 8 / 8 / 8 | True / True / True | 69.8 / 69.8 / 69.8 (69.3) |
| alakajam | 2 | 1.100 (93.78 / 85.27) | 1.075 (90.09 / 83.82); 1.402 (91.12 / 64.97); 1.778 (106.05 / 59.63) | 1.419 | +29.0 % | 32 / 32 / 32 | True / True / True | 0.0 / 0.0 / 0.0 (0.0) |
| alakajam | 4 | 0.830 (70.75 / 85.27) | 1.012 (84.8 / 83.82); 1.351 (87.8 / 64.97); 1.334 (79.56 / 59.63) | 1.232 | +48.5 % | 47 / 47 / 45 | True / True / True | 0.0 / 0.0 / 0.0 (0.0) |

STOP RULE (mean cold ratio vs before, misura A): alakajam w2: mean cold ratio 1.100 -> 1.419 (+29.0 %; rounds 1.075, 1.402, 1.778); alakajam w4: mean cold ratio 0.830 -> 1.232 (+48.5 %; rounds 1.012, 1.351, 1.334)

## shared-service hazards seen (a)

drydock: unix:/run/docker.sock (20-31 per run) and loopback ports; codex-multi-auth: loopback ports (chaos/net-faults vs
responses-websocket-interrupt and runtime-rotation-proxy); ironcurtain: 1 loopback port. drydock's Docker socket is a
real local service used from many files, so no extra Postgres suite was added. Remote hosts
(tcp:raw.githubusercontent.com:443 on codex) are recorded and, since f80ce6cf, never paired.

## hazards() before / after (largest pool repo: drydock, 651 files, w4)

The lane markers of one drydock w4 run per engine were dumped with a scratch-only patch (m/hazards-timing-dump.diff,
never committed to the engine) and hazards() was timed 25 times on them (m/bench-hazards.js, m/hazards-timing.jsonl):

| engine | markers of | footprint keys | hazards | median ms (min / max) |
|---|---|---|---|---|
| f3c6711d (before) | its own run | 6 039 | 0 | 21.52 (20.09 / 61.59) |
| cb42cccf (after) | its own run | 6 977 | 31 | 6.07 (4.68 / 15.88) |
| cb42cccf (after) | the before run | 6 039 | 47 | 3.20 (2.79 / 11.84) |

hazards() is faster after (sorted-index range queries), and a few milliseconds against a 215 s parallel run: far
below the 5 % of collect time the spec sets for a report.
