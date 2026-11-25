"""Agent tools count rules (pure functions): Count 2's check rules (copied from
origin/claude/agent-pr-scan-count2 3aee9ba harness/agent_pr_scan_count2/rules.py), plus the Count A rules
(evidence, agent commits, wasted commits, pull request result, decision (a)) and the Count B rules (links, agent
pull requests, issue classes, choice labels, decision (b)).

Every result is produced through these functions both in the Actions job (live API) and in ``verify.py`` (replay of
the committed raw JSON). PREREG.md quotes every regex below verbatim.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from fractions import Fraction

# ================================================================ Count 2 rules (copied)

FAILED_RUN = {"failure", "timed_out", "startup_failure"}
FAILED_STATUS = {"failure", "error"}
ALREADY_RED, NEW_RED, NO_BASE_SIGNAL, UNREADABLE = "ALREADY_RED", "NEW_RED", "NO_BASE_SIGNAL", "UNREADABLE"
WINDOW = dt.timedelta(days=7)


def ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_failed(conclusion: str | None) -> bool:
    return conclusion in FAILED_RUN


def status_failed(state: str | None) -> bool:
    return state in FAILED_STATUS


def actions_identity(workflow_name: str, job_name: str) -> str:
    return f"{workflow_name} / {job_name}"


def result_of_run(conclusion: str | None) -> str | None:
    if conclusion in FAILED_RUN:
        return ALREADY_RED
    if conclusion == "success":
        return NEW_RED
    return None


def result_of_status(state: str | None) -> str | None:
    if state in FAILED_STATUS:
        return ALREADY_RED
    if state == "success":
        return NEW_RED
    return None


def pick_primary(base_results: list[dict], head_started: dt.datetime) -> dict | None:
    """Count 2: most recent usable base result of one identity, started in [S - 7 days, S)."""
    ok = [b for b in base_results if b["completed"] and b["signal"] and b["started"] is not None
          and head_started - WINDOW <= b["started"] < head_started]
    return max(ok, key=lambda b: b["started"]) if ok else None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


# ================================================================ Count A: failure evidence (§1.5)

EVIDENCE_RE = re.compile(
    r"""(?:^|[\s("'`])(?:/home/runner/work/[^/\s]+/[^/\s]+/|\./)?((?:[\w.-]+/)*[\w.-]+\.(?:jsx|tsx|mjs|cjs|js|ts|py|rb|go|rs|java|kt|php|cs|swift|scala|exs|ex|vue|svelte|cpp|c|h|dart))(?![\w.])(?::\d+(?::\d+)?)?""",
    re.MULTILINE)
PASS_RE = re.compile(r"\bPASS(ED)?\b")
EXCLUDED_DIRS = {"node_modules", "vendor", ".venv", "site-packages", "dist", "build"}


def _norm(p: str) -> str:
    while p.startswith("./"):
        p = p[2:]
    return p


def excluded_dir(path: str) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.split("/")[:-1])


def is_github_path(path: str) -> bool:
    return path == ".github" or path.startswith(".github/")


def text_candidates(text: str) -> list[str]:
    """Paths named in a check run's output text, line by line; lines matching PASS_RE or containing a check mark
    are skipped."""
    out = []
    for line in (text or "").splitlines():
        if PASS_RE.search(line) or "✓" in line:
            continue
        for m in EVIDENCE_RE.finditer(line):
            out.append(_norm(m.group(1)))
    return out


def annotation_candidates(annotations: list[dict]) -> list[str]:
    out = []
    for a in annotations or []:
        p = a.get("path")
        if a.get("annotation_level") != "failure" or not p:
            continue
        p = _norm(p)
        if is_github_path(p):
            continue
        out.append(p)
    return out


def evidence_candidates(annotations: list[dict], output: dict | None) -> list[str]:
    """Candidate failure files of one check run, before the tree filter (sorted, unique, excluded dirs removed)."""
    o = output or {}
    text = "\n".join(str(o.get(k) or "") for k in ("title", "summary", "text"))
    c = annotation_candidates(annotations) + text_candidates(text)
    return sorted({p for p in c if p and not excluded_dir(p)})


def failure_files(candidates: list[str], exists) -> list[str]:
    """Keep the candidates that are blobs in the tree (``exists(path) -> bool``)."""
    return [p for p in candidates if exists(p)]


def in_base(path: str, base_files: list[str] | None) -> str:
    """Gate rev 3 note 2: ``yes`` / ``no`` / ``base-unknown`` (B(X) evidence is ``none``)."""
    if not base_files:
        return "base-unknown"
    return "yes" if path in base_files else "no"


# ================================================================ Count A: agent commits (§1.6)

COMMIT_LOGINS = {"copilot": {"Copilot"}, "devin": {"devin-ai-integration[bot]"},
                 "jules": {"google-labs-jules[bot]"}}
CLAUDE_COMMIT_RE = re.compile(r"Co-Authored-By: Claude|Generated with \[?Claude Code", re.IGNORECASE)
CLAUDE_BOT = "claude[bot]"


def is_agent_commit(family: str, commit: dict, pr_author: str | None, head_ref: str | None) -> bool:
    """commit: {author_login, message}."""
    login = commit.get("author_login")
    if family in COMMIT_LOGINS:
        return login in COMMIT_LOGINS[family]
    if family == "claude_code":
        return bool(CLAUDE_COMMIT_RE.search(commit.get("message") or "")) or login == CLAUDE_BOT
    if family == "codex":
        # Change before chunk 1 (probe): Codex commits carry no linked author login (null); on a codex/ head ref
        # a commit without a linked login counts as the agent's, as does one by the pull request author.
        return bool(head_ref and head_ref.startswith("codex/") and (login is None or login == pr_author))
    return False


# ================================================================ Count A: wasted commits (§1.7)

FIX_MSG_RE = re.compile(
    r"\b(fix(e[sd])?|repair(ed)?|resolve[sd]?)\b[^.\n]{0,30}\b(failing|broken|flaky|red)?\s*(tests?|ci|build|checks?|pipeline|lint)\b",
    re.IGNORECASE)


def wasted_reasons(commit: dict, x: dict, new_red_before: bool) -> list[str]:
    """Rules (i)-(iii) for one agent commit inside X's window.

    commit: {message, files: [filename, ...]}; x: {failure_files: [...], workflow_paths: [...]};
    new_red_before: a NEW_RED check failed on the latest earlier commit that has check results."""
    files = set(commit.get("files") or [])
    r = []
    if files & set(x.get("failure_files") or []):
        r.append("i")
    if FIX_MSG_RE.search(commit.get("message") or "") and not new_red_before:
        r.append("ii")
    if files & set(x.get("workflow_paths") or []):
        r.append("iii")
    return r


def x_window(k: int, states: dict[int, str], n_commits: int) -> int:
    """Last commit position (inclusive) of X's window: the first position j > k where X passes, or fails with a
    NEW_RED verdict (gate rev 4 note 4); else the last commit. ``states``: position -> ``pass`` / ``already`` /
    ``new_red`` / ``fail_other`` / absent."""
    for j in range(k + 1, n_commits + 1):
        if states.get(j) in ("pass", "new_red"):
            return j
    return n_commits


def in_window(c: dict, k: int, T: dt.datetime | None, end: int) -> bool:
    """c: {pos, date (datetime), parents (int)}. After k (position and committer date after T), not past the
    window end, not a merge."""
    if c["parents"] >= 2 or not (k < c["pos"] <= end):
        return False
    return T is None or (c["date"] is not None and c["date"] > T)


def after_k(c: dict, k: int, T: dt.datetime | None) -> bool:
    """Agent commit after k regardless of the window (for ``not-wasted`` vs ``no-later-commit``); merges excluded."""
    if c["parents"] >= 2 or c["pos"] <= k:
        return False
    return T is None or (c["date"] is not None and c["date"] > T)


WASTED, NOT_WASTED, NO_LATER, UNCERTAIN, NOT_RATEABLE = (
    "wasted", "not-wasted", "no-later-commit", "uncertain", "not-rateable")
RATEABLE_A = (WASTED, NOT_WASTED, NO_LATER)


def pr_result(any_x: bool, any_wasted: bool, any_agent_after: bool) -> str:
    if not any_x:
        return NOT_RATEABLE
    if any_wasted:
        return WASTED
    return NOT_WASTED if any_agent_after else NO_LATER


W_CODES = {"W-file", "W-msg", "W-ci"}
R_CODES = {"R-product", "R-own", "R-sync"}


def hand_result(auto: str, codes: list[str]) -> str:
    """§1.9: a ``wasted`` pull request whose hand-read codes are all R-* becomes ``not-wasted``."""
    if auto != WASTED:
        return auto
    if codes and all(c in R_CODES for c in codes):
        return NOT_WASTED
    return WASTED


# ================================================================ decisions

CONTINUE, DROP, NED = "CONTINUE", "DROP", "NOT ENOUGH DATA"
A_THRESHOLD = Fraction(20, 100)
A_FILES_MIN = Fraction(40, 100)
B_THRESHOLD = Fraction(5, 100)
B_MIN_ADDRESSED = 200


def decide_a(wasted: int, rateable: int, files_share: Fraction | float, misses: int = 0, sample_n: int = 30,
             not_wasted: int = 0) -> str:
    """Decision (a) on the point estimate; NOT ENOUGH DATA when files evidence < 40% and Rate A < 20%, or (gate
    rev 4 note 1) with 1-3 sample misses when the miss-adjusted rate reaches 20% while Rate A does not."""
    if rateable == 0:
        return NED
    rate = Fraction(wasted, rateable)
    if rate >= A_THRESHOLD:
        return CONTINUE
    if Fraction(files_share).limit_denominator(10 ** 9) < A_FILES_MIN:
        return NED
    if 1 <= misses <= 3 and sample_n:
        adj = (wasted + Fraction(misses, sample_n) * not_wasted) / rateable
        if adj >= A_THRESHOLD:
            return NED
    return DROP


def miss_adjusted(wasted: int, rateable: int, misses: int, sample_n: int, not_wasted: int) -> float:
    if rateable == 0 or not sample_n:
        return float("nan")
    return float((wasted + Fraction(misses, sample_n) * not_wasted) / rateable)


def decide_b(competing: int, addressed: int) -> str:
    if addressed < B_MIN_ADDRESSED:
        return NED
    return CONTINUE if Fraction(competing, addressed) >= B_THRESHOLD else DROP


# ================================================================ Count B: agent pull requests (§2.3)

PR_LOGINS = {"copilot": {"Copilot"}, "devin": {"devin-ai-integration[bot]"}, "jules": {"google-labs-jules[bot]"}}
CODEX_BODY_RE = re.compile(r"chatgpt\.com/codex")
CLAUDE_BODY_RE = re.compile(r"Generated with \[?Claude Code", re.IGNORECASE)


def body_flags(body: str | None) -> dict:
    b = body or ""
    return {"codex": bool(CODEX_BODY_RE.search(b)), "claude_code": bool(CLAUDE_BODY_RE.search(b))}


def pr_family(login: str | None, head_ref: str | None, flags: dict) -> str | None:
    for fam, logins in PR_LOGINS.items():
        if login in logins:
            return fam
    if flags.get("codex") and head_ref is not None and head_ref.startswith("codex/"):
        return "codex"
    if flags.get("claude_code"):
        return "claude_code"
    return None


def agent_candidate(login: str | None, flags: dict) -> bool:
    """Could be an agent pull request before its head ref is known (Codex needs the head ref)."""
    return any(login in s for s in PR_LOGINS.values()) or flags.get("codex") or flags.get("claude_code")


# ================================================================ Count B: links (§2.2)

CLOSING_RE = re.compile(
    r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?):?\s+(?:(?P<repo>[\w.-]+/[\w.-]+)?#|https://github\.com/(?P<urlrepo>[\w.-]+/[\w.-]+)/issues/)(?P<num>\d+)(?!\d)",
    re.IGNORECASE)


def closes(body: str | None, repo: str, number: int) -> bool:
    for m in CLOSING_RE.finditer(body or ""):
        r = m.group("repo") or m.group("urlrepo")
        if int(m.group("num")) == number and (r is None or r.lower() == repo.lower()):
            return True
    return False


def ref_names_issue(head_ref: str | None, number: int) -> bool:
    return bool(head_ref) and re.search(rf"(^|[/_-]){number}([/_-]|$)", head_ref) is not None


def same_repo_pr_xref(ev: dict, repo: str) -> bool:
    return ev.get("is_pr") and (ev.get("repo") or "").lower() == repo.lower()


# ================================================================ Count B: classes (§2.4) and labels (§2.5)

AGENT_ADDRESSED, COMPETING, SEQUENTIAL, SINGLE = "agent-addressed", "competing", "sequential", "single"
INF = dt.datetime.max.replace(tzinfo=dt.timezone.utc)


def pr_end(p: dict) -> dt.datetime:
    return ts(p.get("merged_at")) or ts(p.get("closed_at")) or INF


def overlap(a: dict, b: dict) -> bool:
    return ts(a["created_at"]) < pr_end(b) and ts(b["created_at"]) < pr_end(a)


def issue_class(agent_prs: list[dict]) -> str | None:
    """None (not agent-addressed), ``single``, ``competing`` or ``sequential``. Distinct by pull request number."""
    prs = list({p["number"]: p for p in agent_prs}.values())
    if not prs:
        return None
    if len(prs) == 1:
        return SINGLE
    for i in range(len(prs)):
        for j in range(i + 1, len(prs)):
            if overlap(prs[i], prs[j]):
                return COMPETING
    return SEQUENTIAL


GREEN_OK = {"success", "skipped", "neutral"}
GREEN_BAD = {"failure", "timed_out", "cancelled", "action_required"}


def green_time(check_runs: list[dict]) -> dt.datetime | None:
    """Gate rev 3 note 8: all completed with success/skipped/neutral and none bad -> latest completed_at."""
    if not check_runs:
        return None
    if any(r.get("conclusion") in GREEN_BAD for r in check_runs):
        return None
    if not all(r.get("status") == "completed" and r.get("conclusion") in GREEN_OK for r in check_runs):
        return None
    t = [ts(r.get("completed_at")) for r in check_runs if r.get("completed_at")]
    return max(t) if t else None


def choice_labels(prs: list[dict]) -> list[str]:
    """prs: {number, created_at, merged_at, green (iso|None), approved (bool)}."""
    merged = [p for p in prs if p.get("merged_at")]
    if not merged:
        return ["none-merged"]
    m = min(merged, key=lambda p: ts(p["merged_at"]))
    others = [p for p in prs if p["number"] != m["number"]]
    labels = []
    if all(ts(m["created_at"]) < ts(o["created_at"]) for o in others):
        labels.append("first-opened")
    g = ts(m.get("green"))
    if g is not None and all(ts(o.get("green")) is None or g < ts(o["green"]) for o in others):
        labels.append("first-green")
    if g is not None and all(o.get("green") is None for o in others):
        labels.append("only-green")
    if m.get("approved") and not any(o.get("approved") for o in others):
        labels.append("reviewed")
    return labels or ["other"]
