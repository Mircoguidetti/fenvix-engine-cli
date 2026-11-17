"""T2 (django-oauth-toolkit): the virtual wall clock starts at the HEAD commit time.

A test written at a commit may assume that dates before that commit are in the
past (token expiries, certificates, "not before" checks). With a fixed epoch
older than the commit (2025-01-01), such a test failed only under --det. The
commit time is deterministic for a given checkout and never later than the real
time of any run.
"""
import os
import subprocess


def _git(path, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True)


TEST = """
import datetime, time
def test_now_is_the_commit_time():
    now = datetime.datetime.now(datetime.timezone.utc)
    assert (now.year, now.month, now.day) == (2030, 6, 1), now
    assert time.gmtime(time.time())[:3] == (2030, 6, 1)
"""


def test_epoch_defaults_to_the_head_commit_time(pytester, run_det):
    pytester.makepyfile(test_e=TEST)
    _git(pytester.path, "init", "-q")
    _git(pytester.path, "add", "-A")
    _git(pytester.path, "commit", "-q", "-m", "c", date="2030-06-01T12:00:00+00:00")
    result, _ = run_det("-p", "no:randomly")
    result.assert_outcomes(passed=1)


def test_explicit_epoch_and_no_git_keep_the_fixed_default(pytester, run_det):
    pytester.makepyfile(test_e="""
        import datetime
        def test_default():
            assert datetime.datetime.now(datetime.timezone.utc).year == 2025
        """)
    result, _ = run_det("-p", "no:randomly")
    result.assert_outcomes(passed=1)
    pytester.makepyfile(test_e=TEST)
    result, _ = run_det("-p", "no:randomly", "--det-epoch=2030-06-01T08:00:00+00:00")
    result.assert_outcomes(passed=1)
