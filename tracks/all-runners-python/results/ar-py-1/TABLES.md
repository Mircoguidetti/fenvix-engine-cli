| project | transitions | tests | time skipped median / mean | tests skipped median / mean | cache run vs full run, median (A / B) | capture overhead (median, n) | cold / plain pytest (median) | verified reuses (wrong, flaky) | invalidate-all commits |
|---|---|---|---|---|---|---|---|---|---|
| runner-django-debug-toolbar | 20 | 378 | 100% / 80% | 100% / 80% | 63% (1.8s / 2.9s) | +51% (3) | 1.64x | 6014 (0, 0) | 4/20 |
| runner-django-healthchecks | 0 | 1642 | - / - | - / - | - (- / -) | +16% (1) | 1.15x | 0 (0, 0) | 0/0 |
| runner-doctest-autopep8 | 20 | 1 | 100% / 85% | 100% / 85% | 113% (0.3s / 0.3s) | +72% (3) | 3.18x | 17 (0, 0) | 3/20 |
| runner-nose2-howdoi | 19 | 25.0 | 0% / 0% | 4% / 3% | 111% (2.3s / 2.1s) | +15% (2) | 0.97x | 15 (0, 0) | 19/19 |
| runner-nose2-nose2 | 20 | 333 | 0% / 0% | 0% / 0% | 116% (23.5s / 20.4s) | +16% (3) | 1.08x | 0 (0, 0) | 20/20 |
| runner-unittest-icecream | 20 | 44 | 0% / 10% | 0% / 11% | 142% (0.5s / 0.4s) | +46% (3) | 1.38x | 106 (0, 0) | 18/20 |
| runner-unittest-jc | 20 | 1440 | 0% / 25% | 0% / 25% | 119% (7.2s / 6.2s) | +23% (3) | 1.14x | 7655 (0, 0) | 15/20 |
| runner-ward-pointers | 3 | 24.0 | 0% / 0% | 0% / 0% | 162% (0.4s / 0.3s) | +189% (1) | 1.43x | 0 (0, 0) | 3/3 |
| runner-ward-ward | 3 | 409.0 | 0% / 0% | 0% / 0% | 137% (1.1s / 0.8s) | +35% (1) | 1.07x | 0 (0, 0) | 3/3 |
| runner-zope-datetime | 20 | 53 | 0% / 10% | 0% / 10% | 170% (0.7s / 0.4s) | +69% (3) | 2.27x | 107 (0, 0) | 17/20 |
| runner-zope-irclog2html | 20 | 89 | 0% / 15% | 0% / 18% | 141% (0.6s / 0.4s) | +61% (3) | 2.23x | 328 (0, 0) | 12/20 |
