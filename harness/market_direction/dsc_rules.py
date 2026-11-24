"""Rules reused from the db-serial-count PREREG (§2.2 test steps and script resolution, §3.2 job matching, §3.3 step
matching, §3.4 median). The functions below are copied from that session's `harness/db_serial_count/rules.py`
(origin/claude/db-serial-count 8cda92d) so the same rules give the same answers; database and serial-flag rules are
not used here and were left out. No network: files come from ``read(path)`` (text or None).
"""
from __future__ import annotations

import configparser
import itertools
import json
import posixpath
import re
import shlex

import yaml

INSTALL_RE = re.compile(r"\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|apt(-get)?|brew|go)\s+"
                        r"(install|i|add|ci|get|mod download)\b")
RUNNER_RE = re.compile(r"\b(jest|vitest|mocha|pytest|python -m pytest|tox|nox|manage\.py test|rspec|rails test|"
                       r"bin/rails test|rake (test|spec)\b|go test|node --test|make test[\w-]*)\b")
PM_RE = re.compile(r"\b(npm|yarn|pnpm)\b( run)? (test[\w:-]*)\b")
HELP_RE = re.compile(r"\b(jest|vitest|mocha|pytest|tox|nox|rspec|rails|rake|go|node|make|npm|yarn|pnpm)\b\s+"
                     r"(\S+\s+)?--(help|version)\b")
MONOREPO_RE = re.compile(r"\b(turbo|lerna|nx)\b|\bnpm\b.*\s(-w|--workspaces?)\b|\byarn workspaces?\b|"
                         r"\bpnpm\b.*\s(-r|--recursive|--filter|-F)\b")

# ---------------------------------------------------------------------------------------------- commands

