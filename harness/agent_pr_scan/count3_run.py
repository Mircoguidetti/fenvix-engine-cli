#!/usr/bin/env python3
"""Count 3: flaky fixes that did not hold (informational).

Sample: merged public pull requests found by the title queries flaky / flakiness / flake / deflake, titles matching
flake8|nix|flake.(nix|lock) excluded, deduplicated, shuffled once with random.Random(1) (pool sorted by URL first),
at most 3 per repository, forks excluded, landed on the default branch, changing at least one test file. Drawn until
200 such pull requests are read (and further, if needed, until 150 have a nameable test).

Test identity: for each changed test file, the test functions that enclose a changed line (scanning the file upward
at that commit for a test definition); a test file added or deleted whole names the file. Nothing nameable ->
"test not nameable" (left out of the denominator).

Did it hold (window: 90 days after the landing commit, commits after it on the default branch, git log --follow):
not held if a later commit (a) mentions flaky/flake/flakiness/deflake and changes the same test, (b) adds a skip
marker inside the same test, or (c) deletes the test and mentions flaky/flake, or deletes it after (b).
Other deletions are reported separately and do not count.

Writes count3_rows.jsonl, count3_excluded.jsonl, and appends to unreadable.jsonl (count = "count3").
"""
from __future__ import annotations

import datetime as dt
import os
import random
import re
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import classify
import gitpr
from common import HERE, Meta, append_jsonl, read_jsonl

WORK = Path(os.environ.get("WORK_DIR", "/tmp/agent_pr_scan_work")) / "count3"
ROWS = HERE / "count3_rows.jsonl"
EXCL = HERE / "count3_excluded.jsonl"
UNREAD = HERE / "unreadable.jsonl"
TERMS = ["flaky", "flakiness", "flake", "deflake"]
TITLE_EXCL = re.compile(r"flake8|nix|flake\.(nix|lock)", re.I)
TITLE_TERM = re.compile(r"flak|deflak", re.I)
FLAKY_MSG = re.compile(r"\b(?:de)?flak(?:y|e|es|iness|ily)\b", re.I)
HOLD_DAYS = 90
TARGET_READ = 200
MIN_NAMEABLE = 150
CAP = 3

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def flaky_msg(msg: str) -> bool:
    return bool(FLAKY_MSG.search(re.sub(r"flake8|flake\.(?:nix|lock)|\bnix\s+flake", " ", msg, flags=re.I)))


def load_pool() -> list[dict]:
    seen, out = {}, []
    for t in TERMS:
        for r in read_jsonl(HERE / "search_rows" / f"count3_{t}.jsonl.gz"):
            if r["url"] in seen:
                seen[r["url"]]["terms"].append(t)
                continue
            if TITLE_EXCL.search(r["title"]) or not TITLE_TERM.search(r["title"]):
                continue
            r = {**r, "terms": [t]}
            seen[r["url"]] = r
            out.append(r)
    out.sort(key=lambda r: r["url"])
    random.Random(1).shuffle(out)
    return out


def changed_lines(patch_text: str) -> dict[str, dict]:
    """path -> {"old": [old-side line numbers removed], "new": [new-side line numbers added], flags}."""
    res, cur, o, n = {}, None, 0, 0
    for line in patch_text.split("\n"):
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            cur = {"old_path": m.group(1) if m else None, "path": m.group(2) if m else None, "old": [],
                   "new": [], "added_lines": [], "removed_lines": [], "new_file": False, "deleted": False}
            res[cur["path"]] = cur
            continue
        if cur is None:
            continue
        if line.startswith("new file mode"):
            cur["new_file"] = True
        elif line.startswith("deleted file mode"):
            cur["deleted"] = True
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            o, n = int(m.group(1)), int(m.group(3))
        elif line.startswith("+") and not line.startswith("+++"):
            cur["new"].append(n)
            cur["added_lines"].append((n, line[1:]))
            n += 1
        elif line.startswith("-") and not line.startswith("---"):
            cur["old"].append(o)
            cur["removed_lines"].append((o, line[1:]))
            o += 1
        elif line.startswith(" "):
            o += 1
            n += 1
    return res


def indent(s: str) -> int:
    return len(s) - len(s.lstrip())


def def_name(lines: list[str], i: int) -> str | None:
    """Test name defined at line i (0-based), following an annotation to the next declaration if needed."""
    n = classify.test_defs(lines[i])
    if n is None:
        return None
    if n.startswith(("@Test", "#[", "[")):
        for j in range(i + 1, min(i + 6, len(lines))):
            m = re.search(r"\b(?:fn|void|fun|func|def|Task|async\s+Task)\s+`?(\w+)`?\s*\(", lines[j]) or \
                re.search(r"\b(\w+)\s*\([^)]*\)\s*(?:throws [\w, .]+)?\s*\{?\s*$", lines[j])
            if m:
                return m.group(1)
        return None
    return n


