"""Pure rules of the market direction check (PREREG Part 1 §1.2-1.5, Part 2 §2.4, verdict). No network.

Files come from ``read(path) -> text | None``; run listings and job lists are passed in or come from callables, so
every rule is unit-tested on fixtures (test_market_direction.py).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import posixpath
import random
import re

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

import dsc_rules as R

UTC = dt.timezone.utc
T0_UPPER = dt.datetime(2026, 5, 24, 23, 59, 59, tzinfo=UTC)
AGENT_PATHS = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", ".windsurfrules", ".clinerules",
               ".github/copilot-instructions.md", ".github/instructions/", ".cursor/rules/"]
EVAL_DEPS = ["promptfoo", "deepeval", "ragas", "langsmith", "braintrust", "inspect-ai", "inspect_ai", "trulens",
             "trulens-eval", "arize-phoenix", "langfuse"]
DROP_REASONS = ["excluded", "no_language", "no_root_file", "t0_out_of_range", "no_test_step", "unresolved",
                "too_few_runs", "retention", "zero_duration", "no_control", "error"]


def ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(d: dt.datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------------------------------ §1.2 step 1-2

def excluded(repo: dict, launch: dt.date) -> str | None:
    """1.2 step 1: 'excluded' / 'no_language' / None."""
    cut = dt.datetime.combine(launch - dt.timedelta(days=30), dt.time(), UTC)
    if repo.get("fork") or repo.get("archived") or (repo.get("stargazers_count") or 0) < 10 \
            or not repo.get("pushed_at") or ts(repo["pushed_at"]) < cut:
        return "excluded"
    if repo.get("language") is None:
        return "no_language"
    return None


def t0_of(commit_lists: list[list[dict]]) -> dt.datetime | None:
    """T0 = minimum committer date over all commits (both files)."""
    dates = [ts(c["commit"]["committer"]["date"]) for cl in commit_lists for c in cl
             if ((c.get("commit") or {}).get("committer") or {}).get("date")]
    return min(dates) if dates else None


def t0_in_range(t0: dt.datetime, t0_min: dt.date) -> bool:
    return dt.datetime.combine(t0_min, dt.time(), UTC) <= t0 <= T0_UPPER


# ------------------------------------------------------------------------------------------------ §1.2 step 3

def only_workflow_call(wf: dict) -> bool:
    return R.triggers(wf) == {"workflow_call"}


def job_test_steps(job: dict, wf: dict, read) -> dict:
    """§2.2 for one job: indices of candidate steps, of resolving steps (>= 1 runner line, no Unresolved), and the
    runner lines. A step 'resolves' when every runner command of it resolves and at least one gives a runner line."""
    steps = job.get("steps") or []
    cand, resolving, unresolved, lines = [], [], [], {}
    for i, st in enumerate(steps):
        if not isinstance(st, dict) or not st.get("run"):
            continue
        cmds = [c for c in R.kept_commands(str(st["run"])) if R.is_runner_command(c)]
        if not cmds:
            continue
        cand.append(i)
        wd = R.working_dir(st, job, wf)
        if wd is None:  # expression in working-directory
            unresolved.append(i)
            continue
        got, bad = [], False
        for c in cmds:
            try:
                got += R.resolve_command(c, wd, read, "", None)
            except R.Unresolved:
                bad = True
        if bad:
            unresolved.append(i)
        elif got:
            resolving.append(i)
            lines[i] = [ln.text for ln in got]
    return {"candidates": cand, "resolving": resolving, "unresolved": unresolved, "lines": lines}


def measured_job(files: list[tuple[str, str | None]], read) -> dict:
    """1.2 step 3. ``files`` = [(path, text)] of .github/workflows (.yml/.yaml) at the T0 commit.
    Returns {"WF", "key", "name", "steps"} or {"reason": no_test_step|unresolved, "detail"}."""
    any_cand = False
    detail = []
    for path, text in sorted(files):
        if not path.endswith((".yml", ".yaml")) or text is None:
            continue
        try:
            wf = R.load_yaml(text)
        except Exception as e:
            detail.append(f"{path}: yaml {type(e).__name__}")
            continue
        if only_workflow_call(wf):
            detail.append(f"{path}: workflow_call only")
            continue
        jobs = wf.get("jobs") or {}
        if not isinstance(jobs, dict):
            continue
        for key, job in jobs.items():
            if not isinstance(job, dict) or job.get("uses"):
                continue
            ts_ = job_test_steps(job, wf, read)
            if ts_["candidates"]:
                any_cand = True
            if ts_["resolving"]:
                return {"WF": path, "key": str(key), "name": str(job.get("name") or key),
                        "steps": ts_["resolving"], "lines": ts_["lines"]}
    return {"reason": "unresolved" if any_cand else "no_test_step", "detail": detail}


# ------------------------------------------------------------------------------------------------ §1.2 step 4

def d0_subranges(t0: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    """[T0 - 90 d, T0) in 7-day half-open sub-ranges anchored at T0, newest first."""
    lo, out, end = t0 - dt.timedelta(days=90), [], t0
    while end > lo:
        start = max(end - dt.timedelta(days=7), lo)
        out.append((start, end))
        end = start
    return out


def d1_subranges(t0: dt.datetime, read_time: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    """[T0 + 182 d, min(T0 + 272 d, read time)] in 7-day sub-ranges, oldest first. Sub-ranges are half-open
    [s, e) except the last, which is closed (the window's end is included)."""
    s, hi = t0 + dt.timedelta(days=182), min(t0 + dt.timedelta(days=272), read_time)
    out = []
    while s <= hi:
        e = min(s + dt.timedelta(days=7), hi)
        out.append((s, e))
        if e >= hi:
            break
        s = e
    return out


def split_range(s: dt.datetime, e: dt.datetime, unit: str) -> list[tuple[dt.datetime, dt.datetime]]:
    step = dt.timedelta(days=1) if unit == "day" else dt.timedelta(hours=1)
    out, x = [], s
    while x < e:
        out.append((x, min(x + step, e)))
        x = x + step
    return out or [(s, e)]


def in_range(created: str, s: dt.datetime, e: dt.datetime, closed: bool) -> bool:
    c = ts(created)
    return s <= c <= e if closed else s <= c < e


def keep_run(run: dict) -> bool:
    return not str(run.get("event") or "").startswith("pull_request")


class JobLevel(Exception):
    """Raised by a step-level value function when a matched job has an empty steps list."""


def select_window(subranges, list_runs, value_of, newest_first: bool, closed_last: bool = False,
                  need: int = 10) -> list[tuple[dict, float]]:
    """Walk sub-ranges in order; within each, runs sorted newest-first (D0) or oldest-first (D1); return the first
    ``need`` (run, value) pairs whose value is not None. ``list_runs(s, e)`` returns raw runs (any created_at);
    the half-open bound is enforced here. ``value_of(run)`` may raise JobLevel."""
    got = []
    for k, (s, e) in enumerate(subranges):
        closed = closed_last and k == len(subranges) - 1
        runs = [r for r in list_runs(s, e) if keep_run(r) and in_range(r["created_at"], s, e, closed)]
        seen, uniq = set(), []
        for r in runs:
            if r["id"] not in seen:
                seen.add(r["id"])
                uniq.append(r)
        uniq.sort(key=lambda r: (r["created_at"], r["id"]), reverse=newest_first)
        for r in uniq:
            v = value_of(r)
            if v is not None:
                got.append((r, v))
                if len(got) >= need:
                    return got
    return got


# ------------------------------------------------------------------------------------------------ §1.2 step 5

def api_legs(api_jobs: list[dict], yaml_name: str) -> list[dict]:
    """§3.2: API jobs whose name matches the YAML job name pattern, with conclusion success."""
    return [j for j in api_jobs if R.job_matches(j.get("name") or "", yaml_name) and j.get("conclusion") == "success"]


def seconds(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return (ts(b) - ts(a)).total_seconds()


def run_value(wf_text: str | None, key: str, read, api_jobs: list[dict], level: str) -> float | None:
    """1.2 step 5. ``wf_text`` = WF at head_sha; ``read`` reads files at head_sha. Step level: per leg the sum of the
    durations of every resolving §2.2 test step, all matched (§3.3) and success; value = max over legs with a value.
    Raises JobLevel at step level when a matched leg has an empty steps list. Job level: max over legs of the job's
    completed_at - started_at. Note 10: no resolving test step at head_sha -> None (both levels)."""
    if wf_text is None:
        return None
    try:
        wf = R.load_yaml(wf_text)
    except Exception:
        return None
    job = (wf.get("jobs") or {}).get(key) if isinstance(wf.get("jobs"), dict) else None
    if not isinstance(job, dict):
        return None
    tsx = job_test_steps(job, wf, read)
    if not tsx["resolving"]:
        return None
    legs = api_legs(api_jobs, str(job.get("name") or key))
    if not legs:
        return None
    if level == "job":
        vals = [seconds(j.get("started_at"), j.get("completed_at")) for j in legs]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else None
    if any(not (j.get("steps") or []) for j in legs):
        raise JobLevel()
    steps = job.get("steps") or []
    vals = []
    for j in legs:
        total, ok = 0.0, True
        for i in tsx["resolving"]:
            s = R.pick_api_step(j["steps"], steps, i)
            d = R.step_seconds(s)
            if d is None:
                ok = False
                break
            total += d
        if ok:
            vals.append(total)
    return max(vals) if vals else None


def median(values: list[float]) -> float:
    v = sorted(values)
    n = len(v)
    if n == 0:
        raise ValueError("median of nothing")
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def median10(values: list[float]) -> float | None:
    """§3.4: exactly 10 values; mean of the 5th and 6th sorted."""
    if len(values) < 10:
        return None
    v = sorted(values[:10])
    return (v[4] + v[5]) / 2


# ------------------------------------------------------------------------------------------------ §1.3 control

def control_query(language: str, stars: int, launch: dt.date) -> str:
    lo, hi = math.floor(0.5 * stars), math.ceil(1.5 * stars)
    return (f'language:"{language}" stars:{lo}..{hi} pushed:>={(launch - dt.timedelta(days=30)).isoformat()} '
            f"archived:false fork:false")


def control_order(items: list[dict], frame_repos: set[str], agent_repo: str, agent_id: int) -> list[dict]:
    seen, out = set(), []
    for it in items:
        fn = it["full_name"]
        if fn in seen or fn in frame_repos or fn == agent_repo:
            continue
        seen.add(fn)
        out.append(it)
    out.sort(key=lambda x: x["id"])
    random.Random(agent_id).shuffle(out)
    return out[:100]


def agent_file_hit(path_results: dict[str, list]) -> list[str]:
    """Paths (of the 9) whose commits query returned at least one commit."""
    return [p for p in AGENT_PATHS if path_results.get(p)]


# ------------------------------------------------------------------------------------------------ §1.4 statistic

def faster(g_agent: list[float], g_control: list[float]) -> bool:
    return median(g_agent) > median(g_control)


def bootstrap(pairs: list[tuple[float, float]], n_res: int = 10000, seed: int = 2) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(pairs)
    diffs = []
    for _ in range(n_res):
        s = [pairs[rng.randrange(n)] for _ in range(n)]
        diffs.append(median([a for a, _ in s]) - median([c for _, c in s]))
    diffs.sort()
    return diffs[249], diffs[9749]


# ------------------------------------------------------------------------------------------------ §1.5 eval setup

def norm_dep(name: str) -> str:
    return name.strip().lower().replace("_", "-")


EVAL_NORM = {norm_dep(x) for x in EVAL_DEPS}


def dep_names(path: str, text: str) -> tuple[set[str], bool]:
    """(normalised dependency names, has a git dependency on openai/evals)."""
    names, git_evals = set(), bool(re.search(r"github\.com[/:]openai/evals\b", text or ""))
    base = posixpath.basename(path)
    if base == "package.json":
        try:
            d = json.loads(text)
            for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
                names |= {norm_dep(x) for x in (d.get(k) or {})}
        except Exception:
            pass
        return names, git_evals
    if base == "pyproject.toml" and tomllib is not None:
        try:
            d = tomllib.loads(text)
        except Exception:
            d = {}
        reqs = list((d.get("project") or {}).get("dependencies") or [])
        for v in ((d.get("project") or {}).get("optional-dependencies") or {}).values():
            reqs += list(v or [])
        for v in (d.get("dependency-groups") or {}).values():
            reqs += [x for x in (v or []) if isinstance(x, str)]
        poetry = ((d.get("tool") or {}).get("poetry") or {})
        names |= {norm_dep(x) for x in (poetry.get("dependencies") or {})}
        names |= {norm_dep(x) for x in (poetry.get("dev-dependencies") or {})}
        for g in (poetry.get("group") or {}).values():
            names |= {norm_dep(x) for x in ((g or {}).get("dependencies") or {})}
        names |= {_req_name(r) for r in reqs if _req_name(r)}
        return names, git_evals
    if base == "Pipfile" and tomllib is not None:
        try:
            d = tomllib.loads(text)
            for k in ("packages", "dev-packages"):
                names |= {norm_dep(x) for x in (d.get(k) or {})}
        except Exception:
            pass
        return names, git_evals
    if base == "setup.cfg":
        m = re.search(r"(?ms)^\s*install_requires\s*=\s*(.*?)(^\S|\Z)", text or "")
        block = m.group(1) if m else ""
        m2 = re.search(r"(?ms)^\[options\.extras_require\](.*?)(^\[|\Z)", text or "")
        block += "\n" + (re.sub(r"(?m)^\s*\w[\w-]*\s*=", "", m2.group(1)) if m2 else "")
        names |= {_req_name(x) for x in block.splitlines() if _req_name(x)}
        return names, git_evals
    # requirements*.txt
    names |= {_req_name(x) for x in (text or "").splitlines() if _req_name(x)}
    return names, git_evals


def _req_name(line: str) -> str | None:
    s = line.split("#", 1)[0].strip()
    if not s or s.startswith("-"):
        return None
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", s)
    return norm_dep(m.group(1)) if m else None


def is_dep_file(path: str) -> bool:
    if path.count("/") > 1:
        return False
    base = posixpath.basename(path)
    return base in ("package.json", "pyproject.toml", "setup.cfg", "Pipfile") or \
        bool(re.match(r"^requirements.*\.txt$", base))


def is_promptfoo_config(path: str) -> bool:
    return path.count("/") <= 1 and posixpath.basename(path) in ("promptfooconfig.yaml", "promptfooconfig.yml")


def eval_setup(files: dict[str, str]) -> tuple[bool, list[str]]:
    """``files`` = {path: text} of dependency files and promptfoo configs at the root or one level down."""
    why = []
    for p, t in sorted(files.items()):
        if is_promptfoo_config(p):
            why.append(p)
            continue
        if not is_dep_file(p):
            continue
        names, git_evals = dep_names(p, t)
        hit = sorted(names & EVAL_NORM)
        if hit:
            why.append(f"{p}: {', '.join(hit)}")
        if git_evals:
            why.append(f"{p}: git openai/evals")
    return bool(why), why


# ------------------------------------------------------------------------------------------------ Part 2

def ratio(f_t: float, f_e: float) -> float:
    if f_t == 0:
        return math.inf if f_e > 0 else 0.0   # both 0 -> R = 0 (Interpretation (PREREG), note 13)
    return f_e / f_t


def part2_failed(n_seed: int, n_seed_unverified: int, any_source: bool) -> bool:
    return n_seed_unverified > 0.25 * n_seed or not any_source


def part1_state(n_pairs: int, blocked: bool, faster_: bool | None) -> str:
    if blocked:
        return "BLOCKED"
    if n_pairs < 100:
        return "NO DECISION"
    return "yes" if faster_ else "no"


def part2_state(failed: bool, r: float | None) -> str:
    if failed:
        return "NO DECISION"
    return "R>=3" if r >= 3 else "R<3"


def verdict(p1: str, p2: str) -> str:
    """p1 in {yes, no, NO DECISION, BLOCKED}; p2 in {R>=3, R<3, NO DECISION}."""
    if p1 == "no" and p2 == "R>=3":
        return "REOPEN"
    if p1 == "yes" or p2 == "R<3":
        return "STANDS"
    if p1 == "BLOCKED" and p2 == "NO DECISION":
        return "BLOCKED"
    return "NO DECISION"
