"""Pure rules of the count (§2-§5): command splitting, runner steps, script resolution, serial table, database jobs,
job/step name matching, median, Wilson bound, DROP check. No network: files come from a ``read(path)`` callable
(path relative to the repository root; returns text or None when absent) and ``listdir(dir)`` (names or None).
"""
from __future__ import annotations

import configparser
import itertools
import json
import math
import posixpath
import re
import shlex

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

import yaml

# ---------------------------------------------------------------------------------------------- regexes (PREREG)

IMAGE_RE = re.compile(r"^(postgres|postgis/postgis|cimg/postgres|mysql|mariadb|mongo|pgvector/pgvector|timescale/|"
                      r"bitnami/(postgresql|mysql|mariadb|mongodb))")
COMPOSE_UP_RE = re.compile(r"docker[ -]compose .*up")
SYSTEMCTL_RE = re.compile(r"systemctl start (postgresql|mysql)|service (postgresql|mysql) start|"
                          r"/etc/init\.d/(postgresql|mysql) start")
DB_ACTIONS = ("ankane/setup-postgres", "ankane/setup-mysql", "ankane/setup-mongodb", "harmon758/postgresql-action",
              "ikalnytskyi/action-setup-postgres", "shogo82148/actions-setup-mysql",
              "supercharge/mongodb-github-action")
INSTALL_RE = re.compile(r"\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|apt(-get)?|brew|go)\s+"
                        r"(install|i|add|ci|get|mod download)\b")
RUNNER_RE = re.compile(r"\b(jest|vitest|mocha|pytest|python -m pytest|tox|nox|manage\.py test|rspec|rails test|"
                       r"bin/rails test|rake (test|spec)\b|go test|node --test|make test[\w-]*)\b")
PM_RE = re.compile(r"\b(npm|yarn|pnpm)\b( run)? (test[\w:-]*)\b")
HELP_RE = re.compile(r"\b(jest|vitest|mocha|pytest|tox|nox|rspec|rails|rake|go|node|make|npm|yarn|pnpm)\b\s+"
                     r"(\S+\s+)?--(help|version)\b")
DB_TERM_RE = re.compile(r"(?i)postgres|mysql|mariadb|mongo|postgis|pgvector|timescale")
DECLARED_RE = re.compile(r"(?i)\b(db|database|postgres|postgresql|mysql|mongo|shared|isolation|race|conflict|"
                         r"deadlock)\b")
MONOREPO_RE = re.compile(r"\b(turbo|lerna|nx)\b|\bnpm\b.*\s(-w|--workspaces?)\b|\byarn workspaces?\b|"
                         r"\bpnpm\b.*\s(-r|--recursive|--filter|-F)\b")

JEST_CMD = re.compile(r"--runInBand|(^|\s)-i(\s|$)|--maxWorkers[= ]1\b|(^|\s)-w[= ]?1\b")
JEST_CFG = re.compile(r"maxWorkers[\"']?\s*:\s*[\"']?1\b")
VITEST_CMD = re.compile(r"--no-file-parallelism|--fileParallelism[= ]false|--maxWorkers[= ]1\b|"
                        r"--poolOptions\.(threads|forks)\.single(Thread|Fork)")
VITEST_CFG = re.compile(r"fileParallelism\s*:\s*false|singleFork\s*:\s*true|singleThread\s*:\s*true|"
                        r"maxWorkers\s*:\s*1\b")
MOCHA_PAR_CMD = re.compile(r"(^|\s)(--parallel|-p)(\s|$|=)")
MOCHA_PAR_CFG = re.compile(r"\"?parallel\"?\s*:\s*true")
NODE_CMD = re.compile(r"--test-concurrency[= ]1\b")
GO_CMD = re.compile(r"(^|\s)-p[= ]1\b")
RSPEC_PAR = re.compile(r"parallel_rspec|turbo_tests|parallel_tests|knapsack")

EXPLICIT, DECLARED, DEFAULT = "explicit", "declared", "default-serial"


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


# ---------------------------------------------------------------------------------------------- serial rules

def _line_of(text: str | None, needle: str) -> int | None:
    if not text or not needle:
        return None
    for i, ln in enumerate(text.splitlines()):
        if needle in ln:
            return i
    return None