def enclosing_tests(content: str, line_nos: list[int]) -> set[str]:
    lines = content.split("\n")
    out = set()
    for ln in line_nos:
        i = min(max(ln - 1, 0), len(lines) - 1) if lines else -1
        tgt = indent(lines[i]) if i >= 0 else 0
        j = i
        while j >= 0:
            name = def_name(lines, j)
            if name and (indent(lines[j]) <= tgt or j == i):
                out.add(name)
                break
            j -= 1
    return out


def show(d: Path, sha: str, path: str) -> str:
    return gitpr.git(d, "show", f"{sha}:{path}", timeout=300, check=False)


def tests_touched(d: Path, base: str, landing: str, info: dict) -> set[str]:
    names = set()
    if info["new"]:
        names |= enclosing_tests(show(d, landing, info["path"]), info["new"])
    if info["old"]:
        names |= enclosing_tests(show(d, base, info["old_path"]), info["old"])
    for _, ln in info["added_lines"] + info["removed_lines"]:
        n = classify.test_defs(ln)
        if n and not n.startswith(("@Test", "#[", "[")):
            names.add(n)
    return names


def skip_in_test(d: Path, c: str, info: dict, names: set[str]) -> bool:
    content = None
    for lno, ln in info["added_lines"]:
        hit = [k for k, r in classify.SKIP_RES if r.search(ln) and
               (not k.startswith("rspec.") or info["path"].endswith(".rb"))]
        if not hit:
            continue
        if names == {"<file>"}:
            return True
        if any(nm in ln for nm in names):
            return True
        if content is None:
            content = show(d, c, info["path"])
        if enclosing_tests(content, [lno]) & names or enclosing_tests(content, [lno + 1]) & names:
            return True
    return False


def follow(d: Path, landing: str, branch: str, path: str, until: dt.datetime) -> list[dict]:
    out = gitpr.git(d, "log", "--follow", "-M", "--format=%x01%H%x00%cI%x00%B%x02", "--name-status",
                    f"--until={until.isoformat()}", f"{landing}..refs/remotes/origin/{branch}", "--", path,
                    timeout=300)
    res = []
    for rec in out.split("\x01")[1:]:
        head, _, files = rec.partition("\x02")
        sha, date, msg = head.split("\x00", 2)
        res.append({"sha": sha, "date": date, "msg": msg, "files": files.strip()})
    return list(reversed(res))  # oldest first


