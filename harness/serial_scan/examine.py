#!/usr/bin/env python3
"""Step 2: examine every repository found by search.py, by reading files through gh api.

For each repository (one line per repository in raw/examined.jsonl):
  * pin the default-branch HEAD commit, stars, language;
  * re-read the hit file at that commit and look for a serial flag with a regex
    (search hits are only candidates; a hit without a verified flag is examined
    but not serial);
  * collect the evidence that may say why: comments / step names within +-WINDOW
    lines in the same file, README lines that mention the flag, and the message of
    the commit that last touched the flag line (GraphQL blame);
  * auto-classify reason_kind (stated candidates are then confirmed by hand in
    review_decisions.json; see finalize.py);
  * decide multi_core_runner from .github/workflows (method recorded per repo).

Reading method: the per-repository GitHub REST API is not reachable from this session for
repositories outside its scope, so each repository is read through a bare, blobless,
depth-limited partial fetch (git clone --bare --filter=blob:none --depth=DEPTH): commits and
trees only, and only the blobs of the files read here are downloaded on demand. Nothing is
checked out, nothing is executed, and the fetch is deleted right after. Commit authors are
never recorded. Usage: python3 harness/serial_scan/examine.py [max_repos]
"""
import json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
WINDOW = 5
DEPTH = 150
PER_QUERY = int(os.environ.get("SERIAL_SCAN_PER_QUERY", "25"))
DL = os.environ.get("SERIAL_SCAN_DL", "/tmp/serial_scan_dl")

# ---------------------------------------------------------------- flag regexes
# value that is 1, '1', or a conditional whose branch is 1 (e.g. process.env.CI ? 1 : undefined)
ONE_VALUE = r"""(?:['"]?1['"]?|[^,\n]*\?\s*['"]?1['"]?\s*:[^,\n]*|[^,\n]*\?[^:,\n]+:\s*['"]?1['"]?)\s*(?:[,};)]|$)"""
FLAGS = {
    "jest": [
        ("--runInBand", re.compile(r"--runInBand\b|--run-in-band\b")),
        ("jest -i", re.compile(r"\bjest\b[^\n\"']*?\s-i(?=[\s\"']|$)")),
        ("--maxWorkers=1", re.compile(r"--max[Ww]orkers[= ]1(?![\d%.])|--max-workers[= ]1(?![\d%.])|\bjest\b[^\n\"']*\s-w[= ]?1(?![\d%.])")),
        ("maxWorkers: 1", re.compile(r"\bmaxWorkers['\"]?\s*:\s*" + ONE_VALUE)),
    ],
    "vitest": [
        ("--no-threads", re.compile(r"--no-threads\b|--threads[= ]false\b")),
        ("singleThread: true", re.compile(r"\bsingleThread\s*:\s*true\b|--poolOptions\.threads\.singleThread")),
        ("singleFork: true", re.compile(r"\bsingleFork\s*:\s*true\b|--poolOptions\.forks\.singleFork")),
        ("fileParallelism: false", re.compile(r"\bfileParallelism\s*:\s*false\b|--no-file-parallelism\b|--fileParallelism[= ]false")),
        ("maxWorkers: 1", re.compile(r"\b(?:maxWorkers|maxThreads|maxForks)\s*:\s*1(?![\d%.\w])")),
        ("threads: false", re.compile(r"^\s*threads\s*:\s*false\b")),
    ],
    "node:test": [("--test-concurrency=1", re.compile(r"--test-concurrency[= ]1(?!\d)"))],
    "pytest": [
        ("-p no:xdist", re.compile(r"-p\s*no:xdist\b")),
        ("-n 0", re.compile(r"(?:pytest|addopts|py\.test)[^\n]*\s(?:-n\s*=?\s*0|--numprocesses[= ]0)(?![\d.])")),
    ],
    "go": [
        ("go test -p 1", re.compile(r"\bgo\s+test\b[^\n]*\s-p[= ]1(?![\d.])")),
        ("-parallel 1", re.compile(r"\bgo\s+test\b[^\n]*\s-(?:test\.)?parallel[= ]1(?![\d.])|-test\.parallel[= ]1(?![\d.])")),
        ("GOFLAGS -p=1", re.compile(r"GOFLAGS[^\n]*-p=1(?![\d.])")),
    ],
    "cargo": [("--test-threads=1", re.compile(r"--test-threads[= ]1(?!\d)|RUST_TEST_THREADS\s*[:=]\s*['\"]?1(?!\d)"))],
    "ava": [
        ("ava --serial", re.compile(r"\bava\b[^\n\"']*\s(?:--serial|-s)(?=[\s\"']|$)")),
        ("ava serial: true", re.compile(r"\bserial\s*:\s*true\b")),
        ("ava concurrency 1", re.compile(r"\bava\b[^\n\"']*--concurrency[= ]1(?!\d)")),
    ],
    "tap": [("tap --jobs=1", re.compile(r"\btap\b[^\n\"']*\s(?:--jobs[= ]1|-j\s?1)(?!\d)"))],
    "mocha": [("mocha --jobs 1", re.compile(r"\bmocha\b[^\n\"']*\s(?:--jobs[= ]1|-j\s?1)(?!\d)"))],
    "playwright": [
        ("workers: 1", re.compile(r"\bworkers\s*:\s*" + ONE_VALUE)),
        ("--workers=1", re.compile(r"--workers[= ]1(?![\d%])")),
    ],
}
# Line that `npm init playwright` writes; tagged so scaffold defaults can be counted apart.
PLAYWRIGHT_SCAFFOLD = re.compile(r"workers:\s*process\.env\.CI\s*\?\s*1\s*:\s*undefined")
TEMPLATE_PATH = re.compile(r"(\.ejs|\.hbs|\.tmpl|\.tpl|\.mustache|\.jinja2?|\.j2)$|(^|/)(templates?|generators?|scaffold|boilerplates?|starter|examples?|fixtures?)/|\{\{\s*cookiecutter", re.I)