def declared(text: str | None, idx: int | None) -> bool:
    if text is None or idx is None:
        return False
    lines = text.splitlines()
    for j in range(max(0, idx - 5), min(len(lines), idx + 6)):
        if j == idx:
            continue
        s = lines[j].strip()
        if s.startswith(("#", "//", "/*", "*")) and DECLARED_RE.search(s):
            return True
    return False


def _explicit(text, needle) -> str:
    return DECLARED if declared(text, _line_of(text, needle)) else EXPLICIT


def pytest_nvalues(toks: list[str]) -> tuple[list[str], bool, bool]:
    """(-n values, has --dist, has -p no:xdist)."""
    vals, dist, noxd = [], False, False
    for i, t in enumerate(toks):
        if t == "-n" or t == "--numprocesses":
            if i + 1 < len(toks):
                vals.append(toks[i + 1])
        elif t.startswith("--numprocesses="):
            vals.append(t.split("=", 1)[1])
        elif t.startswith("-n") and not t.startswith("--") and len(t) > 2:
            vals.append(t[2:].lstrip("="))
        elif t == "--dist" or t.startswith("--dist="):
            dist = True
        elif t == "-p" and i + 1 < len(toks) and toks[i + 1] == "no:xdist":
            noxd = True
        elif t == "-pno:xdist":
            noxd = True
    return vals, dist, noxd


def pytest_addopts(wd: str, read) -> list[tuple[str, list[str], str | None]]:
    """[(file, tokens, file text)] from pytest.ini, pyproject.toml, setup.cfg, tox.ini."""
    out = []
    for name, sec in (("pytest.ini", "pytest"), ("setup.cfg", "tool:pytest"), ("tox.ini", "pytest")):
        p = jpath(wd, name)
        t = read(p)
        if t is None:
            continue
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            cp.read_string(t)
        except configparser.Error:
            continue
        if cp.has_section(sec) and cp.has_option(sec, "addopts"):
            out.append((p, tokens(cp.get(sec, "addopts").replace("\n", " ")), t))
    p = jpath(wd, "pyproject.toml")
    t = read(p)
    if t is not None and tomllib is not None:
        try:
            d = tomllib.loads(t)
            ao = (((d.get("tool") or {}).get("pytest") or {}).get("ini_options") or {}).get("addopts")
            if isinstance(ao, list):
                out.append((p, [str(x) for x in ao], t))
            elif isinstance(ao, str):
                out.append((p, tokens(ao), t))
        except Exception:
            pass
    return out


def _read_cfgs(wd: str, read, names: list[str]) -> list[tuple[str, str]]:
    out = []
    for n in names:
        p = jpath(wd, n)
        t = read(p)
        if t is not None:
            out.append((p, t))
    return out


