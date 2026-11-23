"""Read a merged pull request from a public repository with git only (no GitHub API).

The REST and GraphQL APIs are refused for third-party repositories in this session (see REPORT.md), so a pull
request is reconstructed from a blobless partial clone:

  1. fetch all branches (blobless, shallow since merged_at - SHALLOW_DAYS) plus refs/pull/<n>/head;
  2. find the commit that landed the pull request: committer date within MERGE_WINDOW seconds of merged_at, and
     either "Merge pull request #<n> " in the message (merge commit) or a subject ending in "(#<n>)" (squash);
  3. if none is found (rebase merges, custom messages), fall back to merge-base(refs/pull/<n>/head, branch)..head
     where branch is the default branch;
  4. "base" is the first parent of the landing commit (or the merge-base in the fallback); the diff is base..landing.

Nothing is checked out and nothing from the repository is executed.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
from pathlib import Path

SHALLOW_DAYS = 120
MERGE_WINDOW = 180
FETCH_TIMEOUT = 300


class Unreadable(Exception):
    pass


def git(d: Path, *args: str, timeout: int = 120, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        raise Unreadable(f"timeout after {timeout}s: git {' '.join(args[:3])}")
    if check and r.returncode != 0:
        line = (r.stderr.strip().splitlines() or ["(no stderr)"])[-1]
        raise Unreadable(f"git {' '.join(args[:2])} exit {r.returncode}: {line}")
    return r.stdout


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def ensure_repo(root: Path, repo: str) -> Path:
    d = root / repo.replace("/", "__")
    if not (d / "HEAD").exists():
        d.mkdir(parents=True, exist_ok=True)
        git(d, "init", "-q", "--bare")
        git(d, "remote", "add", "origin", f"https://github.com/{repo}.git")
        git(d, "config", "remote.origin.promisor", "true")
        git(d, "config", "remote.origin.partialclonefilter", "blob:none")
    return d


def default_branch(d: Path) -> str:
    out = git(d, "ls-remote", "--symref", "origin", "HEAD", timeout=60)
    m = re.search(r"ref: refs/heads/(\S+)\s+HEAD", out)
    if not m:
        raise Unreadable(f"ls-remote: no default branch ({out.strip()[:120]!r})")
    return m.group(1)


def fetch(d: Path, number: int, since: dt.datetime, all_branches: bool, branch: str) -> None:
    refs = ["+refs/heads/*:refs/remotes/origin/*"] if all_branches else \
        [f"+refs/heads/{branch}:refs/remotes/origin/{branch}"]
    refs.append(f"+refs/pull/{number}/head:refs/pr/{number}")
    git(d, "fetch", "-q", "--no-tags", "--filter=blob:none", f"--shallow-since={since.date().isoformat()}",
        "origin", *refs, timeout=FETCH_TIMEOUT)


def find_landing(d: Path, number: int, merged_at: dt.datetime, refs: list[str]) -> tuple[str, str] | None:
    lo = int(merged_at.timestamp()) - MERGE_WINDOW
    hi = int(merged_at.timestamp()) + MERGE_WINDOW
    out = git(d, "log", *refs, f"--since={lo}", f"--until={hi}", "--format=%H%x00%ct%x00%B%x01", timeout=120)
    merge_re = re.compile(rf"Merge pull request #{number}\b")
    squash_re = re.compile(rf"\(#{number}\)\s*$")
    for rec in out.split("\x01"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, ct, body = rec.split("\x00", 2)
        if not lo <= int(ct) <= hi:
            continue
        subject = body.strip().splitlines()[0] if body.strip() else ""
        if merge_re.search(body):
            return sha, "merge_commit"
        if squash_re.search(subject):
            return sha, "squash"
    return None


def parent(d: Path, sha: str) -> str | None:
    out = git(d, "rev-list", "--parents", "-n", "1", sha).split()
    return out[1] if len(out) > 1 else None


def read_pr(root: Path, repo: str, number: int, merged_at_s: str, all_branches: bool = True) -> dict:
    """Return landing/base commits for the pull request. Raises Unreadable."""
    merged_at = parse_ts(merged_at_s)
    d = ensure_repo(root, repo)
    branch = default_branch(d)
    since = merged_at - dt.timedelta(days=SHALLOW_DAYS)
    try:
        fetch(d, number, since, all_branches, branch)
    except Unreadable as e:
        if "couldn't find remote ref" in str(e) and f"pull/{number}" in str(e):
            raise
        if all_branches:  # retry with the default branch only
            fetch(d, number, since, False, branch)
        else:
            raise
    refs = [r for r in git(d, "for-each-ref", "--format=%(refname)", "refs/remotes/origin").split() if r]
    found = find_landing(d, number, merged_at, refs or [f"refs/remotes/origin/{branch}"])
    head = git(d, "rev-parse", f"refs/pr/{number}").strip()
    if found:
        landing, method = found
        base = parent(d, landing)
        if base is None:
            git(d, "fetch", "-q", "--no-tags", "--filter=blob:none", "--deepen=50", "origin",
                f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=FETCH_TIMEOUT)
            base = parent(d, landing)
        if base is None:
            raise Unreadable("landing commit has no parent within the shallow window")
    else:
        method = "pr_head_merge_base"
        landing = head
        mb = git(d, "merge-base", head, f"refs/remotes/origin/{branch}", check=False).strip()
        if not mb:
            raise Unreadable("no landing commit found and no merge-base between pull head and default branch")
        if mb == head:
            raise Unreadable("no landing commit found; pull head is already on the default branch "
                             "(merge-base equals head, diff would be empty)")
        base = mb
    on_default = subprocess.run(
        ["git", "-C", str(d), "merge-base", "--is-ancestor", landing, f"refs/remotes/origin/{branch}"],
        capture_output=True).returncode == 0
    return {"dir": d, "default_branch": branch, "method": method, "landing": landing, "base": base,
            "pr_head": head, "landed_on_default": on_default}


def name_status(d: Path, a: str, b: str) -> list[dict]:
    out = git(d, "diff", "-M", "--name-status", "-z", a, b, timeout=300)
    parts = out.split("\x00")
    res, i = [], 0
    while i < len(parts) and parts[i]:
        st = parts[i]
        if st[0] in "RC":
            res.append({"status": st[0], "score": st[1:], "old": parts[i + 1], "path": parts[i + 2]})
            i += 3
        else:
            res.append({"status": st[0], "old": parts[i + 1], "path": parts[i + 1]})
            i += 2
    return res


def patch(d: Path, a: str, b: str, paths: list[str]) -> str:
    if not paths:
        return ""
    return git(d, "diff", "-M", "-U3", "--no-color", a, b, "--", *paths, timeout=600)


def tree_paths(d: Path, sha: str) -> list[str]:
    return [p for p in git(d, "ls-tree", "-r", "--name-only", sha, timeout=300).split("\n") if p]


def cleanup(d: Path) -> None:
    shutil.rmtree(d, ignore_errors=True)