# ---------------------------------------------------------------- reason words
WHY_BREAK = re.compile(r"flak|\brace\b|races\b|racy|shared|share\b|sharing|databas|\bdbs?\b|postgres|mysql|sqlite|redis|mongo|\bports?\b|isolat|\border\b|ordering|interfer|conflict|deadlock|\block|locking|\bstate\b|stateful|global|collid|collision|clash|same time|simultaneous|at once|singleton|\bbreak|\bbroke|\bfail|\bhang|time ?outs?\b|timing out|pollut|leak|clean ?up|mutat|side.?effect|contention|docker|container|emulator|file ?system|env(ironment)? var|idempot|thread.?safe|not safe|unsafe|nondetermin|non-determin|intermittent|randomly|crash|conflict|overlap|step on|clobber|corrupt|depend on each other|interdepend", re.I)
WHY_RESOURCE = re.compile(r"memory|\boom\b|heap|\bcpus?\b|\bcores?\b|resources?\b|too slow|slower|faster|speed|perf|rate.?limit|quota|out of memory|machine", re.I)
# implied: a real comment (not a step name) about CI / flaky tests / serial execution that names no reason
CONTEXTY = re.compile(r"\bci\b|github action|flak|parallel|serial|sequential|in.?band|worker|concurren|one at a time|one by one|xdist|single.?(fork|thread)", re.I)
# reason connectors: only applied to same-file comments and doc lines (already restricted to the
# comment block above the flag / serial-ish comments / lines naming the flag), never to commit messages
WHY_CONNECT = re.compile(r"\bcause|because|\bsince\b|so that|otherwise|avoid|prevent|due to|\bneeds?\b|requires?|\bmust\b|can'?t|cannot|unreliab|\bstab(le|ility)|\bsafe|429|throttl|per second|overrun|run together|rate", re.I)
COMMENT = re.compile(r"(?:^|\s)(?:#|//|/\*|\*|<!--)\s?(?P<c>.*\S)")
YAML_NAME = re.compile(r"^\s*-?\s*name\s*:\s*(?P<c>.*\S)")