def serial_check(line: Line, env: dict, read, listdir, wf_path: str, wf_text: str | None) -> dict:
    """Apply the §2.3 table to one resolved runner line. Returns {kind, serial, reason, evidence}."""
    txt, wd = line.text, line.wd
    kind = runner_kind(txt)
    res = {"kind": kind, "serial": False, "reason": None, "evidence": None, "line": txt, "via": line.via,
           "src": line.src_path}

    def hit(reason, ev):
        res.update(serial=True, reason=reason, evidence=ev)
        return res

    if kind == "jest":
        m = JEST_CMD.search(txt)
        if m:
            return hit(_explicit(line.src_text, m.group(0).strip()), f"command {m.group(0).strip()}")
        t = tokens(txt)
        cfg = None
        for i, w in enumerate(t):
            if w in ("--config", "-c") and i + 1 < len(t):
                cfg = t[i + 1]
            elif w.startswith("--config="):
                cfg = w.split("=", 1)[1]
        files = _read_cfgs(wd, read, [cfg]) if cfg and not cfg.startswith("{") else \
            _read_cfgs(wd, read, [f"jest.config.{e}" for e in ("js", "ts", "cjs", "mjs", "json")])
        if not cfg:
            pj = read(jpath(wd, "package.json"))
            if pj:
                try:
                    jj = json.loads(pj).get("jest")
                    if jj is not None:
                        files.append((jpath(wd, "package.json"), json.dumps(jj, indent=1)))
                except (json.JSONDecodeError, AttributeError):
                    pass
        for p, t2 in files:
            m = JEST_CFG.search(t2)
            if m:
                return hit(_explicit(t2, m.group(0)), f"{p}: {m.group(0)}")
        return res
    if kind == "vitest":
        m = VITEST_CMD.search(txt)
        if m:
            return hit(_explicit(line.src_text, m.group(0)), f"command {m.group(0)}")
        names = listdir(wd) or []
        cfgs = sorted(n for n in names if re.match(r"^(vitest|vite)\.config\.", n))
        for p, t2 in _read_cfgs(wd, read, cfgs):
            m = VITEST_CFG.search(t2)
            if m:
                return hit(_explicit(t2, m.group(0)), f"{p}: {m.group(0)}")
        return res
    if kind == "mocha":
        if MOCHA_PAR_CMD.search(txt):
            return res
        files = _read_cfgs(wd, read, [f".mocharc.{e}" for e in ("js", "cjs", "json", "yml", "yaml")])
        pj = read(jpath(wd, "package.json"))
        if pj:
            try:
                mm = json.loads(pj).get("mocha")
                if mm is not None:
                    files.append((jpath(wd, "package.json"), json.dumps(mm)))
            except (json.JSONDecodeError, AttributeError):
                pass
        for p, t2 in files:
            if MOCHA_PAR_CFG.search(t2):
                return res
        return hit(DEFAULT, "mocha without --parallel")
    if kind == "node":
        m = NODE_CMD.search(txt)
        return hit(_explicit(line.src_text, m.group(0)), f"command {m.group(0)}") if m else res
    if kind == "go":
        m = GO_CMD.search(txt)
        return hit(_explicit(line.src_text, m.group(0).strip()), f"command {m.group(0).strip()}") if m else res
    if kind == "rspec":
        return res if RSPEC_PAR.search(txt) else hit(DEFAULT, "rspec without a parallel runner")
    if kind == "rails":
        pw = env.get("PARALLEL_WORKERS")
        mline = re.search(r"\bPARALLEL_WORKERS=(\S+)", txt)
        if mline:
            pw = mline.group(1)
        if pw is not None and str(pw).strip("'\"") == "1":
            src = line.src_text if mline else wf_text
            return hit(_explicit(src, "PARALLEL_WORKERS"), "PARALLEL_WORKERS=1")
        th_path = jpath(wd, "test/test_helper.rb")
        th = read(th_path)
        par = [ln for ln in (th or "").splitlines() if "parallelize(" in ln and not ln.strip().startswith("#")]
        if not par:
            return hit(DEFAULT, "no parallelize( in test/test_helper.rb")
        for ln in par:
            if re.search(r"workers:\s*1\b", ln):
                return hit(_explicit(th, ln.strip()), f"{th_path}: {ln.strip()}")
        return res
    if kind == "django":
        t = tokens(txt)
        if "--parallel" not in t and not any(w.startswith("--parallel=") for w in t):
            return hit(DEFAULT, "manage.py test without --parallel")
        m = re.search(r"--parallel[= ]1\b", txt)
        if m:
            return hit(_explicit(line.src_text, m.group(0)), f"command {m.group(0)}")
        i = t.index("--parallel") if "--parallel" in t else None
        bare = i is not None and (i + 1 >= len(t) or t[i + 1].startswith("-") or not re.match(r"^(\d+|auto)$", t[i + 1]))
        if bare and str(env.get("DJANGO_TEST_PROCESSES", "")).strip("'\"") == "1":
            return hit(_explicit(wf_text, "DJANGO_TEST_PROCESSES"), "bare --parallel, DJANGO_TEST_PROCESSES=1")
        return res
    if kind == "pytest":
        sources = [("line", tokens(txt), line.src_text)]
        sources += pytest_addopts(wd, read)
        pa = env.get("PYTEST_ADDOPTS")
        if pa:
            sources.append(("PYTEST_ADDOPTS", tokens(str(pa)), wf_text))
        allv, dist = [], False
        for name, toks, text in sources:
            vals, d, noxd = pytest_nvalues(toks)
            if noxd:
                return hit(_explicit(text, "no:xdist"), f"{name}: -p no:xdist")
            allv += [(v, name, text) for v in vals]
            dist = dist or d
        if not allv:
            return res if dist else hit(DEFAULT, "pytest without -n")
        if all(v == "0" for v, _, _ in allv):
            v, name, text = allv[0]
            return hit(_explicit(text, "-n"), f"{name}: -n 0")
        return res
    return res


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


