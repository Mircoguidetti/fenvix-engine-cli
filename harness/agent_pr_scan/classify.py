"""Two-tier test-weakening classifier (Count 1). Pure functions over a name-status list and a unified diff.

Fixed before any sample pull request was read (spec rule 3). The skip-marker list below is complete; nothing was
added after looking at the sample.
"""
from __future__ import annotations

import fnmatch
import re

TEST_SEGMENTS = {"test", "tests", "__tests__", "spec", "specs"}
TEST_NAME_GLOBS = ["*_test.*", "*.test.*", "*.spec.*", "test_*.py", "*Test.java", "*_spec.rb"]
DOC_EXT = (".md", ".rst", ".txt", ".adoc")
TEST_CONFIG_GLOBS = ["jest.config.*", "vitest.config.*", "playwright.config.*", "cypress.config.*", "karma.conf.*",
                     ".mocharc*", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "conftest.py",
                     "phpunit.xml*", "jest.setup.*", "vitest.setup.*"]


def is_snapshot(path: str) -> bool:
    return path.endswith(".snap") or "__snapshots__" in path.split("/")[:-1]


def is_test(path: str) -> bool:
    if is_snapshot(path):
        return False
    parts = path.split("/")
    if any(seg in TEST_SEGMENTS for seg in parts[:-1]):
        return True
    name = parts[-1]
    return any(fnmatch.fnmatchcase(name, g) for g in TEST_NAME_GLOBS)


def is_test_config(path: str) -> bool:
    name = path.split("/")[-1]
    return any(fnmatch.fnmatchcase(name, g) for g in TEST_CONFIG_GLOBS)


def is_nontest_code(path: str) -> bool:
    return not is_test(path) and not is_snapshot(path) and not path.lower().endswith(DOC_EXT)


# --- skip markers (added line, per file: added count > removed count) ---------------------------------------
SKIP_MARKERS = [
    ("js.skip", r"\b(?:it|test|describe|context|suite|specify)(?:\.describe)?\.skip\b"),
    ("js.x", r"(?<![\w.])x(?:it|describe|test|context|specify)\s*\("),
    ("js.fixme", r"\btest(?:\.describe)?\.fixme\s*\("),
    ("mocha.this.skip", r"\bthis\.skip\s*\(\s*\)"),
    ("pytest.mark", r"@pytest\.mark\.(?:skip|skipif|xfail)\b"),
    ("pytest.call", r"\bpytest\.(?:skip|xfail)\s*\("),
    ("unittest.decorator", r"@(?:unittest\.)?(?:skip|skipIf|skipUnless|expectedFailure)\b"),
    ("unittest.skipTest", r"\bself\.skipTest\s*\("),
    ("go.t.Skip", r"\b[tb]\.Skip(?:f|Now)?\s*\("),
    ("junit.Disabled", r"@Disabled\b"),
    ("junit.Ignore", r"@Ignore\b"),
    ("rspec.skip_meta", r"\bskip:\s"),
    ("rspec.skip_pending", r"^\s*(?:skip|pending)(?:\s*\(|\s+['\"]|\s*$)"),
    ("rust.ignore", r"#\[ignore\b"),
    ("dotnet.skip", r"\[(?:Fact|Theory)\s*\(\s*Skip\s*=|\[Ignore\b"),
    ("php.skip", r"\bmarkTest(?:Skipped|Incomplete)\s*\("),
    ("swift.skip", r"\bXCTSkip\w*\s*\("),
]
SKIP_RES = [(k, re.compile(p)) for k, p in SKIP_MARKERS]

ASSERT_RE = re.compile(
    r"\bassert\w*\b|\bexpect\s*\(|\.should\b|\bshould\s*[\(.]|\b[tb]\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b|"
    r"\brequire\.\w+\(|\bXCTAssert\w*|\bverify\s*\(|\bself\.fail\s*\(|\bpytest\.raises\s*\(|"
    r"\.to(?:Be|Equal|StrictEqual|Match|Contain|Have|Throw)\w*\s*\(|\bis\.?(?:Equal|True|False|Nil|NotNil)\s*\(|"
    r"\bmust_\w+|\bexpect\b"
)