TEST_FILE = re.compile(r"(^|/)(__tests__/.*\.[cm]?[jt]sx?|tests?/[^/]*\.[cm]?[jt]s|test_[^/]*\.py|[^/]*_test\.py|[^/]*_test\.go|[^/]*\.(test|spec)\.[cm]?[jt]sx?|tests/[^/]*\.rs)$")
HOSTED = re.compile(r"\b(ubuntu|windows|macos)-(latest|\d[\w.-]*)\b")
DEFAULT_CONFIG = re.compile(r"^((jest|vitest|vite|playwright|ava)\.config\.(js|ts|mjs|mts|cjs|cts)|pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|conftest\.py|\.taprc|\.mocharc\.\w+)$")
TEST_CMD = re.compile(r"\b(npm (run )?test|npm t\b|yarn( run)? test|pnpm( run)? test|bun (run )?test|jest|vitest|pytest|tox|nox|go test|cargo test|cargo nextest|playwright test|make test|make check|ava\b|tap\b|mocha|node --test)", re.I)


COMMENTED = re.compile(r"^\s*(#|//|/\*|\*|<!--|;|rem\s)", re.I)
SERIALISH = re.compile(r"run.?in.?band|serial|sequential|parallel|worker|concurren|one (at a time|by one)|single.?(thread|fork)|threads?\b|xdist|in band|-p ?1\b|-j ?1\b|jobs|isolat|fork", re.I)
DOC_PATH = re.compile(r"\.(md|mdx|rst|txt|adoc|html?|ipynb)$", re.I)
DEBUG_LINE = re.compile(r"--inspect|--watch\b|\bwatch\b|debug", re.I)
INACTIVE_PATH = re.compile(r"(\.tmp|\.bak|\.orig|\.old|\.sample|\.example|\.dist|\.deactivated|\.disabled|\.off|\.unused|\.main|\.backup|\.copy|\.bkp|-bak|_bak|-old|-copy|~)$|(^|/)#[^/]*#$|(^|/)\.github/workflows-disabled/|\.github/workflows/.*\.(?!ya?ml$)[^/.]+$", re.I)


def find_flags(text, prefer):
    """All flag matches; returns the best one (a non-debug/watch line first) plus whether
    every match is a debug/watch-only line."""
    order = [prefer] + [r for r in FLAGS if r != prefer]
    lines = text.splitlines()
    low = text.lower()
    matches = []
    for runner in order:
        for name, rx in FLAGS[runner]:
            for i, ln in enumerate(lines):
                if len(ln) > 2000 or COMMENTED.match(ln):
                    continue
                if rx.search(ln):
                    if runner == "playwright" and name == "workers: 1" and "playwright" not in low:
                        continue
                    if runner == "ava" and name == "ava serial: true" and "ava" not in low:
                        continue
                    if runner == "jest" and name == "maxWorkers: 1" and "vitest" in low:
                        continue
                    matches.append((runner, name, i + 1, ln))
    if not matches:
        return None
    real = [m for m in matches if not DEBUG_LINE.search(m[3])]
    if real:
        return real[0], False
    return matches[0], True


def comment_text(ln):
    m = COMMENT.search(ln)
    if m and "://" not in m.group(0)[:12]:
        return m.group("c")
    return None


def comments_near(lines, lineno, is_yaml):
    """Evidence lines in the same file: (a) the flag line's own trailing comment, (b) the
    contiguous comment block directly above the flag line (and, in YAML, the name: of the
    step that holds it), (c) any comment within +-WINDOW lines that itself talks about
    serial/parallel execution."""
    out = {}
    if comment_text(lines[lineno - 1]):
        out[lineno] = lines[lineno - 1]
    n = lineno - 1
    while n >= 1 and n >= lineno - 12:
        ln = lines[n - 1]
        if COMMENTED.match(ln):
            out[n] = ln
            n -= 1
            continue
        if not ln.strip():
            n -= 1
            continue
        break
    if is_yaml:
        for n in range(lineno, max(0, lineno - WINDOW - 3), -1):
            if YAML_NAME.search(lines[n - 1]):
                out[n] = lines[n - 1]
                break
    for n in range(max(1, lineno - WINDOW), min(len(lines), lineno + WINDOW) + 1):
        c = comment_text(lines[n - 1])
        if c and SERIALISH.search(c):
            out[n] = lines[n - 1]
    return sorted(out.items())


def flag_token(name):
    return {"--runInBand": "runInBand", "jest -i": "runInBand", "--maxWorkers=1": "maxWorkers",
            "maxWorkers: 1": "maxWorkers", "-p no:xdist": "no:xdist", "-n 0": "-n 0",
            "go test -p 1": "-p 1", "-parallel 1": "-parallel", "--test-threads=1": "test-threads",
            "workers: 1": "workers", "--workers=1": "workers"}.get(name, name.split()[-1].split(":")[0].lstrip("-"))