def read_one(r: dict) -> dict:
    root = WORK / r["url"].split("github.com/")[1].replace("/", "__")
    try:
        info = gitpr.read_pr(root, r["repo"], r["number"], r["merged_at"], all_branches=False)
        d = info["dir"]
        res = {"ok": True, "info": {k: v for k, v in info.items() if k != "dir"}}
        if not info["landed_on_default"] or info["method"] == "pr_head_merge_base":
            res["not_default"] = True
            return res
        ns = gitpr.name_status(d, info["base"], info["landing"])
        tfiles = [e for e in ns if classify.is_test(e["path"]) or classify.is_test(e["old"])]
        res["n_test_files_changed"] = len(tfiles)
        if not tfiles:
            return res
        text = gitpr.patch(d, info["base"], info["landing"], sorted({e["path"] for e in tfiles} |
                                                                    {e["old"] for e in tfiles}))
        cl = changed_lines(text)
        ident = []
        for e in tfiles:
            ci = cl.get(e["path"])
            if ci is None:
                continue
            if ci["new_file"] or ci["deleted"] or e["status"] in "AD":
                ident.append({"file": e["path"], "tests": ["<file>"], "status": e["status"]})
                continue
            names = tests_touched(d, info["base"], info["landing"], ci)
            if names:
                ident.append({"file": e["path"], "tests": sorted(names), "status": e["status"]})
        res["identity"] = ident
        if not ident:
            return res
        merged = gitpr.parse_ts(r["merged_at"])
        until = merged + dt.timedelta(days=HOLD_DAYS)
        # make sure history up to `until` is present (the fetch already covers the default branch up to now)
        events = []
        for idt in ident:
            if idt["status"] == "D":
                continue  # the fix deleted the file itself; nothing to follow
            names = set(idt["tests"])
            skipped = False
            for c in follow(d, info["landing"], info["default_branch"], idt["file"], until):
                cur_path = idt["file"]
                m = re.findall(r"^[RC]\d*\t(\S+)\t(\S+)$", c["files"], re.M)
                if m:
                    cur_path = m[-1][1]
                deleted_file = bool(re.search(r"^D\t", c["files"], re.M))
                par = gitpr.parent(d, c["sha"])
                if par is None:
                    continue
                cdiff = gitpr.git(d, "diff", "-M", "-U3", "--no-color", par, c["sha"], "--", cur_path,
                                  *([idt["file"]] if cur_path != idt["file"] else []), timeout=300)
                cc = changed_lines(cdiff)
                info_c = next(iter(cc.values()), None)
                fl = flaky_msg(c["msg"])
                if names == {"<file>"}:
                    touched, deleted = info_c is not None, deleted_file
                else:
                    touched_names = tests_touched(d, par, c["sha"], info_c) if info_c else set()
                    touched = bool(touched_names & names)
                    if deleted_file:
                        deleted = True
                    elif info_c:
                        removed = {classify.test_defs(ln) for _, ln in info_c["removed_lines"]}
                        added = {classify.test_defs(ln) for _, ln in info_c["added_lines"]}
                        deleted = bool((names & removed) - added)
                    else:
                        deleted = False
                ev = {"sha": c["sha"], "date": c["date"], "subject": c["msg"].strip().split("\n")[0][:160],
                      "flaky_msg": fl, "file": idt["file"]}
                if info_c and skip_in_test(d, c["sha"], info_c, names):
                    events.append({**ev, "kind": "skipped"})
                    skipped = True
                elif deleted and (fl or skipped):
                    events.append({**ev, "kind": "deleted_flaky_or_after_skip"})
                elif deleted:
                    events.append({**ev, "kind": "deleted_other"})
                elif touched and fl:
                    events.append({**ev, "kind": "changed_again_flaky"})
        res["events"] = events
        return res
    except gitpr.Unreadable as e:
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    pool = load_pool()
    meta = Meta()
    done = {x["url"] for x in read_jsonl(ROWS)} | {x["url"] for x in read_jsonl(EXCL)} | \
        {x["url"] for x in read_jsonl(UNREAD) if x.get("count") == "count3"}
    rows = read_jsonl(ROWS)
    per_repo = Counter(x["repo"].lower() for x in rows) + \
        Counter(x["repo"].lower() for x in read_jsonl(UNREAD) if x.get("count") == "count3")
    n_read = sum(1 for x in rows if x["n_test_files_changed"] > 0)
    n_name = sum(1 for x in rows if x.get("identity"))
    ex = ThreadPoolExecutor(max_workers=4)
    futs = {}

    def static(x: dict) -> str | None:
        if per_repo[x["repo"].lower()] >= CAP:
            return "repository cap (3 per repository) reached"
        m = meta.get(x["repo"])
        if not m["found"]:
            return m["note"]
        if m["fork"]:
            return "fork"
        return None

    for i, r in enumerate(pool):
        if n_read >= TARGET_READ and n_name >= MIN_NAMEABLE:
            break
        window = [x for x in pool[i:i + 40] if x["url"] not in done]
        meta.ensure([x["repo"] for x in window])
        for x in window[:8]:
            if x["url"] not in futs and static(x) is None:
                futs[x["url"]] = ex.submit(read_one, x)
        if r["url"] in done:
            continue
        base = {"url": r["url"], "repo": r["repo"], "number": r["number"], "title": r["title"],
                "merged_at": r["merged_at"], "terms": r["terms"], "month": r["month"]}
        why = static(r)
        if why:
            append_jsonl(EXCL, {**base, "reason": why})
            done.add(r["url"])
            continue
        res = (futs.pop(r["url"], None) or ex.submit(read_one, r)).result()
        done.add(r["url"])
        per_repo[r["repo"].lower()] += 1
        if not res["ok"]:
            append_jsonl(UNREAD, {**base, "count": "count3", "error": res["error"]})
            print("UNREADABLE", r["url"], res["error"], flush=True)
            continue
        if res.get("not_default"):
            append_jsonl(EXCL, {**base, "reason": "did not land on the default branch (or landing commit not "
                                                  "found: rebase merge or custom message)",
                                "method": res["info"]["method"]})
            continue
        if not res.get("n_test_files_changed"):
            append_jsonl(EXCL, {**base, "reason": "no test file changed"})
            continue
        ev = res.get("events", [])
        counting = [e for e in ev if e["kind"] != "deleted_other"]
        row = {**base, **res["info"], "n_test_files_changed": res["n_test_files_changed"],
               "identity": res.get("identity", []), "events": ev,
               "held": (None if not res.get("identity") else not counting)}
        append_jsonl(ROWS, row)
        n_read += 1
        n_name += bool(res.get("identity"))
        print(f"read={n_read} nameable={n_name} {r['url']} held={row['held']} "
              f"{[e['kind'] for e in ev]}", flush=True)
    ex.shutdown(wait=False, cancel_futures=True)
    print("done", n_read, n_name, flush=True)


if __name__ == "__main__":
    main()