def split_commands(run: str) -> list[str]:
    """Split a shell script on newlines, &&, ||, ; and | outside quotes (backslash-newline joins lines)."""
    s = re.sub(r"\\\r?\n", " ", run or "")
    out, cur, q, i = [], [], None, 0
    while i < len(s):
        ch = s[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            elif ch == "\\" and q == '"' and i + 1 < len(s):
                cur.append(s[i + 1])
                i += 1
            i += 1
            continue
        if ch in "'\"":
            q = ch
            cur.append(ch)
            i += 1
            continue
        two = s[i:i + 2]
        if two in ("&&", "||"):
            out.append("".join(cur))
            cur = []
            i += 2
            continue
        if ch in "\n;|":
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [c.strip() for c in out if c.strip() and not c.strip().startswith("#")]


def kept_commands(run: str) -> list[str]:
    return [c for c in split_commands(run) if not INSTALL_RE.search(c) and not HELP_RE.search(c)]


def is_runner_command(cmd: str) -> bool:
    return bool(RUNNER_RE.search(cmd) or PM_RE.search(cmd))


def runner_kind(line: str) -> str | None:
    if re.search(r"manage\.py test\b", line):
        return "django"
    if re.search(r"\b(bin/rails|rails) test\b|\brake test\b", line):
        return "rails"
    if re.search(r"\brake spec\b|\brspec\b", line):
        return "rspec"
    if re.search(r"\bgo test\b", line):
        return "go"
    if re.search(r"\bnode --test\b", line):
        return "node"
    for k in ("vitest", "jest", "mocha", "pytest"):
        if re.search(rf"\b{k}\b", line):
            return k
    return None


def tokens(s: str) -> list[str]:
    try:
        return shlex.split(s, comments=False)
    except ValueError:
        return s.split()


# ---------------------------------------------------------------------------------------------- resolution

class Unresolved(Exception):
    pass


def norm(*parts: str) -> str:
    p = posixpath.normpath(posixpath.join(*[x for x in parts if x not in (None, "")])) if parts else "."
    return "" if p in (".", "/") else p.lstrip("./") if p.startswith("./") else p


def jpath(wd: str, name: str) -> str:
    p = posixpath.normpath(posixpath.join(wd or ".", name))
    return "" if p == "." else p


class Line:
    """A resolved runner line with where it came from (for the `declared` comment check)."""

    def __init__(self, text: str, src_path: str, src_text: str | None, wd: str, via: list[str]):
        self.text, self.src_path, self.src_text, self.wd, self.via = text, src_path, src_text, wd, via

    def __repr__(self):
        return f"Line({self.text!r} @ {self.src_path} via {self.via})"


def _pm_script(cmd: str):
    """(manager, script name, extra args) for `npm run X` / `npm test` / `yarn X` / `pnpm X`, else None."""
    t = tokens(cmd)
    for i, w in enumerate(t):
        base = posixpath.basename(w)
        if base in ("npm", "yarn", "pnpm"):
            rest = [x for x in t[i + 1:]]
            while rest and rest[0].startswith("-") and rest[0] not in ("--",):
                # flags before the command (e.g. --silent); a value-taking flag is not handled
                rest = rest[1:]
            if not rest:
                return None
            if rest[0] in ("run", "run-script"):
                rest = rest[1:]
                while rest and rest[0].startswith("-") and rest[0] != "--":
                    rest = rest[1:]
                if not rest:
                    return None
                name, extra = rest[0], rest[1:]
                return base, name, extra, True
            if rest[0] in ("test", "t", "tst"):
                return base, "test", rest[1:], True
            if base in ("yarn", "pnpm") and rest[0] not in ("install", "add", "exec", "dlx", "x", "why", "info",
                                                              "workspace", "workspaces", "-r", "--filter"):
                return base, rest[0], rest[1:], False
            return None
    return None


def _extra(extra: list[str], mgr: str) -> str:
    if extra and extra[0] == "--":
        extra = extra[1:]
    return " ".join(shlex.quote(x) if " " in x else x for x in extra)


def resolve_command(cmd: str, wd: str, read, src_path: str, src_text: str | None, level: int = 0,
                    via: list[str] | None = None) -> list[Line]:
    """Resolve one command to runner lines. Raises Unresolved for missing/variable-only targets and monorepo
    tools. Returns [] when the command (after resolution) runs no runner."""
    via = via or []
    if level > 3:
        raise Unresolved("more than 3 levels")
    c = cmd.strip()
    if MONOREPO_RE.search(c) and (PM_RE.search(c) or level > 0):
        raise Unresolved(f"monorepo tool: {c[:80]}")
    # package manager scripts
    pm = _pm_script(c)
    if pm and (PM_RE.search(c) or level > 0):
        mgr, name, extra, explicit_run = pm
        pj = read(jpath(wd, "package.json"))
        if pj is None:
            raise Unresolved(f"no package.json in '{wd}' for {mgr} {name}")
        try:
            scripts = (json.loads(pj).get("scripts") or {})
        except (json.JSONDecodeError, AttributeError):
            raise Unresolved("package.json not JSON")
        if name not in scripts:
            if explicit_run or not RUNNER_RE.search(f"{name}"):
                if not explicit_run and not RUNNER_RE.search(c):
                    return []
                if explicit_run:
                    raise Unresolved(f"script '{name}' not found in {jpath(wd, 'package.json')}")
            # `yarn jest ...` runs the binary
            return [Line(c, src_path, src_text, wd, via)] if RUNNER_RE.search(c) else []
        body = scripts[name] or ""
        cmds = kept_commands(body)
        if extra and cmds:
            cmds[-1] = cmds[-1] + " " + _extra(extra, mgr)
        out = []
        for sc in cmds:
            out += resolve_command(sc, wd, read, jpath(wd, "package.json"), pj, level + 1,
                                   via + [f"{mgr}:{name}"])
        return out
    m = re.search(r"\bmake\b(.*)", c) or re.search(r"\$\(MAKE\)(.*)", c)
    if m and (re.search(r"\bmake test[\w-]*\b", c) or level > 0):
        args = tokens(m.group(1))
        mdir, targets, i = wd, [], 0
        while i < len(args):
            a = args[i]
            if a == "-C" and i + 1 < len(args):
                mdir = jpath(wd, args[i + 1])
                i += 2
                continue
            if a.startswith("-") or "=" in a:
                i += 1
                continue
            targets.append(a)
            i += 1
        if not targets:
            targets = [None]
        out = []
        for t in targets:
            out += resolve_make(t, mdir, read, level + 1, via)
        return out
    if re.search(r"\btox\b", c) and not re.search(r"\b(pytest|python -m pytest)\b", c):
        return resolve_tox(c, wd, read, level + 1, via)
    if re.search(r"\bnox\b", c) and not re.search(r"\b(pytest)\b", c):
        return resolve_nox(c, wd, read, level + 1, via)
    if RUNNER_RE.search(c) and runner_kind(c):
        return [Line(c, src_path, src_text, wd, via)]
    return []


def _make_rules(text: str) -> tuple[dict, dict]:
    rules, vars_ = {}, {}
    lines = re.sub(r"\\\n", " ", text).splitlines()
    cur = None
    for ln in lines:
        if ln.startswith("\t"):
            if cur is not None:
                rules[cur]["recipe"].append(ln.strip())
            continue
        mv = re.match(r"^\s*(export\s+)?([A-Za-z_][\w.]*)\s*(\?=|:=|::=|\+=|=)\s*(.*)$", ln)
        if mv and ":" not in mv.group(2):
            vars_[mv.group(2)] = mv.group(4).strip()
            cur = None
            continue
        mr = re.match(r"^([^\s:#=][^:=]*?)\s*::?\s*([^=].*)?$", ln)
        if mr and not ln.startswith("#"):
            prereq_part = (mr.group(2) or "").split(";", 1)
            for tgt in mr.group(1).split():
                rules.setdefault(tgt, {"prereq": [], "recipe": [], "text": ln})
                rules[tgt]["prereq"] += [p for p in prereq_part[0].split() if not p.startswith("$")]
                if len(prereq_part) > 1 and prereq_part[1].strip():
                    rules[tgt]["recipe"].append(prereq_part[1].strip())
            cur = mr.group(1).split()[0]
            continue
        if ln.strip() and not ln.startswith("#"):
            cur = None
    return rules, vars_


def _subst(s: str, vars_: dict, depth: int = 0) -> str:
    if depth > 5:
        return s
    def rep(m):
        name = m.group(1) or m.group(2)
        return vars_[name] if name in vars_ else m.group(0)
    s2 = re.sub(r"\$\((\w+)\)|\$\{(\w+)\}", rep, s)
    return _subst(s2, vars_, depth + 1) if s2 != s else s2


def resolve_make(target, mdir: str, read, level: int, via: list[str]) -> list[Line]:
    if level > 3:
        raise Unresolved("make: more than 3 levels")
    path = jpath(mdir, "Makefile")
    text = read(path)
    if text is None:
        text = read(jpath(mdir, "makefile")) or read(jpath(mdir, "GNUmakefile"))
    if text is None:
        raise Unresolved(f"no Makefile in '{mdir}'")
    rules, vars_ = _make_rules(text)
    if target is None:
        target = next((t for t in rules if not t.startswith(".") and "%" not in t), None)
        if target is None:
            raise Unresolved("make: no default target")
    if target not in rules:
        raise Unresolved(f"make target '{target}' not found in {path}")
    out, var_only = [], False
    for p in rules[target]["prereq"]:
        if p in rules:
            out += resolve_make(p, mdir, read, level + 1, via + [f"make:{target}"])
    for raw in rules[target]["recipe"]:
        line = re.sub(r"^[@+-]+", "", raw)
        sub = _subst(line, vars_)
        if re.match(r"^\$[({]\w+[)}]", sub.strip()):
            var_only = True
            continue
        for sc in kept_commands(sub):
            if re.search(r"\bmake\b|\$\(MAKE\)", line) and not re.search(r"\bmake\b", sc):
                sc = re.sub(r"\$\(MAKE\)", "make", sc)
            if re.match(r"^(make\b|\$\(MAKE\))", sc.strip()):
                m = re.sub(r"^(\$\(MAKE\)|make)", "", sc.strip())
                args = tokens(m)
                tg = [a for a in args if not a.startswith("-") and "=" not in a]
                for t in tg or [None]:
                    out += resolve_make(t, mdir, read, level + 1, via + [f"make:{target}"])
                continue
            out += resolve_command(sc, mdir, read, path, text, level, via + [f"make:{target}"])
    if not out and var_only:
        raise Unresolved(f"make target '{target}': variable-only recipe")
    return out


def resolve_tox(cmd: str, wd: str, read, level: int, via: list[str]) -> list[Line]:
    path = jpath(wd, "tox.ini")
    text = read(path)
    if text is None:
        raise Unresolved(f"no tox.ini in '{wd}'")
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    try:
        cp.read_string(text)
    except configparser.Error:
        raise Unresolved("tox.ini parse error")
    t = tokens(cmd)
    envs = []
    for i, w in enumerate(t):
        if w in ("-e", "--env") and i + 1 < len(t):
            envs += t[i + 1].split(",")
        elif w.startswith("-e") and len(w) > 2 and not w.startswith("--"):
            envs += w[2:].split(",")
    secs = [f"testenv:{e}" for e in envs] if envs else ["testenv"]
    out = []
    for s in secs:
        sec = s if cp.has_section(s) else "testenv"
        if not cp.has_section(sec) or not cp.has_option(sec, "commands"):
            continue
        for ln in cp.get(sec, "commands").splitlines():
            ln = re.sub(r"^\S+:\s*", "", ln.strip()) if re.match(r"^[\w,-]+:\s", ln.strip()) else ln.strip()
            ln = ln.replace("{posargs}", "").replace("{posargs:", "")
            for sc in kept_commands(ln):
                out += resolve_command(sc, wd, read, path, text, level, via + [f"tox:{s}"])
    return out


def resolve_nox(cmd: str, wd: str, read, level: int, via: list[str]) -> list[Line]:
    path = jpath(wd, "noxfile.py")
    text = read(path)
    if text is None:
        raise Unresolved(f"no noxfile.py in '{wd}'")
    t = tokens(cmd)
    names = []
    for i, w in enumerate(t):
        if w in ("-s", "--session", "--sessions", "-e") and i + 1 < len(t):
            names += t[i + 1].split(",")
    # split noxfile into session functions
    blocks = re.split(r"\n(?=@nox\.session|@session)", "\n" + text)
    out = []
    for b in blocks:
        md = re.search(r"def\s+(\w+)\s*\(", b)
        if not md or not re.search(r"@(nox\.)?session", b):
            continue
        sname = md.group(1)
        mn = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", b.split("def", 1)[0])
        if mn:
            sname = mn.group(1)
        if names and sname not in names and md.group(1) not in names:
            continue
        for call in re.finditer(r"session\.run\((.*?)\)\s*(\n|$)", b, re.S):
            args = re.findall(r"['\"]([^'\"]*)['\"]", call.group(1).split("env=")[0])
            line = " ".join(args)
            if RUNNER_RE.search(line) and runner_kind(line):
                out.append(Line(line, path, text, wd, via + [f"nox:{sname}"]))
    return out


# ---------------------------------------------------------------------------------------------- workflows / jobs

def load_yaml(text: str):
    d = yaml.safe_load(text)
    if not isinstance(d, dict):
        raise ValueError("workflow is not a mapping")
    if True in d and "on" not in d:
        d["on"] = d.pop(True)
    return d


def triggers(wf: dict) -> set:
    on = wf.get("on")
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(map(str, on))
    if isinstance(on, dict):
        return set(map(str, on))
    return set()


def working_dir(step: dict, job: dict, wf: dict) -> str | None:
    for src in (step.get("working-directory"),
                ((job.get("defaults") or {}).get("run") or {}).get("working-directory"),
                ((wf.get("defaults") or {}).get("run") or {}).get("working-directory")):
        if src is not None:
            s = str(src)
            if "${{" in s:
                return None
            p = posixpath.normpath(s)
            return "" if p in (".", "/", "./") else p.lstrip("/").removeprefix("./")
    return ""


def merged_env(wf: dict, job: dict, step: dict) -> dict:
    env = {}
    for src in (wf.get("env"), job.get("env"), step.get("env")):
        if isinstance(src, dict):
            env.update({str(k): v for k, v in src.items()})
    return env


# ---------------------------------------------------------------------------------------------- name matching (§3)

def name_pattern(name: str) -> str:
    parts = re.split(r"\$\{\{.*?\}\}", name)
    return ".*".join(re.escape(p) for p in parts)


def strip_suffix(api_name: str) -> str | None:
    m = re.match(r"^(.*) \((.*)\)$", api_name)
    return m.group(1) if m else None


def job_matches(api_name: str, yaml_name: str, caller: str | None = None) -> bool:
    callee = name_pattern(yaml_name)
    pat = rf"^{name_pattern(caller)}( \(.*\))? / {callee}$" if caller is not None else rf"^{callee}$"
    if re.match(pat, api_name, re.S):
        return True
    s = strip_suffix(api_name)
    return s is not None and bool(re.match(pat, s, re.S))


def step_key(step: dict) -> tuple[str, str]:
    if step.get("name") is not None:
        return "name", str(step["name"])
    first = next((ln.strip() for ln in str(step.get("run") or "").splitlines() if ln.strip()), "")
    return "prefix", "Run " + first[:40]


def step_matches(api_name: str, key: tuple[str, str]) -> bool:
    kind, v = key
    if kind == "name":
        return bool(re.match(rf"^{name_pattern(v)}$", api_name or "", re.S))
    return (api_name or "").startswith(v)


def pick_api_step(api_steps: list[dict], yaml_steps: list[dict], idx: int) -> dict | None:
    """The API step for YAML step ``idx``: the j-th match, j = position of idx among YAML steps with the same key."""
    key = step_key(yaml_steps[idx])
    j = sum(1 for k in range(idx) if isinstance(yaml_steps[k], dict) and step_key(yaml_steps[k]) == key)
    matches = [s for s in sorted(api_steps, key=lambda s: s.get("number") or 0) if step_matches(s.get("name"), key)]
    return matches[j] if j < len(matches) else None


def iso(s: str):
    import datetime as dt
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def step_seconds(api_step: dict | None) -> float | None:
    if not api_step or api_step.get("conclusion") != "success":
        return None
    if not api_step.get("started_at") or not api_step.get("completed_at"):
        return None
    return (iso(api_step["completed_at"]) - iso(api_step["started_at"])).total_seconds()


def median10(values: list[float]) -> float | None:
    if len(values) < 10:
        return None
    v = sorted(values[:10])
    return (v[4] + v[5]) / 2


