| project | transitions | tests | time skipped median / mean | tests skipped median / mean | cache run vs full run, median (A / B) | capture overhead (median, n) | cold / plain pytest (median) | verified reuses (wrong, flaky) | invalidate-all commits |
|---|---|---|---|---|---|---|---|---|---|
| runner-django-debug-toolbar | 20 | 378 | 100% / 80% | 100% / 80% | 54% (1.5s / 2.8s) | +47% (3) | 1.37x | 6014 (0, 0) | 4/20 |
| runner-django-healthchecks | 20 | 1643 | 16% / 42% | 11% / 40% | 110% (25.3s / 22.9s) | +16% (3) | 1.18x | 13288 (0, 0) | 9/20 |
| runner-doctest-autopep8 | 20 | 1 | 100% / 85% | 100% / 85% | 114% (0.3s / 0.2s) | +82% (3) | 3.34x | 17 (0, 0) | 3/20 |
| runner-doctest-nameparser | 20 | 1 | 0% / 30% | 0% / 30% | 154% (0.6s / 0.4s) | +215% (3) | 2.58x | 6 (0, 0) | 14/20 |
| runner-nose2-howdoi | 19 | 25.0 | 0% / 0% | 4% / 3% | 114% (1.7s / 1.4s) | +17% (2) | 0.98x | 16 (0, 0) | 19/19 |
| runner-nose2-nose2 | 20 | 333 | 21% / 13% | 76% / 46% | 94% (21.0s / 21.7s) | +18% (3) | 1.08x | 3031 (0, 0) | 8/20 |
| runner-unittest-icecream | 20 | 44 | 0% / 10% | 0% / 11% | 141% (0.6s / 0.5s) | +44% (3) | 1.46x | 106 (0, 0) | 18/20 |
| runner-unittest-jc | 20 | 1440 | 0% / 25% | 0% / 25% | 116% (5.1s / 4.3s) | +22% (3) | 1.13x | 7655 (0, 0) | 14/20 |
| runner-ward-ward | 3 | 389.0 | 0% / 0% | 0% / 0% | 135% (1.1s / 0.8s) | +44% (2) | 1.39x | 0 (0, 0) | 3/3 |
| runner-zope-datetime | 20 | 53 | 0% / 36% | 0% / 35% | 168% (0.5s / 0.3s) | +77% (3) | 2.11x | 370 (0, 0) | 12/20 |
| runner-zope-irclog2html | 20 | 89 | 0% / 40% | 0% / 41% | 135% (0.6s / 0.4s) | +60% (3) | 2.22x | 725 (0, 0) | 11/20 |
