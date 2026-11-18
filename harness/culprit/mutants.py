#!/usr/bin/env python3
"""Planted code regressions in a replayed history (cases of kind a).

For one library and a list of distances k, each case is:

* green commit g = the first-parent commit k commits before HEAD's position;
* a planted commit M = g + one mutated source line (a realistic one-token regression);
* every later first-parent commit replayed on top of M with the same mutation applied (new commits, same trees
  otherwise, same messages and dates), ending at HEAD';
* a red test: one test that passes at g and fails at M and at HEAD' (plain pytest and ``--det`` agree).

So (g, HEAD'] holds exactly k commits and the true culprit is M. The cases are written as JSON lines.

    mutants.py --repo DIR --venv DIR --name NAME --ks 5,10,... --out cases.jsonl [--seed S]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import checkout, git, git_out, run_det, run_plain  # noqa: E402

OPS = [
    (r" == ", " != "), (r" != ", " == "), (r" < ", " <= "), (r" > ", " >= "), (r" <= ", " < "),
    (r" >= ", " > "), (r" and ", " or "), (r" or ", " and "), (r"return True\b", "return False"),
    (r"return False\b", "return True"), (r" \+ 1\b", " + 2"), (r" - 1\b", " - 2"), (r"\bif not ", "if "),
    (r" is None\b", " is not None"), (r" is not None\b", " is None"), (r"\[0\]", "[1]"), (r"\[-1\]", "[0]"),
]


def source_files(repo: Path) -> list[str]:
    out = git(repo, "ls-files", "*.py").split()
    keep = []
    for f in out:
        parts = f.split("/")
        if any(p in ("tests", "test", "testing", "docs", "doc", "benchmarks", "bench", "examples", "scripts",
                     "tasks", "conftest.py", "setup.py", "noxfile.py") for p in parts):
            continue
        if parts[-1].startswith("test_") or parts[-1].endswith("_test.py"):
            continue
        keep.append(f)
    return keep


def func_body_lines(tree) -> set[int]:
    lines = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = n.body
            start = body[0].lineno
            if isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                if len(body) == 1:
                    continue
                start = body[1].lineno
            lines.update(range(start, (n.end_lineno or start) + 1))
    return lines


def sites(text: str):
    """(line index, original line, mutated line, operator) for every mutable code line inside a function body."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    body = func_body_lines(tree)
    ref = ast.dump(tree)
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        if i + 1 not in body or line.strip().startswith("#"):
            continue
        code = line.split("#", 1)[0]
        for pat, rep in OPS:
            m = re.search(pat, code)
            if not m:
                continue
            new = line[: m.start()] + re.sub(pat, rep, line[m.start(): m.end()]) + line[m.end():]
            new_text = "\n".join(lines[:i] + [new] + lines[i + 1:])
            try:
                if ast.dump(ast.parse(new_text)) == ref:
                    continue  # inside a string
            except SyntaxError:
                continue
            out.append((i, line, new, pat))
    return out


def failed_ids(out: str) -> set[str]:
    ids = set()
    for line in out.splitlines():
        if line.startswith(("FAILED ", "ERROR ")):
            tid = line.split(" ", 1)[1].split(" - ", 1)[0].strip()
            ids.add(tid)
    return ids


def apply_line(text: str, old: str, new: str) -> str | None:
    lines = text.split("\n")
    idx = [i for i, l in enumerate(lines) if l == old]
    if len(idx) != 1:
        return None
    lines[idx[0]] = new
    return "\n".join(lines)


def show(repo, sha, path) -> str | None:
    p = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{path}"], capture_output=True)
    if p.returncode != 0:
        return None
    try:
        return p.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def persists(repo, later: list[str], path: str, old: str) -> bool:
    """The original line exists exactly once in every later version of the file (so the mutation replays)."""
    if not later:
        return True
    touched = git(repo, "log", "--format=%H", "--first-parent", f"{later[0]}^..{later[-1]}", "--", path).split()
    for sha in touched:
        t = show(repo, sha, path)
        if t is None or apply_line(t, old, old + "\0") is None:
            return False
    return True


def tree_with(repo, sha, path, old, new) -> str:
    t = show(repo, sha, path)
    mt = apply_line(t, old, new)
    assert mt is not None, (sha, path)
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=mt.encode(),
                          capture_output=True, check=True).stdout.decode().strip()
    mode = git(repo, "ls-tree", sha, "--", path).split()[0]
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(td, "index")}
        subprocess.run(["git", "-C", str(repo), "read-tree", sha], env=env, check=True)
        subprocess.run(["git", "-C", str(repo), "update-index", "--cacheinfo", f"{mode},{blob},{path}"], env=env,
                       check=True)
        return subprocess.run(["git", "-C", str(repo), "write-tree"], env=env, capture_output=True, check=True,
                              text=True).stdout.strip()


