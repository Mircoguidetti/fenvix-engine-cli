"""Fix round 4 (exact culprit): the reviewer's tests in this directory are unchanged.

N5 (``test_det_replay_runs_the_checked_out_source_not_stale_bytecode``) was an engine bug (bytecode validated by
source mtime and size under ``--det``). Round 3 marked it as a non-strict expected failure until the engine fix
from ``claude/rust-hotpaths-2`` landed. Round 4 merged that branch, the test passes (XPASS), and the mark is removed.
"""
