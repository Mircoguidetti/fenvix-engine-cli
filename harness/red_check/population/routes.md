# C5.3: route to third-party job logs (every attempt)

Route 1 (Count 2's): GitHub Actions in this repository, workflow `.github/workflows/red-check-population.yml`,
`GITHUB_TOKEN`, read-only on other repositories. Count 2 never read job logs on it; this probe (spec 2.1) does, before
any other request of C5.3.

Log read: `GET repos/{o}/{r}/actions/jobs/{id}/logs` with `Authorization` attached by `add_unredirected_header` and no
automatic redirect follow (`ghrest.py`); the 302's `Location` (signed blob URL) is read by a second request without
`Authorization`. API status and blob status are recorded apart. Unit test: `test_probe.py::test_authorization_not_sent_to_redirect_host`.

## Probe 2.1 (request `requests/probe.json`, results `results/probe_probe.json`)

| When (UTC) | Run | Requests | Verdict | Rate headers after the probe |
|---|---|---|---|---|
| 2026-11-25 21:10 | 45701805964 (push of commit 4471172; results committed by the job as c292db5) | 4 of at most 10 | **works** | `X-RateLimit-Limit` 5000, remaining **47** |

Jobs were taken from Count 2's raw check runs (`results/raw/*.jsonl.gz`, `results/supplement/2.jsonl.gz` on
`origin/claude/agent-pr-scan-count2`; app `github-actions`, conclusion failure/timed_out, `completed_at` >= 2026-10-27),
newest first, one per repository. The first two answered; the other three listed in the request were not read.

| Job | PR | completed_at (age) | API status | Blob status | Body bytes | First 200 characters |
|---|---|---|---|---|---|---|
| xikimay/nirux 132973304825 (`test`) | xikimay/nirux#551 | 2026-11-15T22:01:33Z (9.1 d) | 302 | 200 | 920,764 | `﻿2026-11-15T21:59:18.8684250Z Current runner version: '2.338.2'\n2026-11-15T21:59:18.8699470Z ##[group]Runner Image Provisioner\n2026-11-15T21:59:18.8700080Z Hosted Compute Agent\n2026-11-15T21:59:18.870` |
| nikolay-e/diffctx 132869934598 (`Rust diffctx tests (ubuntu-latest, 1/2)`) | nikolay-e/diffctx#762 | 2026-11-15T20:21:03Z (9.2 d) | 302 | 200 | 169,933 | `﻿2026-11-15T19:49:03.1602033Z Current runner version: '2.338.2'\n2026-11-15T19:49:03.1637879Z ##[group]Runner Image Provisioner\n2026-11-15T19:49:03.1639288Z Hosted Compute Agent\n2026-11-15T19:49:03.164` |

Notes:
- Logs start with a UTF-8 byte-order mark (`﻿`) before the first timestamp: 2.5's line cleaning strips it.
- `X-RateLimit-Remaining` was 47 of 5000 after these 4 requests: the repository's `GITHUB_TOKEN` budget was nearly
  spent by other work at 21:10 UTC (the shared budget the coordinator gates with `C5.3 budget free`).