def commit(repo, tree, parent, msg, like: str | None) -> str:
    env = dict(os.environ)
    if like:
        fmt = git_out(repo, "log", "-1", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI", like).strip().split("\0")
        env.update(GIT_AUTHOR_NAME=fmt[0], GIT_AUTHOR_EMAIL=fmt[1], GIT_AUTHOR_DATE=fmt[2], GIT_COMMITTER_NAME=fmt[3],
                   GIT_COMMITTER_EMAIL=fmt[4], GIT_COMMITTER_DATE=fmt[5])
    else:
        env.update(GIT_AUTHOR_NAME="planted", GIT_AUTHOR_EMAIL="planted@example.invalid",
                   GIT_COMMITTER_NAME="planted", GIT_COMMITTER_EMAIL="planted@example.invalid")
    return subprocess.run(["git", "-C", str(repo), "commit-tree", tree, "-p", parent, "-m", msg], env=env,
                          capture_output=True, text=True, check=True).stdout.strip()


def build_chain(repo, g, later, path, old, new, case_id) -> tuple[str, str]:
    m = commit(repo, tree_with(repo, g, path, old, new), g, f"planted regression {case_id} in {path}", None)
    prev = m
    for sha in later:
        msg = git_out(repo, "log", "-1", "--format=%B", sha)
        prev = commit(repo, tree_with(repo, sha, path, old, new), prev, msg, sha)
    git(repo, "update-ref", f"refs/culprit/{case_id}", prev)
    return m, prev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--ks", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default="exact-culprit")
    ap.add_argument("--head", default=None)
    ap.add_argument("--tries", type=int, default=12)
    a = ap.parse_args()
    repo, venv = Path(a.repo).resolve(), Path(a.venv).resolve()
    head = a.head or git(repo, "rev-parse", "HEAD")
    fp = git(repo, "rev-list", "--first-parent", "--reverse", "--max-count=400", head).split()
    rng = random.Random(f"{a.seed}:{a.name}")
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            done.add(json.loads(line)["k_target"])
    plain = ["-q", "--tb=no", "-rfE", "-p", "no:randomly"]
    for n, k in enumerate(int(x) for x in a.ks.split(",")):
        if k in done:
            continue
        case = None
        for shift in range(0, 6):
            kk = k + shift
            gi = len(fp) - kk
            g, later = fp[gi], fp[gi + 1:]
            checkout(repo, g)
            code, out, _ = run_plain(repo, venv, plain, timeout=1200)
            base_failed = failed_ids(out)
            if code not in (0, 1):
                print(f"{a.name} k={kk}: suite unusable at {g[:10]} (exit {code})", flush=True)
                continue
            files = source_files(repo)
            all_sites = []
            for f in files:
                t = (repo / f).read_text(errors="replace")
                for s in sites(t):
                    all_sites.append((f, *s))
            rng.shuffle(all_sites)
            tried = 0
            for f, i, old, new, pat in all_sites:
                if tried >= a.tries:
                    break
                if not persists(repo, later, f, old):
                    continue
                tried += 1
                p = repo / f
                orig = p.read_text()
                mt = apply_line(orig, old, new)
                if mt is None:
                    continue
                p.write_text(mt)
                code2, out2, _ = run_plain(repo, venv, plain, timeout=1200)
                p.write_text(orig)
                killed = sorted(failed_ids(out2) - base_failed)
                killed = [t for t in killed if "::" in t]
                if not killed:
                    continue
                red = rng.choice(killed)
                cid = f"{a.name}-k{kk}-{n}"
                m, head2 = build_chain(repo, g, later, f, old, new, cid)
                # checks: plain and --det agree (green passes at g, red fails at M and at HEAD')
                ok = True
                why = []
                for sha, want in ((g, "pass"), (m, "fail"), (head2, "fail")):
                    checkout(repo, sha)
                    c3, _o3, _ = run_plain(repo, venv, ["-q", "--tb=no", "-p", "no:randomly", red])
                    got = "pass" if c3 == 0 else "fail"
                    d = run_det(repo, venv, red)["outcome"]
                    if got != want or d != want:
                        ok = False
                        why.append(f"{sha[:8]} plain={got} det={d} want={want}")
                        break
                if not ok:
                    print(f"{a.name} k={kk}: rejected {f}:{i + 1} {red}: {why}", flush=True)
                    git(repo, "update-ref", "-d", f"refs/culprit/{cid}")
                    continue
                case = {"id": cid, "repo": a.name, "k_target": k, "k": len(later) + 1, "green": g, "planted": m,
                        "red_head": head2, "head": head, "file": f, "line": i + 1, "old": old, "new": new,
                        "op": pat, "red_test": red, "killed": len(killed)}
                break
            if case:
                break
        if case is None:
            print(f"{a.name} k={k}: no case", flush=True)
            continue
        with open(a.out, "a") as fh:
            fh.write(json.dumps(case) + "\n")
        print(f"{a.name} k={case['k']}: {case['file']}:{case['line']} {case['red_test']} (killed {case['killed']})",
              flush=True)
    checkout(repo, head)


if __name__ == "__main__":
    main()
