# test-quality-count status

PAUSED 2026-11-27 20:25Z until Mon 2026-12-01 09:00 UTC or the coordinator's RESUME (credits). On resume: pull the
re-read results of chunks 1-3 (run 46036935910, pushes on its own), re-queue requests 4-6 then 7-10 (150 each,
max_minutes 105, issues_route session), then issues, hand reads, report, verify, AC4 round 2.

RESUMED 2026-11-27 10:05Z (coordinator instruction, early resume). Paused 05:40Z-10:05Z.

- Discovery: done (N 58,715; 341 leaves, 0 incomplete, 0 pages lost).
- Chunk 1 (candidates 0-149): read, issues searched, 160 hand reads, report rendered, verify.py 0 mismatches.
  Decision check: KEEP READING (read 115, running 10, pain yes 4, unknown 2, no 4).
- Chunk 2 (150-299): read, issues searched, 93 hand reads (4 confirmed, 12 information, 77 rejected), report rendered.
- Chunk 3 (300-449): read (33.6 min), issues searched, 147 hand reads (2 confirmed, 12 information, 133 rejected).
- Chunks 4-5 (450-749): read (one run), issues searched, 174 hand reads (0 confirmed, 6 information, 168 rejected).
- Chunks 6-7 (750-1049): read, issues searched, 156 hand reads (2 confirmed, 7 information, 147 rejected; obsidian-roamer #22 set to information by the session: time reason only implied).
- Chunks 8-10 (1050-1499): read, issues searched, 430 hand reads (2 confirmed after session review, 16 information, 412 rejected; ArloL/drifty d6ab3e5 set to information: run added and moved in the same PR).
- AC4 round 1 (83 samples): stop rule hit (4 tool-present-unlinked samples are running). Rule fixed (CHANGES.md 21); round-1 rows archived in results/v1/; re-reading candidates 0-1499 (requests 1-3 queued, 4-10 next).
- Round-1 totals (superseded): read 1106, running 109, pain yes 30. No decision claimed.