TEST_DEF_RES = [
    re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\("),
    re.compile(r"""^\s*(?:it|test|specify|scenario)(?:\.\w+)?\s*\(\s*(['"`])(.+?)\1"""),
    re.compile(r"^\s*func\s+(Test\w+)\s*\("),
    re.compile(r"""^\s*it\s+(['"])(.+?)\1"""),
    re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?(?:fun|void|func|function)\s+`?(test\w*)`?\s*\("),
    re.compile(r"^\s*(@Test\b|#\[test\]|#\[tokio::test|\[Fact\]|\[Theory\]|\[Test\]|\[TestMethod\])"),
]

NUM_KEY_RE = re.compile(r"(\w*(?:timeout|retries|retry|reruns|retrytimes)\w*)\W{0,20}?(\d[\d_]*)", re.I)
LIT_RE = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`|\b\d+(?:\.\d+)?\b""")


def test_defs(line: str) -> str | None:
    for r in TEST_DEF_RES:
        m = r.search(line)
        if m:
            return m.group(m.lastindex) if m.lastindex else m.group(0)
    return None


def parse_patch(text: str) -> list[dict]:
    """Split a unified diff into files -> hunks of (removed, added) lines."""
    files, cur, hunk = [], None, None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            cur = {"path": None, "old": None, "deleted": False, "new": False, "hunks": []}
            files.append(cur)
            hunk = None
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            if m:
                cur["old"], cur["path"] = m.group(1), m.group(2)
            continue
        if cur is None:
            continue
        if line.startswith("deleted file mode"):
            cur["deleted"] = True
        elif line.startswith("new file mode"):
            cur["new"] = True
        elif line.startswith("rename to "):
            cur["path"] = line[len("rename to "):]
        elif line.startswith("@@"):
            hunk = {"header": line, "rem": [], "add": []}
            cur["hunks"].append(hunk)
        elif hunk is not None and line.startswith("-") and not line.startswith("---"):
            hunk["rem"].append(line[1:])
        elif hunk is not None and line.startswith("+") and not line.startswith("+++"):
            hunk["add"].append(line[1:])
    return files


def norm_lit(s: str) -> str:
    return re.sub(r"\s+", "", LIT_RE.sub("L", s))


def classify(ns: list[dict], patch_text: str) -> dict:
    paths = [e["path"] for e in ns]
    test_changed = [e for e in ns if is_test(e["path"]) or is_test(e["old"])]
    nontest = any(is_nontest_code(e["path"]) for e in ns)
    snapshots = sum(1 for e in ns if is_snapshot(e["path"]) or is_snapshot(e["old"]))
    signals: list[dict] = []

    # deleted test files (renames are status R and never count)
    for e in ns:
        if e["status"] == "D" and is_test(e["path"]):
            signals.append({"kind": "test_file_deleted", "tier": "STRONG", "file": e["path"]})

    files = parse_patch(patch_text)
    added_names, removed_by_file, added_by_file = set(), {}, {}
    for f in files:
        if f["path"] is None:
            continue
        for h in f["hunks"]:
            for ln in h["add"]:
                n = test_defs(ln)
                if n:
                    added_names.add(n)
                    added_by_file.setdefault(f["path"], []).append(n)
            for ln in h["rem"]:
                n = test_defs(ln)
                if n:
                    removed_by_file.setdefault(f["path"], []).append(n)

    for f in files:
        p = f["path"]
        if p is None:
            continue
        test_file = is_test(p) or is_test(f["old"] or "")
        if test_file and not f["deleted"]:
            rem = removed_by_file.get(p, [])
            add = added_by_file.get(p, [])
            gone = [n for n in rem if n not in added_names]
            if gone and len(rem) > len(add):
                signals.append({"kind": "test_function_deleted", "tier": "STRONG", "file": p,
                                "detail": ", ".join(sorted(set(gone)))[:300]})
            # skip markers
            all_add = [ln for h in f["hunks"] for ln in h["add"]]
            all_rem = [ln for h in f["hunks"] for ln in h["rem"]]
            for k, r in SKIP_RES:
                if k.startswith("rspec.") and not p.endswith(".rb"):
                    continue
                na = sum(1 for ln in all_add if r.search(ln))
                nr = sum(1 for ln in all_rem if r.search(ln))
                if na > nr:
                    ex = next(ln for ln in all_add if r.search(ln))
                    signals.append({"kind": "skip_added", "tier": "STRONG", "file": p, "marker": k,
                                    "detail": ex.strip()[:200]})
            for h in f["hunks"]:
                ra = [ln for ln in h["rem"] if ASSERT_RE.search(ln)]
                aa = [ln for ln in h["add"] if ASSERT_RE.search(ln)]
                if ra and not aa:
                    signals.append({"kind": "assertion_removed", "tier": "STRONG", "file": p,
                                    "detail": ra[0].strip()[:200]})
                # WEAK: expected literal changed in an assertion
                if ra and aa:
                    na = {norm_lit(x): x for x in aa}
                    for x in ra:
                        y = na.get(norm_lit(x))
                        if y is not None and re.sub(r"\s+", "", x) != re.sub(r"\s+", "", y):
                            signals.append({"kind": "assert_literal_changed", "tier": "WEAK", "file": p,
                                            "detail": f"{x.strip()[:120]} -> {y.strip()[:120]}"})
                            break
        if test_file or is_test_config(p):
            for h in f["hunks"]:
                before = {}
                for ln in h["rem"]:
                    for m in NUM_KEY_RE.finditer(ln):
                        before.setdefault(m.group(1).lower(), []).append(int(m.group(2).replace("_", "")))
                for ln in h["add"]:
                    for m in NUM_KEY_RE.finditer(ln):
                        k, v = m.group(1).lower(), int(m.group(2).replace("_", ""))
                        if k in before and v > max(before[k]):
                            signals.append({"kind": "timeout_or_retry_raised", "tier": "WEAK", "file": p,
                                            "detail": f"{k}: {max(before[k])} -> {v}"})
                            break

    strong = [s for s in signals if s["tier"] == "STRONG"]
    weak = [s for s in signals if s["tier"] == "WEAK"]
    if strong and nontest:
        tier = "STRONG"
    elif weak:
        tier = "WEAK"
    else:
        tier = "NONE"
    return {"tier": tier, "signals": signals, "strong_signals_test_only_pr": bool(strong and not nontest),
            "n_files": len(paths), "n_test_files_changed": len(test_changed), "nontest_code_changed": nontest,
            "snapshot_files_changed": snapshots}