def script_key(line):
    m = re.match(r'\s*"([^"]+)"\s*:', line)
    return m.group(1) if m else None


def make_target(lines, lineno):
    for n in range(lineno - 1, 0, -1):
        m = re.match(r"^([A-Za-z0-9_.\-/]+)\s*:(?!=)", lines[n - 1])
        if m:
            return m.group(1)
    return None


def decide_multi_core(repo, sha, tree_paths, flag_path, flag_line, flag_lines_all, workflows_text):
    """Return (bool, method). True only if a GitHub-hosted (>1 core) job runs the serial path."""
    if not workflows_text:
        return False, "no .github/workflows file: runner unknown, counted false"
    hosted = {}
    for p, t in workflows_text.items():
        ro = re.findall(r"runs-on\s*:\s*(.+)", t)
        h = any(HOSTED.search(x) for x in ro)
        if not h and any("${{" in x for x in ro) and HOSTED.search(t):
            h = True  # matrix of hosted labels
        hosted[p] = h
    base = os.path.basename(flag_path)
    if flag_path.startswith(".github/workflows/"):
        if hosted.get(flag_path):
            return True, f"flag is in workflow {flag_path} whose runs-on is a GitHub-hosted label (>=2 cores for public repos, GitHub docs)"
        return False, f"flag is in workflow {flag_path} but its runs-on is not a recognised GitHub-hosted label"
    pats = []
    how = ""
    if base == "package.json":
        key = script_key(flag_line)
        if not key:
            return False, "flag line in package.json is not a script entry"
        keys = {key}
        # one level of indirection: scripts that call this script
        try:
            scripts = json.loads("\n".join(flag_lines_all)).get("scripts", {})
        except Exception:
            scripts = {}
        for k, v in scripts.items():
            if isinstance(v, str) and re.search(r"(run|yarn|pnpm|bun)\s+" + re.escape(key) + r"(\s|$|&|;)", v):
                keys.add(k)
        for k in keys:
            e = re.escape(k)
            pats.append(r"(npm|pnpm|yarn|bun)( run| run-script)?\s+" + e + r"(\s|$|\")")
            if k == "test":
                pats.append(r"\bnpm t(\s|$)|\b(npm|pnpm|yarn|bun) test\b")
        how = f"workflow runs package.json script(s) {sorted(keys)}"
    elif base.lower() in ("makefile", "gnumakefile") or base.endswith(".mk"):
        tgt = make_target(flag_lines_all, flag_lines_all.index(flag_line) + 1 if flag_line in flag_lines_all else 1)
        if tgt:
            pats.append(r"\bmake\b[^\n]*\b" + re.escape(tgt) + r"\b")
        how = f"workflow runs make target {tgt}"
    elif re.search(r"(jest|vitest|vite|playwright|ava)\.config\.|\.taprc|\.mocharc|pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|conftest\.py|config\.toml$|\.cargo", base + flag_path):
        if DEFAULT_CONFIG.match(base):
            if base.startswith("playwright."):
                pats.append(r"playwright\s+test|test:e2e|\be2e\b")
                how = f"default config {base} applies to every Playwright run; workflow runs Playwright"
            else:
                pats.append(TEST_CMD.pattern)
                how = f"default config {base} applies to every run; workflow runs a test command"
        else:
            pats.append(re.escape(base))
            how = f"non-default config {base} only applies when named; workflow references it"
    else:
        pats.append(re.escape(base))
        how = f"workflow references {base}"
    for p, t in workflows_text.items():
        if not hosted.get(p):
            continue
        for pat in pats:
            if re.search(pat, t, re.I):
                return True, how + f" ({p}, GitHub-hosted runs-on)"
    if not any(hosted.values()):
        return False, "no workflow with a GitHub-hosted runs-on label"
    return False, "hosted workflows exist but none was matched to the serial path (" + how + ")"


