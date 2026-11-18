# Cache with proof step 1, R-009 fix round: run s1g (home-assistant, engine df409cb)

| project | transitions | tests | time skipped median / mean | tests skipped median / mean | cache run vs full run, median (A / B) | capture overhead (median, n) | cold / plain pytest (median) | verified reuses (wrong, flaky) | invalidate-all commits |
|---|---|---|---|---|---|---|---|---|---|
| home-assistant | 49 | 11897.0 | 94% / 76% | 97% / 78% | 39% (41.4s / 78.7s) | +21% (6) | 1.48x | 455510 (0, 2) | 7/49 |
