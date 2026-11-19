| project | transitions | tests | time skipped median / mean | tests skipped median / mean | cache run vs full run, median (A / B) | capture overhead (median, n) | cold / plain pytest (median) | verified reuses (wrong, flaky) | invalidate-all commits |
|---|---|---|---|---|---|---|---|---|---|
| runner-ward-thoughtspot-tml | 20 | 71 | 0% / 0% | 0% / 0% | 114% (2.1s / 1.8s) | +15% (3) | 1.25x | 0 (0, 0) | 20/20 |
| runner-ward-ward | 3 | 389.0 | 0% / 0% | 0% / 0% | 146% (1.1s / 0.8s) | +50% (2) | 1.48x | 0 (0, 0) | 3/3 |