def git(d, *args, timeout=300):
    try:
        p = subprocess.run(["git", "-C", d] + list(args), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return p.stdout if p.returncode == 0 else None


def show(d, sha, path):
    try:
        p = subprocess.run(["git", "-C", d, "show", f"{sha}:{path}"], capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace")


def examine(entry, meta):
    repo = entry["repo"]
    rec = {"repo": repo, "commit": None, "stars": meta.get("stars"), "language": meta.get("language"),
           "archived": meta.get("archived"), "pushed_at": meta.get("pushed_at"),
           "default_branch": meta.get("default_branch"),
           "search_runner": entry["runner"], "search_queries": entry["queries"]}
    if meta.get("missing"):
        rec["error"] = "repository not returned by repository search (private, deleted or renamed)"
        return rec
    d = os.path.join(DL, repo.replace("/", "__"))
    shutil.rmtree(d, ignore_errors=True)
    try:
        p = subprocess.run(["git", "clone", "-q", "--bare", "--filter=blob:none", f"--depth={DEPTH}",
                            f"https://github.com/{repo}", d], capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            rec["error"] = "partial fetch failed"
            return rec
        return _examine(entry, rec, d)
    except subprocess.TimeoutExpired:
        rec["error"] = "partial fetch timed out"
        return rec
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _examine(entry, rec, d):
    repo = entry["repo"]
    sha = (git(d, "rev-parse", "HEAD") or "").strip() or None
    rec["commit"] = sha
    if not sha:
        rec["error"] = "default branch head unavailable"
        return rec
    paths = (git(d, "ls-tree", "-r", "--name-only", sha) or "").splitlines()
    rec["test_count_estimate"] = sum(1 for p in paths if TEST_FILE.search(p)) if paths else None
    found = None
    for path in entry["paths"]:
        txt = show(d, sha, path)
        if txt is None:
            continue
        f = find_flags(txt, entry["runner"])
        if f:
            if found is None or (found[3] and not f[1]) or TEMPLATE_PATH.search(found[0]) or INACTIVE_PATH.search(found[0]) or DOC_PATH.search(found[0]):
                found = (path, txt, f[0], f[1])
            if not TEMPLATE_PATH.search(path) and not INACTIVE_PATH.search(path) and not DOC_PATH.search(path) and not f[1]:
                break
    if not found:
        rec.update({"runner": entry["runner"], "flag": None, "file": entry["paths"][0], "line": None,
                    "verbatim_line": None, "running_serially": False,
                    "not_serial_reason": "no serial flag at pinned commit in the hit file(s)",
                    "reason_quote": None, "reason_kind": None, "multi_core_runner": False,
                    "multi_core_method": "n/a (not serial)"})
        return rec
    path, txt, (runner, flag, lineno, line), debug_only = found
    lines = txt.splitlines()
    rec.update({"runner": runner, "flag": flag, "file": path, "line": lineno, "verbatim_line": line})
    nsr = None
    if DOC_PATH.search(path):
        nsr = "flag only in documentation/prose, not an executed config"
    elif INACTIVE_PATH.search(path):
        nsr = "flag is in an inactive file (backup/temp/sample/disabled name), not the active config"
    elif debug_only:
        nsr = "flag only on a debug/watch line (e.g. test:debug --inspect-brk), not the suite run"
    if nsr:
        rec.update({"running_serially": False, "not_serial_reason": nsr, "reason_quote": None,
                    "reason_kind": None, "multi_core_runner": False, "multi_core_method": "n/a (not serial)"})
        return rec
    if TEMPLATE_PATH.search(path):
        rec.update({"running_serially": False,
                    "not_serial_reason": "flag is in a template/example/fixture path, not the repository's own suite",
                    "reason_quote": None, "reason_kind": None, "multi_core_runner": False,
                    "multi_core_method": "n/a (not serial)"})
        return rec
    rec["running_serially"] = True
    rec["playwright_scaffold_default"] = bool(runner == "playwright" and PLAYWRIGHT_SCAFFOLD.search(line))
    is_yaml = path.endswith((".yml", ".yaml"))
    near = comments_near(lines, lineno, is_yaml)
    evidence = [{"source": "same_file", "file": path, "line": n, "text": l} for n, l in near]
    tok = flag_token(flag)
    readmes = [p for p in paths if re.search(r"(^|/)(README|CONTRIBUTING|TESTING|CHANGELOG)[^/]*\.(md|rst|txt)$", p, re.I)
               and p.count("/") <= 1][:4]
    for rp in readmes:
        rt = show(d, sha, rp)
        if not rt:
            continue
        rl = rt.splitlines()
        for i, l in enumerate(rl):
            if tok and tok.lower() in l.lower():
                for n in range(max(1, i + 1 - 1), min(len(rl), i + 1 + 1) + 1):
                    evidence.append({"source": "doc", "file": rp, "line": n, "text": rl[n - 1]})
    # blame within the fetched depth: the commit that last touched the flag line
    bl = git(d, "blame", "--porcelain", "-L", f"{lineno},{lineno}", sha, "--", path, timeout=240)
    rec["blame_commit"] = None
    if bl:
        first = bl.splitlines()[0].split()
        boundary = "\nboundary" in bl
        rec["blame_commit"] = first[0]
        rec["blame_boundary"] = boundary  # true: line is older than the fetched depth; commit is the shallow boundary
        if not boundary:
            msg = git(d, "log", "-1", "--format=%B", first[0]) or ""
            if not (SERIALISH.search(msg) or (tok and tok.lower() in msg.lower())):
                msg = ""
            for j, ml in enumerate(msg.splitlines()):
                if ml.strip():
                    evidence.append({"source": "commit_message", "file": f"commit {first[0]}", "line": j + 1, "text": ml})
    rec["evidence"] = evidence
    classify(rec)
    wf_paths = [p for p in paths if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))][:20]
    wtext = {}
    for wp in wf_paths:
        t = txt if wp == path else show(d, sha, wp)
        if t:
            wtext[wp] = t
    mc, method = decide_multi_core(repo, sha, paths, path, line, lines, wtext)
    rec["multi_core_runner"] = mc
    rec["multi_core_method"] = method
    return rec


def is_evidence_line(e):
    """same-file evidence must be a comment, or a YAML step name (kept for stated, never implied)."""
    if e["source"] != "same_file":
        return True
    return bool(comment_text(e["text"]) or COMMENTED.match(e["text"]) or YAML_NAME.search(e["text"]))


def classify(rec):
    rec["evidence"] = [e for e in rec.get("evidence", []) if is_evidence_line(e)]
    ev = rec["evidence"]

    def why(e):
        if WHY_BREAK.search(e["text"]) or WHY_RESOURCE.search(e["text"]):
            return True
        return e["source"] != "commit_message" and bool(WHY_CONNECT.search(e["text"]))
    stated = [e for e in ev if why(e)]
    comments = [e for e in ev if e["source"] == "same_file" and not YAML_NAME.search(e["text"])
                and (comment_text(e["text"]) or COMMENTED.match(e["text"])) and CONTEXTY.search(e["text"])]
    rec.pop("auto_reason_all", None)
    if stated:
        stated.sort(key=lambda e: {"same_file": 0, "doc": 1, "commit_message": 2}[e["source"]])
        rec["auto_reason_kind"] = "stated"
        rec["auto_reason"] = stated[0]
        rec["auto_reason_all"] = stated[:8]
    elif comments:
        rec["auto_reason_kind"] = "implied"
        rec["auto_reason"] = comments[0]
    else:
        rec["auto_reason_kind"] = "none"
        rec["auto_reason"] = None


def reclassify():
    """Offline: re-apply path rules and reason rules to raw/examined.jsonl (no network)."""
    path = os.path.join(RAW, "examined.jsonl")
    rows = [json.loads(l) for l in open(path)]
    for r in rows:
        if r.get("not_serial_reason") == "flag is in an inactive file (backup/temp/sample name), not the active config":
            r["not_serial_reason"] = "flag is in an inactive file (backup/temp/sample/disabled name), not the active config"
        if r.get("running_serially"):
            f = r["file"]
            nsr = None
            if DOC_PATH.search(f):
                nsr = "flag only in documentation/prose, not an executed config"
            elif INACTIVE_PATH.search(f):
                nsr = "flag is in an inactive file (backup/temp/sample/disabled name), not the active config"
            elif TEMPLATE_PATH.search(f):
                nsr = "flag is in a template/example/fixture path, not the repository's own suite"
            if nsr:
                r.update({"running_serially": False, "not_serial_reason": nsr, "reason_kind": None,
                          "multi_core_runner": False, "multi_core_method": "n/a (not serial)"})
                for k in ("evidence", "auto_reason", "auto_reason_all", "auto_reason_kind"):
                    r.pop(k, None)
                continue
            classify(r)
    with open(path + ".new", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(path + ".new", path)
    print("reclassified", len(rows))


def recheck_multicore():
    """Re-decide multi_core_runner for serial rows whose decision rested on a config file, using a
    depth-1 blobless fetch of the pinned commit (workflow files only)."""
    path = os.path.join(RAW, "examined.jsonl")
    rows = [json.loads(l) for l in open(path)]
    todo = [r for r in rows if r.get("running_serially") and r.get("multi_core_method", "").startswith(("config file", "default config", "non-default config"))]

    def one(r):
        d = os.path.join(DL, "mc_" + r["repo"].replace("/", "__"))
        shutil.rmtree(d, ignore_errors=True)
        try:
            subprocess.run(["git", "clone", "-q", "--bare", "--filter=blob:none", "--depth=1", f"https://github.com/{r['repo']}", d],
                           capture_output=True, timeout=600)
            if git(d, "cat-file", "-e", r["commit"]) is None:
                git(d, "fetch", "-q", "--filter=blob:none", "--depth=1", "origin", r["commit"])
            paths = (git(d, "ls-tree", "-r", "--name-only", r["commit"]) or "").splitlines()
            if not paths:
                return r, None
            txt = show(d, r["commit"], r["file"]) or ""
            wt = {}
            for wp in [p for p in paths if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))][:20]:
                t = show(d, r["commit"], wp)
                if t:
                    wt[wp] = t
            return r, decide_multi_core(r["repo"], r["commit"], paths, r["file"], r["verbatim_line"], txt.splitlines(), wt)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    changed = 0
    with ThreadPoolExecutor(6) as ex:
        for r, res in ex.map(one, todo):
            if res is None:
                print("could not re-read", r["repo"])
                continue
            if res[0] != r["multi_core_runner"]:
                changed += 1
            r["multi_core_runner"], r["multi_core_method"] = res
    with open(path + ".new", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(path + ".new", path)
    print(f"rechecked {len(todo)}, changed {changed}")


def main():
    if "--reclassify" in sys.argv:
        return reclassify()
    if "--recheck-multicore" in sys.argv:
        return recheck_multicore()
    max_repos = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    hits = [json.loads(l) for l in open(os.path.join(RAW, "hits.jsonl"))]
    metas = {}
    for l in open(os.path.join(RAW, "repo_meta.jsonl")):
        m = json.loads(l)
        metas.setdefault(m["repo"].lower(), m)
    # Sampling rule: for each query, the first PER_QUERY non-fork repositories in the order
    # GitHub code search returned them; a repository hit by several queries is examined once.
    per_query = {}
    by_repo = {}
    for h in hits:
        if h.get("fork"):
            continue
        seen = per_query.setdefault(h["query"], [])
        if h["repo"] not in seen and h["repo"] not in by_repo and len(seen) >= PER_QUERY:
            continue
        if h["repo"] not in seen:
            seen.append(h["repo"])
        e = by_repo.setdefault(h["repo"], {"repo": h["repo"], "runner": h["runner"], "paths": [], "queries": []})
        if h["path"] not in e["paths"]:
            e["paths"].append(h["path"])
        if h["query"] not in e["queries"]:
            e["queries"].append(h["query"])
    out_path = os.path.join(RAW, "examined.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["repo"] for l in open(out_path)}
    todo = [e for r, e in by_repo.items() if r not in done and r.lower() in metas
            and not metas[r.lower()].get("fork")][:max_repos]
    print(f"{len(by_repo)} repos from search, {len(done)} done, examining {len(todo)}", flush=True)
    with open(out_path, "a") as out, ThreadPoolExecutor(6) as ex:
        for i, rec in enumerate(ex.map(lambda e: examine(e, metas[e["repo"].lower()]), todo)):
            out.write(json.dumps(rec) + "\n")
            out.flush()
            if i % 20 == 0:
                print(i, rec["repo"], rec.get("flag"), rec.get("auto_reason_kind"), flush=True)


if __name__ == "__main__":
    main()
