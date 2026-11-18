| project | transitions | tests | time skipped median / mean | tests skipped median / mean | cache run vs full run, median (A / B) | capture overhead (median, n) | cold / plain pytest (median) | verified reuses (wrong, flaky) | invalidate-all commits |
|---|---|---|---|---|---|---|---|---|---|
| home-assistant | 49 | 11897.0 | 80% / 64% | 80% / 64% | 49% (104.0s / 103.6s) | +20% (6) | 1.47x | 374443 (0, 1) | 7/49 |
| structlog | 50 | 920 | 100% / 73% | 100% / 75% | 75% (1.5s / 2.0s) | +28% (6) | 2.22x | 34465 (0, 0) | 11/50 |
