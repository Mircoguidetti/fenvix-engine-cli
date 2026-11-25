"""C5.3 decision rules (PREREG.md): exclusions, runner detection (2.5), job matching at B0 (2.6), job features."""
from __future__ import annotations

import datetime as dt
import re

FAMILIES = ["copilot", "devin", "jules", "codex", "claude_code"]
QUERIES = {
    "copilot": "is:pr is:public author:app/copilot-swe-agent",
    "devin": "is:pr is:public author:app/devin-ai-integration",
    "jules": "is:pr is:public author:app/google-labs-jules",
    "codex": "is:pr is:public head:codex/",
    "claude_code": 'is:pr is:public "Generated with Claude Code"',
}
CODEX_MARK = re.compile(r"chatgpt\.com/codex", re.I)
CC_MARK = re.compile(r"Generated with \[?Claude Code", re.I)
EXCLUDED_OWNERS = {"mircoguidetti", "github", "anthropics", "openai", "microsoft"}
FAILED = ("failure", "timed_out")
OS_LABEL = re.compile(r"windows|macos", re.I)

# ---------------------------------------------------------------- 2.2 / 2.3


def family_ok(family: str, body: str | None) -> bool:
    body = body or ""
    if family == "codex":
        return bool(CODEX_MARK.search(body))
    if family == "claude_code":
        return bool(CC_MARK.search(body))
    return True


def owner_excluded(full_name: str) -> bool:
    return full_name.split("/", 1)[0].lower() in EXCLUDED_OWNERS


def ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def repo_exclusion(meta_status, meta: dict | None) -> str | None:
    """Repository-level reason from GET repos/{o}/{r}, or None."""
    if meta_status != 200 or not isinstance(meta, dict):
        return "repo_unreadable"
    if meta.get("fork"):
        return "fork"
    if meta.get("archived"):
        return "archived"
    if meta.get("private"):
        return "private"
    return None


def too_young(repo_created_at: str, pr_created_at: str) -> bool:
    return ts(pr_created_at) - ts(repo_created_at) < dt.timedelta(days=30)


def repo_order(pool: list[dict]) -> list[tuple[str, int]]:
    """[(full_name, raw pool count)] after owner exclusions: count descending, then full_name ascending."""
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for r in pool:
        k = r["repo"].lower()
        if owner_excluded(k):
            continue
        counts[k] = counts.get(k, 0) + 1
        names.setdefault(k, r["repo"])
    return [(names[k], counts[k]) for k in sorted(counts, key=lambda k: (-counts[k], k))]


def candidate(job: dict) -> bool:
    return job.get("conclusion") in FAILED and not any(OS_LABEL.search(str(x)) for x in job.get("labels") or [])

# ---------------------------------------------------------------- 2.5 runner of a failed job


TS_PREFIX = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RUNNERS = {
    "vitest": re.compile(r"^\s*Test Files\s+(\d+) failed"),
    "jest": re.compile(r"^Tests:\s+(\d+) failed"),
    "node-test": re.compile(r"^(?:ℹ|#) fail (\d+)\s*$"),
    "pytest": re.compile(r"^=+ .*?\b(\d+) failed\b.* in [\d.]+s.*=+\s*$"),
}
NO_RUNNER, AMBIGUOUS = "no_runner", "ambiguous_runner"


def clean_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.lstrip("\ufeff")
        line = TS_PREFIX.sub("", line, count=1)
        out.append(ANSI.sub("", line))
    return out


def detect_runner(text: str) -> tuple[str, int | None]:
    """(runner | no_runner | ambiguous_runner, index of the summary line kept for the excerpt or None)."""
    lines = clean_lines(text)
    first: dict[str, int] = {}
    for i, line in enumerate(lines):
        for name, pat in RUNNERS.items():
            if name in first:
                continue
            m = pat.search(line)
            if m and int(m.group(1)) >= 1:
                first[name] = i
    if not first:
        return NO_RUNNER, None
    if len(first) > 1:
        return AMBIGUOUS, min(first.values())
    (name, i), = first.items()
    return name, i


def excerpt(text: str, idx: int, before: int = 200) -> str:
    """The summary line and at most ``before`` lines before it, from the raw log lines."""
    raw = text.splitlines()
    return "\n".join(raw[max(0, idx - before): idx + 1]) + "\n"

# ---------------------------------------------------------------- 2.6 job definition at B0


EXPR = re.compile(r"\$\{\{.*?\}\}", re.S)
MATRIX_SUFFIX = re.compile(r"^(.*) \(([^()]*)\)$")
FOUND, ABSENT, REUSABLE = "found", "job_absent_at_base", "reusable_workflow_job"


def _strip_suffix(n: str) -> str | None:
    m = MATRIX_SUFFIX.match(n)
    return m.group(1) if m else None


def _name_matches(name, key: str, n: str) -> bool:
    base = _strip_suffix(n)
    if isinstance(name, str):
        if name == n:  # (a)
            return True
        if EXPR.search(name):  # (b)
            parts = EXPR.split(name)
            rx = "^" + ".*".join(re.escape(p) for p in parts) + "$"
            return re.match(rx, n, re.S) is not None
        return base is not None and name == base  # (c)
    if name is None:  # (d)
        return key == n or (base is not None and key == base)
    return False


def match_job(wf, n: str) -> tuple[str, str | None]:
    """(found | job_absent_at_base | reusable_workflow_job, job key or None)."""
    jobs = wf.get("jobs") if isinstance(wf, dict) else None
    if not isinstance(jobs, dict):
        return ABSENT, None
    if " / " in n:
        caller = n.split(" / ", 1)[0]
        for key, job in jobs.items():
            if isinstance(job, dict) and "uses" in job and (str(key) == caller or job.get("name") == caller):
                return REUSABLE, str(key)
    hits = [str(k) for k, j in jobs.items() if isinstance(j, dict) and _name_matches(j.get("name"), str(k), n)]
    if len(hits) == 1:
        return FOUND, hits[0]
    return ABSENT, None


SECRET = re.compile(r"secrets\.(\w+)")


def _walk_strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk_strings(v)


def uses_secrets(job: dict) -> bool:
    for s in _walk_strings(job):
        if "vars." in s:
            return True
        if any(name != "GITHUB_TOKEN" for name in SECRET.findall(s)):
            return True
    return False


def features(job: dict) -> dict:
    services = job.get("services") or {}
    svc = {str(k): (v.get("image") if isinstance(v, dict) else v) for k, v in services.items()} \
        if isinstance(services, dict) else str(services)
    matrix = (job.get("strategy") or {}).get("matrix") if isinstance(job.get("strategy"), dict) else None
    if isinstance(matrix, dict):
        mx = {str(k): (len(v) if isinstance(v, list) else str(v)) for k, v in matrix.items()}
    elif matrix is None:
        mx = None
    else:
        mx = str(matrix)
    needs = job.get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    steps = job.get("steps") if isinstance(job.get("steps"), list) else []
    return {"runs_on": job.get("runs-on"), "services": svc, "matrix": mx, "container": "container" in job,
            "needs": needs, "uses": [s["uses"] for s in steps if isinstance(s, dict) and "uses" in s],
            "uses_secrets": uses_secrets(job)}