def matrix_values(job: dict) -> dict[str, list]:
    m = ((job.get("strategy") or {}).get("matrix")) or {}
    out: dict[str, list] = {}
    if not isinstance(m, dict):
        return out
    for k, v in m.items():
        if k in ("include", "exclude"):
            continue
        if isinstance(v, list):
            out.setdefault(k, []).extend(v)
    for inc in m.get("include") or []:
        if isinstance(inc, dict):
            for k, v in inc.items():
                out.setdefault(k, []).append(v)
    return out


def expand_matrix(s: str, mv: dict[str, list]) -> list[str]:
    names = re.findall(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", s)
    if not names:
        return [s]
    names = list(dict.fromkeys(names))
    pools = [[str(x) for x in mv.get(n, [])] or [None] for n in names]
    out = []
    for combo in itertools.product(*pools):
        x = s
        for n, v in zip(names, combo):
            if v is not None:
                x = re.sub(r"\$\{\{\s*matrix\." + re.escape(n) + r"\s*\}\}", v, x)
        out.append(x)
    return out


def image_ok(img) -> bool:
    return isinstance(img, str) and bool(IMAGE_RE.match(img.strip()))


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


def compose_db(run: str, wd: str, read) -> tuple[bool, str | None]:
    for ln in run.splitlines():
        if not COMPOSE_UP_RE.search(ln):
            continue
        t = tokens(ln)
        files = [t[i + 1] for i, w in enumerate(t) if w in ("-f", "--file") and i + 1 < len(t)]
        names = files or ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
        for n in names:
            p = jpath(wd, n)
            text = read(p)
            if text is None:
                continue
            try:
                d = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                continue
            for svc in (d.get("services") or {}).values() if isinstance(d, dict) else []:
                if isinstance(svc, dict) and image_ok(str(svc.get("image", ""))):
                    return True, f"compose {p}: {svc.get('image')}"
    return False, None


def db_job_evidence(job: dict, wf: dict, read) -> str | None:
    mv = matrix_values(job)
    for name, svc in (job.get("services") or {}).items() if isinstance(job.get("services"), dict) else []:
        img = svc.get("image") if isinstance(svc, dict) else svc
        if isinstance(img, str):
            for x in expand_matrix(img, mv):
                if image_ok(x):
                    return f"service {name}: {x}"
    for st in job.get("steps") or []:
        if not isinstance(st, dict):
            continue
        uses = str(st.get("uses") or "")
        if uses.split("@")[0].lower() in DB_ACTIONS:
            return f"uses {uses}"
        run = str(st.get("run") or "")
        if SYSTEMCTL_RE.search(run):
            return f"run {SYSTEMCTL_RE.search(run).group(0)}"
        if COMPOSE_UP_RE.search(run):
            wd = working_dir(st, job, wf)
            ok, ev = compose_db(run, wd or "", read)
            if ok:
                return ev
    return None


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


# ---------------------------------------------------------------------------------------------- §5 statistics

Z = 1.96


def wilson_upper(k: int, n: int, z: float = Z) -> float:
    if n == 0:
        return 1.0
    p = k / n
    z2 = z * z
    return (p + z2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n)


def n_upper(leaves: list[dict]) -> int:
    return sum(max(lf.get("total_count") or 0, lf.get("read") or 0) for lf in leaves if lf.get("leaf", True))


def drop_check(qualifying: int, uncertain: int, read: int, nup: int, any_incomplete: bool) -> dict:
    u = wilson_upper(qualifying + uncertain, read)
    est = u * nup
    return {"U": u, "estimate": est, "drop": read >= 300 and not any_incomplete and est < 20}


def drop_reachable(nup: int) -> int:
    return max(300, math.floor(3.8416 * nup / 20 - 3.8416) + 1)
