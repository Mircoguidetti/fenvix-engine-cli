"""Pure rules of the count (PREREG §2-§5). No network: files come from a ``Ctx`` (``read(path)`` -> text or None).

Command splitting, the install filter, ``yaml`` loading and job/step name matching are copied from db-serial-count
8150aa1 ``rules.py``; prefix stripping, the mutation table, the resolvers (npm/yarn/pnpm, make for any target, tox,
nox, composer, rake, just, task, shell scripts), Maven and Gradle matching, tool terms, frequency, durations, history
comparison and the decision rule are new here.
"""
from __future__ import annotations

import configparser
import json
import math
import posixpath
import re
import shlex
import statistics
import xml.etree.ElementTree as ET

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

import yaml

WINDOW_START = "2026-01-01"
HISTORY_START = "2024-01-01"
MAX_LEVEL = 3

# ---------------------------------------------------------------------------------------------- commands (§2.2)

INSTALL_RE = re.compile(
    r"\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|apt(-get)?|brew|go)\s+"
    r"(install|i|add|ci|get|mod download)\b"
    r"|\bcomposer\s+(require|install|update)\b|\bcargo\s+(install|binstall)\b"
    r"|\bdotnet\s+tool\s+(install|update|restore)\b|\bgo\s+install\b|\bgem\s+install\b|\bpipx\s+install\b")


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


def is_install(cmd: str) -> bool:
    return bool(INSTALL_RE.search(cmd))


def kept_commands(run: str) -> list[str]:
    return [c for c in split_commands(run) if not is_install(c)]


def tokens(s: str) -> list[str]:
    try:
        return shlex.split(s, comments=False)
    except ValueError:
        return s.split()


def jpath(wd: str, name: str) -> str:
    p = posixpath.normpath(posixpath.join(wd or ".", name))
    return "" if p == "." else p


_ASSIGN = r"[A-Za-z_][A-Za-z0-9_]*=(\"[^\"]*\"|'[^']*'|\S*)"
STRIP_RES = [
    re.compile(rf"^{_ASSIGN}\s+"),
    re.compile(r"^env(\s+-\S+)*\s+"),
    re.compile(r"^\./"),
    re.compile(r"^node_modules/\.bin/"),
    re.compile(r"^(poetry|uv|pdm|hatch|pipenv) run\s+"),
    re.compile(r"^python3? -m\s+"),
    re.compile(r"^npx( -y| --yes)?\s+"),
    re.compile(r"^npm exec( --)?\s+"),
    re.compile(r"^pnpm (exec|dlx)\s+"),
    re.compile(r"^yarn dlx\s+"),
    re.compile(r"^bunx\s+"),
    re.compile(r"^dotnet tool run\s+"),
]
YARN_BUILTINS = {"install", "add", "remove", "run", "exec", "dlx", "x", "why", "info", "workspace", "workspaces",
                 "upgrade", "up", "link", "unlink", "global", "config", "cache", "init", "create", "set", "version",
                 "publish", "pack", "audit", "outdated", "bin", "node", "npm", "plugin", "test", "start"}


def strip_prefixes(cmd: str, scripts: set | None = None) -> str:
    """Repeatedly strip the §2.2 prefixes. A bare ``yarn <x>`` is stripped only when <x> is not a package.json
    script (gate note 5)."""
    c = cmd.strip()
    while True:
        prev = c
        for rx in STRIP_RES:
            c = rx.sub("", c, count=1).strip()
        c = re.sub(r"^cargo \+\S+\s+", "cargo ", c)
        c = re.sub(r"^php \./", "php ", c)
        m = re.match(r"^yarn\s+(\S+)", c)
        if m and m.group(1) not in YARN_BUILTINS and not m.group(1).startswith("-") \
                and m.group(1) not in (scripts or set()):
            c = c[len("yarn"):].strip()
        if c == prev:
            return c


# ---------------------------------------------------------------------------------------------- mutation table (§2.3)

SIMPLE = [
    ("stryker", re.compile(r"^stryker run\b")),
    ("stryker", re.compile(r"^dotnet[- ]stryker\b")),
    ("stryker", re.compile(r"^sbt\b.*\bstryker\b")),
    ("mutmut", re.compile(r"^mutmut run\b")),
    ("cosmic-ray", re.compile(r"^cosmic-ray exec\b")),
    ("cargo-mutants", re.compile(r"^cargo[- ]mutants\b")),
    ("infection", re.compile(r"^(php )?((vendor|tools)/bin/|bin/)?infection(\.phar)?\b")),
    ("mutant", re.compile(r"^(bundle exec )?mutant run\b")),
    ("go-mutesting", re.compile(r"^go-mutesting\b")),
    ("gremlins", re.compile(r"^gremlins unleash\b")),
    ("mull", re.compile(r"^mull-runner\b")),
    ("muter", re.compile(r"^muter(\s|$)")),
    ("mutatest", re.compile(r"^mutatest\b")),
]
USES_RE = re.compile(r"(?i)stryker|mutmut|pitest|cargo-mutants|infection|mutation")
MVN_RE = re.compile(r"^mvnw?\b")
GRADLE_RE = re.compile(r"^gradlew?\b")
PIT_GOAL_RE = re.compile(r"^(pitest:(scm)?[mM]utationCoverage|org\.pitest:pitest-maven(:[\w.-]+)?:(scm)?[mM]utationCoverage)$")
PIT_TASK_RE = re.compile(r"^(:[\w-]+)*:?pitest\w*$")
GRADLE_WIRE_RE = re.compile(r"dependsOn.*pitest|finalizedBy.*pitest")
LIFECYCLE = ["validate", "initialize", "generate-sources", "process-sources", "generate-resources",
             "process-resources", "compile", "process-classes", "generate-test-sources", "process-test-sources",
             "generate-test-resources", "process-test-resources", "test-compile", "process-test-classes", "test",
             "prepare-package", "package", "pre-integration-test", "integration-test", "post-integration-test",
             "verify", "install", "deploy"]
MVN_VALUE_OPTS = {"-f", "--file", "-P", "--activate-profiles", "-pl", "--projects", "-s", "--settings", "-T",
                  "--threads", "-rf", "--resume-from", "-gs", "--global-settings", "-t", "--toolchains", "-b",
                  "--builder", "-l", "--log-file", "-e"}
GRADLE_VALUE_OPTS = {"-p", "--project-dir", "-c", "--settings-file", "-b", "--build-file", "-I", "--init-script",
                     "-g", "--gradle-user-home", "--console", "--warning-mode", "--max-workers"}


def match_simple(cmd: str) -> str | None:
    for tool, rx in SIMPLE:
        if rx.search(cmd):
            return tool
    return None


class Unresolved(Exception):
    def __init__(self, name: str, why: str):
        super().__init__(f"{name}: {why}")
        self.name, self.why = name, why


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_pom(text: str):
    try:
        return _strip_ns(ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text))
    except ET.ParseError:
        return None


def _pit_execs(plugins_el) -> list[str]:
    """Bound phases of pitest-maven executions with goal (scm)mutationCoverage under a <plugins> element."""
    out = []
    if plugins_el is None:
        return out
    for pl in plugins_el.findall("plugin"):
        if (pl.findtext("artifactId") or "").strip() != "pitest-maven":
            continue
        for ex in pl.findall("executions/execution"):
            goals = [(g.text or "").strip() for g in ex.findall("goals/goal")]
            if any(g in ("mutationCoverage", "scmMutationCoverage") for g in goals):
                out.append((ex.findtext("phase") or "verify").strip())
    return out


def _has_pit(plugins_el) -> bool:
    return plugins_el is not None and any((pl.findtext("artifactId") or "").strip() == "pitest-maven"
                                          for pl in plugins_el.findall("plugin"))


def pom_info(root, profiles: set) -> dict:
    """Executions in build/plugins (and active profiles), pluginManagement executions, modules, parent path."""
    execs, pm, pm_execs, modules = [], False, [], []
    blocks = [root] + [p for p in root.findall("profiles/profile") if (p.findtext("id") or "").strip() in profiles]
    for b in blocks:
        execs += _pit_execs(b.find("build/plugins"))
        pmp = b.find("build/pluginManagement/plugins")
        if _has_pit(pmp):
            pm = True
            pm_execs += _pit_execs(pmp) or ["verify"]
        modules += [(m.text or "").strip() for m in b.findall("modules/module") if (m.text or "").strip()]
    parent = root.find("parent")
    rel = None
    if parent is not None:
        rel = parent.findtext("relativePath")
        rel = "../pom.xml" if rel is None else rel.strip()
    return {"execs": execs, "pm": pm, "pm_execs": pm_execs, "modules": modules,
            "parent": parent is not None, "parent_rel": rel}


def match_maven(cmd: str, wd: str, ctx) -> dict | None:
    """Return {"tool": "pitest", "how": ...} when this mvn command runs PIT; None when it does not; raises
    Unresolved for pluginManagement-only or an outside parent POM (§2.3)."""
    t = tokens(cmd)[1:]
    profiles, pomfile, phases, i = set(), None, [], 0
    while i < len(t):
        a = t[i]
        if PIT_GOAL_RE.match(a):
            return {"tool": "pitest", "how": "goal", "wrapped": False}
        if a in ("-P", "--activate-profiles") and i + 1 < len(t):
            profiles |= {p.strip().lstrip("!") for p in t[i + 1].split(",")}
            i += 2
            continue
        if a.startswith("-P") and len(a) > 2:
            profiles |= {p.strip().lstrip("!") for p in a[2:].split(",")}
        elif a in ("-f", "--file") and i + 1 < len(t):
            pomfile = t[i + 1]
            i += 2
            continue
        elif a in MVN_VALUE_OPTS:
            i += 2
            continue
        elif a in LIFECYCLE:
            phases.append(LIFECYCLE.index(a))
        i += 1
    if not phases:
        return None
    top = max(phases)
    pom_path = jpath(wd, pomfile or "pom.xml")
    if pom_path.endswith("/") or not pom_path.endswith(".xml"):
        pom_path = jpath(pom_path, "pom.xml")
    text = ctx.read(pom_path)
    if text is None:
        raise Unresolved("pom.xml", f"no {pom_path}")
    root = parse_pom(text)
    if root is None:
        raise Unresolved("pom.xml", f"{pom_path} does not parse")
    info = pom_info(root, profiles)
    base = posixpath.dirname(pom_path)
    execs, pm_execs = list(info["execs"]), list(info["pm_execs"])
    seen = {pom_path}
    stack = [(base, m, 1) for m in info["modules"]]
    while stack:
        b, m, depth = stack.pop(0)
        mp = jpath(jpath(b, m), "pom.xml") if not m.endswith(".xml") else jpath(b, m)
        if mp in seen or depth > 3:
            continue
        seen.add(mp)
        mt = ctx.read(mp)
        mr = parse_pom(mt) if mt else None
        if mr is None:
            continue
        mi = pom_info(mr, profiles)
        execs += mi["execs"]
        pm_execs += mi["pm_execs"]
        stack += [(posixpath.dirname(mp), x, depth + 1) for x in mi["modules"]]
    for ph in execs:
        if ph in LIFECYCLE and top >= LIFECYCLE.index(ph):
            return {"tool": "pitest", "how": f"phase {LIFECYCLE[top]} >= {ph}", "wrapped": True}
    if any(ph in LIFECYCLE and top >= LIFECYCLE.index(ph) for ph in pm_execs):
        raise Unresolved("pitest-maven in pluginManagement", "execution only in <pluginManagement>")
    if info["parent"] and top >= LIFECYCLE.index("verify"):
        rel = info["parent_rel"]
        ppath = jpath(base, rel if rel.endswith(".xml") else jpath(rel, "pom.xml")) if rel else None
        if not ppath or ppath.startswith("..") or ctx.read(ppath) is None:
            raise Unresolved("parent POM", "parent POM outside the repository")
    return None


def match_gradle(cmd: str, wd: str, ctx) -> dict | None:
    t = tokens(cmd)[1:]
    tasks, excluded, pdir, i = [], set(), wd, 0
    while i < len(t):
        a = t[i]
        if a in ("-x", "--exclude-task") and i + 1 < len(t):
            excluded.add(t[i + 1].split(":")[-1])
            i += 2
            continue
        if a.startswith("--exclude-task="):
            excluded.add(a.split("=", 1)[1].split(":")[-1])
        elif a in ("-p", "--project-dir") and i + 1 < len(t):
            pdir = jpath(wd, t[i + 1])
            i += 2
            continue
        elif a in GRADLE_VALUE_OPTS:
            i += 2
            continue
        elif not a.startswith("-"):
            tasks.append(a)
        i += 1
    for tk in tasks:
        if PIT_TASK_RE.match(tk) and tk.split(":")[-1] not in excluded:
            return {"tool": "pitest", "how": f"task {tk}", "wrapped": False}
    if not tasks or "pitest" in excluded:
        return None
    files = [jpath(pdir, "build.gradle"), jpath(pdir, "build.gradle.kts")] + \
        [p for p in ctx.hit_files if posixpath.basename(p) in ("build.gradle", "build.gradle.kts")]
    for f in dict.fromkeys(files):
        txt = ctx.read(f)
        if txt and GRADLE_WIRE_RE.search(txt):
            raise Unresolved(f"gradle {tasks[0]} (pitest wired)", f"pitest wired in {f}")
    return None


# ---------------------------------------------------------------------------------------------- tool terms (§2.5)

TERM_RE = re.compile(r"(?i)(?<![\w-])(stryker|mutmut|cosmic-ray|pitest|mutationCoverage|cargo-mutants|cargo mutants|"
                     r"go-mutesting|gremlins|mull-runner|muter|mutatest)(?![\w-])")
INFECTION_CTX_RE = re.compile(r"(?i)\bphp\s+(\S+/)?infection\b|\b(vendor/bin|tools|bin)/infection\b|\binfection\.phar\b")
INFECTION_RE = re.compile(r"(?i)(?<![\w-])infection(?![\w-])")
MUTANT_RE = re.compile(r"(?i)(?<![\w-])mutant(?![\w])")
NAME_MUTATION_RE = re.compile(r"(?i)mutation")
YAML_ERROR_TERM_RE = re.compile(r"(?i)mutat|stryker|pitest|infection|mutmut|cosmic-ray|gremlins|muter|mull")


def has_term(text: str | None, ctx=None, *, name: bool = False, composer: bool = False) -> bool:
    """Tool term per §2.5. ``name``: the text is a script/target/job/step name (``mutation`` counts there).
    ``composer``: the text comes from a composer.json (``infection`` counts anywhere)."""
    if not text:
        return False
    if TERM_RE.search(text):
        return True
    if INFECTION_CTX_RE.search(text) or (composer and INFECTION_RE.search(text)):
        return True
    if name and NAME_MUTATION_RE.search(text):
        return True
    if MUTANT_RE.search(text) and ctx is not None and ctx.ruby_mutant():
        return True
    return False


# ---------------------------------------------------------------------------------------------- context and resolution

class Ctx:
    """Repository files for the rules: ``read(path)`` -> text or None; ``paths`` (known file paths or None when the
    tree was truncated); ``hit_files`` (discovery hit paths)."""

    def __init__(self, read, paths=None, hit_files=()):
        self._read, self.paths, self.hit_files = read, paths, list(hit_files)
        self._cache: dict = {}
        self._mutant = None

    def read(self, path: str):
        if path is None:
            return None
        p = posixpath.normpath(path)
        if p.startswith("..") or p.startswith("/") or p == ".":
            return None
        if p not in self._cache:
            self._cache[p] = self._read(p)
        return self._cache[p]

    def exists_any(self, pattern) -> list[str]:
        return sorted(p for p in (self.paths or []) if pattern(p))

    def ruby_mutant(self) -> bool:
        if self._mutant is None:
            texts = [self.read("Gemfile")]
            texts += [self.read(p) for p in self.exists_any(lambda p: "/" not in p and p.endswith(".gemspec"))]
            self._mutant = any(t and re.search(r"(?<![\w-])mutant", t) for t in texts)
        return self._mutant


class Res:
    """Accumulated result of resolving one step."""

    def __init__(self):
        self.mutations: list[dict] = []
        self.unresolved: list[dict] = []
        self.texts: list[dict] = []  # {"kind", "name", "text", "composer"} reached from the step

    def as_dict(self) -> dict:
        return {"mutations": self.mutations, "unresolved": self.unresolved,
                "reached": [{"kind": t["kind"], "name": t["name"]} for t in self.texts]}


PM_BUILTINS = {"install", "i", "ci", "add", "remove", "uninstall", "exec", "dlx", "x", "why", "info", "workspace",
               "workspaces", "upgrade", "up", "link", "unlink", "global", "config", "cache", "init", "create", "set",
               "version", "publish", "pack", "audit", "outdated", "bin", "node", "npm", "plugin", "start", "list",
               "ls", "prune", "rebuild", "dedupe", "store", "import", "fetch", "env", "help", "login", "logout"}
COMPOSER_BUILTINS = {"install", "update", "require", "remove", "dump-autoload", "dumpautoload", "validate", "show",
                     "config", "global", "diagnose", "self-update", "selfupdate", "outdated", "audit",
                     "create-project", "check-platform-reqs", "why", "depends", "why-not", "prohibits", "licenses",
                     "archive", "init", "search", "status", "fund", "bump", "reinstall", "list", "help", "clear-cache",
                     "run-script", "run", "exec"}
MONO_RE = re.compile(r"(^|\s)(-w|--workspaces?|--workspace=\S+|-r|--recursive|--filter|-F)(\s|=|$)")


class Resolver:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    # -------------------------------------------------------------- entry points
    def resolve_seq(self, cmds: list[str], wd: str, level: int, via: list[str], res: Res) -> None:
        """Resolve a list of commands, following plain ``cd <dir>`` between them."""
        cur = wd
        for c in cmds:
            m = re.match(r"^cd\s+(\S+)\s*$", c.strip())
            if m:
                d = m.group(1).strip("'\"")
                if "$" not in d and not d.startswith("/") and d != "~":
                    cur = jpath(cur, d)
                continue
            self.resolve(c, cur, level, via, res)

    def resolve(self, cmd: str, wd: str, level: int, via: list[str], res: Res) -> None:
        c = cmd.strip()
        if not c or is_install(c):
            return
        if level > MAX_LEVEL:
            res.unresolved.append({"name": _short(c), "why": f"deeper than {MAX_LEVEL} levels", "via": via})
            return
        try:
            if self._script(c, wd, level, via, res):
                return
            s = strip_prefixes(c, self._pkg_scripts(wd))
            if s != c and not is_install(s) and self._script(s, wd, level, via, res):
                return
            m = self.match(s, wd)
        except Unresolved as e:
            res.unresolved.append({"name": e.name, "why": e.why, "via": via, "cmd": _short(c)})
            return
        if m:
            res.mutations.append({"tool": m["tool"], "cmd": _short(c, 200), "via": via,
                                  "how": m.get("how"), "wrapped": bool(m.get("wrapped")) or _wrapped_via(via)})

    def match(self, s: str, wd: str) -> dict | None:
        if re.match(r"^stryker\s+(init|--version|-v)\b", s):
            return None
        tool = match_simple(s)
        if tool:
            return {"tool": tool}
        if MVN_RE.match(s):
            return match_maven(s, wd, self.ctx)
        if GRADLE_RE.match(s):
            return match_gradle(s, wd, self.ctx)
        return None

    # -------------------------------------------------------------- script kinds
    def _pkg_scripts(self, wd: str) -> set:
        pj = self.ctx.read(jpath(wd, "package.json"))
        try:
            return set((json.loads(pj).get("scripts") or {}) if pj else {})
        except (ValueError, AttributeError):
            return set()

    def _script(self, c: str, wd: str, level: int, via: list[str], res: Res) -> bool:
        t = tokens(c)
        if not t:
            return False
        head = t[0]
        base = posixpath.basename(head)
        if base in ("npm", "yarn", "pnpm", "bun"):
            return self._pm(base, t[1:], c, wd, level, via, res)
        if base == "make" or head == "$(MAKE)":
            return self._make_cmd(t[1:], wd, level, via, res)
        if base == "tox":
            return self._tox(t[1:], wd, level, via, res)
        if base == "nox":
            return self._nox(t[1:], wd, level, via, res)
        if base == "composer" or base == "composer.phar" or (base == "php" and len(t) > 1 and
                                                               posixpath.basename(t[1]) == "composer.phar"):
            rest = t[1:] if base != "php" else t[2:]
            return self._composer(rest, wd, level, via, res)
        if base == "rake" or (t[:3] == ["bundle", "exec", "rake"]):
            rest = t[1:] if base == "rake" else t[3:]
            return self._rake(rest, wd, level, via, res)
        if base == "just":
            return self._just(t[1:], wd, level, via, res)
        if base in ("task", "go-task"):
            return self._task(t[1:], wd, level, via, res)
        if base in ("bash", "sh", "zsh") or head.endswith(".sh"):
            return self._shell(t, wd, level, via, res)
        return False

    def _pm(self, mgr, rest, c, wd, level, via, res) -> bool:
        flags = [x for x in rest if x.startswith("-")]
        rest_nf = list(rest)
        while rest_nf and rest_nf[0].startswith("-") and rest_nf[0] != "--":
            rest_nf = rest_nf[1:]
        if not rest_nf:
            return False
        sub = rest_nf[0]
        if_present = "--if-present" in rest
        if sub in ("run", "run-script"):
            args = rest_nf[1:]
            while args and args[0].startswith("-") and args[0] != "--":
                args = args[1:]
            if not args:
                return False
            name, extra, explicit = args[0], args[1:], True
        elif sub in ("test", "t", "tst"):
            name, extra, explicit = "test", rest_nf[1:], True
        elif mgr in ("yarn", "pnpm", "bun") and sub not in PM_BUILTINS and not sub.startswith("-"):
            if sub not in self._pkg_scripts(wd):
                return False  # `yarn stryker run`: the binary, matched after stripping
            name, extra, explicit = sub, rest_nf[1:], False
        else:
            return False
        if MONO_RE.search(" ".join(flags)) or (mgr == "yarn" and sub in ("workspace", "workspaces")):
            res.unresolved.append({"name": name, "why": "monorepo script", "via": via, "cmd": _short(c)})
            return True
        pjp = jpath(wd, "package.json")
        pj = self.ctx.read(pjp)
        if pj is None:
            res.unresolved.append({"name": name, "why": f"no {pjp}", "via": via, "cmd": _short(c)})
            return True
        try:
            scripts = json.loads(pj).get("scripts") or {}
        except (ValueError, AttributeError):
            res.unresolved.append({"name": name, "why": f"{pjp} not JSON", "via": via, "cmd": _short(c)})
            return True
        res.texts.append({"kind": "script-name", "name": name, "text": name, "composer": False})
        if name not in scripts:
            if not if_present:
                res.unresolved.append({"name": name, "why": f"script not in {pjp}", "via": via, "cmd": _short(c)})
            return True
        body = str(scripts[name] or "")
        res.texts.append({"kind": "npm", "name": name, "text": body, "composer": False})
        cmds = kept_commands(body)
        ex = [x for x in extra if x != "--"]
        if ex and cmds:
            cmds[-1] = cmds[-1] + " " + " ".join(shlex.quote(x) for x in ex)
        self.resolve_seq(cmds, wd, level + 1, via + [f"{mgr}:{name}|{pjp}"], res)
        return True

    # make ---------------------------------------------------------------------------------
    def _make_cmd(self, args, wd, level, via, res) -> bool:
        mdir, mfile, targets, i = wd, None, [], 0
        while i < len(args):
            a = args[i]
            if a in ("-C", "--directory") and i + 1 < len(args):
                mdir = jpath(wd, args[i + 1])
                i += 2
                continue
            if a in ("-f", "--file", "--makefile") and i + 1 < len(args):
                mfile = args[i + 1]
                i += 2
                continue
            if a in ("-j", "--jobs", "-l") and i + 1 < len(args) and args[i + 1].isdigit():
                i += 2
                continue
            if a.startswith("-") or "=" in a:
                i += 1
                continue
            targets.append(a)
            i += 1
        for tg in targets or [None]:
            self._make(tg, mdir, mfile, level + 1, via, res)
        return True

    def _make(self, target, mdir, mfile, level, via, res) -> None:
        name = target or "(default)"
        if level > MAX_LEVEL:
            res.unresolved.append({"name": name, "why": f"make deeper than {MAX_LEVEL} levels", "via": via})
            return
        paths = [jpath(mdir, mfile)] if mfile else [jpath(mdir, n) for n in ("GNUmakefile", "makefile", "Makefile")]
        path, text = None, None
        for p in paths:
            text = self.ctx.read(p)
            if text is not None:
                path = p
                break
        res.texts.append({"kind": "target-name", "name": name, "text": name, "composer": False})
        if text is None:
            res.unresolved.append({"name": name, "why": f"no Makefile in '{mdir}'", "via": via})
            return
        rules_, vars_ = make_rules(text)
        if target is None:
            target = next((t for t in rules_ if not t.startswith(".") and "%" not in t), None)
            if target is None:
                res.unresolved.append({"name": name, "why": "make: no default target", "via": via})
                return
        if target not in rules_:
            res.unresolved.append({"name": target, "why": f"make target not in {path}", "via": via})
            return
        r = rules_[target]
        res.texts.append({"kind": "make", "name": target, "text": "\n".join(r["recipe"]), "composer": False})
        v2 = via + [f"make:{target}|{path}"]
        for p in r["prereq"]:
            if p in rules_:
                self._make(p, mdir, mfile, level + 1, v2, res)
        cmds = []
        for raw in r["recipe"]:
            line = _subst(re.sub(r"^[@+-]+", "", raw), vars_)
            cmds += kept_commands(line.replace("$(MAKE)", "make").replace("${MAKE}", "make"))
        cur = mdir
        for sc in cmds:
            m = re.match(r"^cd\s+(\S+)\s*$", sc)
            if m and "$" not in m.group(1):
                cur = jpath(cur, m.group(1))
                continue
            if re.match(r"^make\b", sc):
                self._make_cmd(tokens(sc)[1:], cur, level, v2, res)
                continue
            self.resolve(sc, cur, level, v2, res)

    # tox / nox ------------------------------------------------------------------------------
    def _tox(self, args, wd, level, via, res) -> bool:
        envs = []
        for i, w in enumerate(args):
            if w in ("-e", "--env") and i + 1 < len(args):
                envs += args[i + 1].split(",")
            elif w.startswith("-e") and len(w) > 2 and not w.startswith("--"):
                envs += w[2:].split(",")
        name = ",".join(envs) or "tox"
        for e in envs or [None]:
            if e:
                res.texts.append({"kind": "target-name", "name": e, "text": e, "composer": False})
        path = jpath(wd, "tox.ini")
        text = self.ctx.read(path)
        if text is None:
            res.unresolved.append({"name": name, "why": f"no {path}", "via": via})
            return True
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            cp.read_string(text)
        except configparser.Error:
            res.unresolved.append({"name": name, "why": "tox.ini parse error", "via": via})
            return True
        for e in envs or [None]:
            sec = f"testenv:{e}" if e else "testenv"
            if not cp.has_section(sec):
                if e and cp.has_section("testenv") and cp.has_option("testenv", "commands"):
                    sec = "testenv"
                else:
                    res.unresolved.append({"name": e or "testenv", "why": f"no [{sec}] in {path}", "via": via})
                    continue
            if not cp.has_option(sec, "commands"):
                continue
            body = cp.get(sec, "commands")
            res.texts.append({"kind": "tox", "name": e or "testenv", "text": body, "composer": False})
            cmds = []
            for ln in body.splitlines():
                ln = ln.strip().lstrip("-").strip()
                ln = re.sub(r"\{posargs[^}]*\}", "", ln)
                cmds += kept_commands(ln)
            self.resolve_seq(cmds, wd, level + 1, via + [f"tox:{e or 'testenv'}|{path}"], res)
        return True

    def _nox(self, args, wd, level, via, res) -> bool:
        names = []
        for i, w in enumerate(args):
            if w in ("-s", "--session", "--sessions", "-e") and i + 1 < len(args):
                names += args[i + 1].split(",")
        for n in names:
            res.texts.append({"kind": "target-name", "name": n, "text": n, "composer": False})
        path = jpath(wd, "noxfile.py")
        text = self.ctx.read(path)
        if text is None:
            res.unresolved.append({"name": ",".join(names) or "nox", "why": f"no {path}", "via": via})
            return True
        blocks = re.split(r"\n(?=@nox\.session|@session)", "\n" + text)
        found = set()
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
            found |= {sname, md.group(1)}
            res.texts.append({"kind": "nox", "name": sname, "text": b, "composer": False})
            for call in re.finditer(r"session\.run\((.*?)\)\s*(\n|$)", b, re.S):
                args_ = re.findall(r"['\"]([^'\"]*)['\"]", call.group(1).split("env=")[0])
                line = " ".join(args_)
                if line:
                    self.resolve(line, wd, level + 1, via + [f"nox:{sname}|{path}"], res)
        for n in names:
            if n not in found:
                res.unresolved.append({"name": n, "why": f"nox session not in {path}", "via": via})
        return True

    # composer -------------------------------------------------------------------------------
    def _composer(self, args, wd, level, via, res) -> bool:
        a = [x for x in args if not x.startswith("-")]
        if not a:
            return False
        if a[0] == "exec" and len(a) > 1:
            i = args.index("exec")
            self.resolve(" ".join(shlex.quote(x) for x in args[i + 1:]), wd, level, via + ["composer:exec"], res)
            return True
        explicit = a[0] in ("run-script", "run")
        if explicit:
            if len(a) < 2:
                return False
            name = a[1]
        elif a[0] in COMPOSER_BUILTINS:
            return False
        else:
            name = a[0]
        self._composer_script(name, wd, level + 1, via, res)
        return True

    def _composer_script(self, name, wd, level, via, res) -> None:
        res.texts.append({"kind": "script-name", "name": name, "text": name, "composer": True})
        if level > MAX_LEVEL:
            res.unresolved.append({"name": name, "why": f"deeper than {MAX_LEVEL} levels", "via": via})
            return
        path = jpath(wd, "composer.json")
        text = self.ctx.read(path)
        if text is None:
            res.unresolved.append({"name": name, "why": f"no {path}", "via": via})
            return
        try:
            scripts = json.loads(text).get("scripts") or {}
        except (ValueError, AttributeError):
            res.unresolved.append({"name": name, "why": f"{path} not JSON", "via": via})
            return
        if name not in scripts:
            res.unresolved.append({"name": name, "why": f"script not in {path}", "via": via})
            return
        body = scripts[name]
        lines = body if isinstance(body, list) else [body]
        res.texts.append({"kind": "composer", "name": name, "text": json.dumps(lines), "composer": True})
        v2 = via + [f"composer:{name}|{path}"]
        for ln in lines:
            ln = str(ln).strip()
            if ln.startswith("@putenv"):
                continue
            if ln.startswith("@php "):
                ln = "php " + ln[5:]
            elif ln.startswith("@composer "):
                ln = "composer " + ln[10:]
            elif ln.startswith("@"):
                self._composer_script(ln[1:].split()[0], wd, level + 1, v2, res)
                continue
            self.resolve_seq(kept_commands(ln), wd, level, v2, res)

    # rake ------------------------------------------------------------------------------------
    def _rake(self, args, wd, level, via, res) -> bool:
        names = [re.sub(r"\[.*\]$", "", x) for x in args if not x.startswith("-") and "=" not in x]
        for n in names or ["default"]:
            self._rake_task(n, wd, level + 1, via, res)
        return True

    def _rake_sources(self, wd):
        out = []
        for n in ("Rakefile", "rakefile", "Rakefile.rb"):
            t = self.ctx.read(jpath(wd, n))
            if t is not None:
                out.append((jpath(wd, n), t))
                break
        for p in self.ctx.exists_any(lambda p: p.endswith(".rake") and
                                     (posixpath.dirname(p) in (jpath(wd, "rakelib"), jpath(wd, "lib/tasks")))):
            t = self.ctx.read(p)
            if t is not None:
                out.append((p, t))
        return out

    def _rake_task(self, name, wd, level, via, res) -> None:
        res.texts.append({"kind": "target-name", "name": name, "text": name, "composer": False})
        if level > MAX_LEVEL:
            res.unresolved.append({"name": name, "why": f"deeper than {MAX_LEVEL} levels", "via": via})
            return
        srcs = self._rake_sources(wd)
        if not srcs:
            res.unresolved.append({"name": name, "why": f"no Rakefile in '{wd}'", "via": via})
            return
        last = name.split(":")[-1]
        for path, text in srcs:
            block = rake_block(text, last)
            if block is None:
                continue
            header, body, prereqs = block
            res.texts.append({"kind": "rake", "name": name, "text": header + "\n" + body, "composer": False})
            v2 = via + [f"rake:{name}|{path}"]
            for p in prereqs:
                self._rake_task(p, wd, level + 1, v2, res)
            for inv in re.findall(r"Rake::Task\[\s*['\"]([^'\"]+)['\"]\s*\]\.(?:invoke|execute)", body):
                self._rake_task(inv, wd, level + 1, v2, res)
            cmds = []
            for m in re.finditer(r"\bsh\s*\(?\s*(\"([^\"]*)\"|'([^']*)'|%[qQ]?\{([^}]*)\})", body):
                cmds += kept_commands(m.group(2) or m.group(3) or m.group(4) or "")
            for m in re.finditer(r"`([^`]*)`", body):
                cmds += kept_commands(m.group(1))
            self.resolve_seq(cmds, wd, level, v2, res)
            return
        res.unresolved.append({"name": name, "why": "rake task not found", "via": via})

    # just / task -------------------------------------------------------------------------------
    def _just(self, args, wd, level, via, res) -> bool:
        a = [x for x in args if not x.startswith("-")]
        text, path = None, None
        for n in ("justfile", "Justfile", ".justfile", "JUSTFILE"):
            text = self.ctx.read(jpath(wd, n))
            if text is not None:
                path = jpath(wd, n)
                break
        recipes = just_recipes(text) if text is not None else {}
        name = a[0] if a else (next(iter(recipes), None) if "default" not in recipes else "default")
        self._just_recipe(name or "(default)", recipes, path, wd, level + 1, via, res)
        return True

    def _just_recipe(self, name, recipes, path, wd, level, via, res):
        res.texts.append({"kind": "target-name", "name": name, "text": name, "composer": False})
        if path is None:
            res.unresolved.append({"name": name, "why": f"no justfile in '{wd}'", "via": via})
            return
        if level > MAX_LEVEL:
            res.unresolved.append({"name": name, "why": f"deeper than {MAX_LEVEL} levels", "via": via})
            return
        if name not in recipes:
            res.unresolved.append({"name": name, "why": f"recipe not in {path}", "via": via})
            return
        deps, lines = recipes[name]
        res.texts.append({"kind": "just", "name": name, "text": "\n".join(lines), "composer": False})
        v2 = via + [f"just:{name}|{path}"]
        for d in deps:
            self._just_recipe(d, recipes, path, wd, level + 1, v2, res)
        cmds = []
        for ln in lines:
            ln = re.sub(r"^[@-]+", "", ln.strip())
            if ln.startswith("#"):
                continue
            cmds += kept_commands(re.sub(r"\{\{[^}]*\}\}", "", ln))
        self.resolve_seq(cmds, wd, level, v2, res)

    def _task(self, args, wd, level, via, res) -> bool:
        a = [x for x in args if not x.startswith("-")]
        text, path = None, None
        for n in ("Taskfile.yml", "Taskfile.yaml", "taskfile.yml", "taskfile.yaml", "Taskfile.dist.yml"):
            text = self.ctx.read(jpath(wd, n))
            if text is not None:
                path = jpath(wd, n)
                break
        tasks = {}
        if text is not None:
            try:
                d = yaml.safe_load(text)
                tasks = (d or {}).get("tasks") or {} if isinstance(d, dict) else {}
            except yaml.YAMLError:
                res.unresolved.append({"name": a[0] if a else "default", "why": f"{path} parse error", "via": via})
                return True
        for n in a or ["default"]:
            self._task_one(n, tasks, path, wd, level + 1, via, res)
        return True

    def _task_one(self, name, tasks, path, wd, level, via, res):
        res.texts.append({"kind": "target-name", "name": name, "text": name, "composer": False})
        if path is None:
            res.unresolved.append({"name": name, "why": f"no Taskfile in '{wd}'", "via": via})
            return
        if level > MAX_LEVEL:
            res.unresolved.append({"name": name, "why": f"deeper than {MAX_LEVEL} levels", "via": via})
            return
        if name not in tasks:
            res.unresolved.append({"name": name, "why": f"task not in {path}", "via": via})
            return
        t = tasks[name]
        v2 = via + [f"task:{name}|{path}"]
        if isinstance(t, str):
            t = {"cmds": [t]}
        elif isinstance(t, list):
            t = {"cmds": t}
        elif not isinstance(t, dict):
            return
        res.texts.append({"kind": "task", "name": name, "text": json.dumps(t, default=str), "composer": False})
        tdir = jpath(wd, str(t["dir"])) if isinstance(t.get("dir"), str) and "{{" not in t["dir"] else wd
        for d in t.get("deps") or []:
            dn = d if isinstance(d, str) else (d.get("task") if isinstance(d, dict) else None)
            if dn:
                self._task_one(dn, tasks, path, wd, level + 1, v2, res)
        for c in t.get("cmds") or []:
            if isinstance(c, dict):
                if c.get("task"):
                    self._task_one(str(c["task"]), tasks, path, wd, level + 1, v2, res)
                    continue
                c = c.get("cmd")
            if isinstance(c, str):
                self.resolve_seq(kept_commands(re.sub(r"\{\{[^}]*\}\}", "", c)), tdir, level, v2, res)

    # shell scripts ---------------------------------------------------------------------------
    def _shell(self, t, wd, level, via, res) -> bool:
        if t[0].endswith(".sh"):
            p = t[0]
        else:
            rest = t[1:]
            while rest and rest[0].startswith("-"):
                if rest[0] in ("-c",):
                    return False  # inline script: not a file
                rest = rest[1:]
            if not rest:
                return False
            p = rest[0]
        name = p
        res.texts.append({"kind": "file-name", "name": name, "text": posixpath.basename(name), "composer": False})
        if "$" in p or p.startswith("/") or p.startswith("~"):
            res.unresolved.append({"name": name, "why": "script path is a variable or absolute", "via": via})
            return True
        path = jpath(wd, p)
        if level + 1 > MAX_LEVEL:
            res.unresolved.append({"name": name, "why": f"deeper than {MAX_LEVEL} levels", "via": via})
            return True
        text = self.ctx.read(path)
        if text is None:
            res.unresolved.append({"name": name, "why": f"no file {path}", "via": via})
            return True
        res.texts.append({"kind": "sh", "name": path, "text": text, "composer": False})
        body = "\n".join(ln for ln in re.sub(r"\\\r?\n", " ", text).splitlines() if not ln.strip().startswith("#"))
        self.resolve_seq(kept_commands(body), wd, level + 1, via + [f"sh:{path}|{path}"], res)
        return True


def _short(s: str, n: int = 120) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 3] + "..."


def via_paths(via: list[str]) -> list[str]:
    """Files a resolution chain went through (``kind:name|path`` items)."""
    return [v.split("|", 1)[1] for v in via if "|" in v]


def _wrapped_via(via: list[str]) -> bool:
    for v in via:
        kind, _, name = v.split("|")[0].partition(":")
        if kind in ("npm", "yarn", "pnpm", "bun") and name == "test":
            return True
        if kind == "make" and re.match(r"^test", name):
            return True
    return False


def make_rules(text: str) -> tuple[dict, dict]:
    """Makefile rules {target: {prereq, recipe}} and simple variables (db-serial-count ``_make_rules``)."""
    rules_, vars_ = {}, {}
    cur = None
    for ln in re.sub(r"\\\n", " ", text).splitlines():
        if ln.startswith("\t"):
            if cur is not None:
                for c in cur:
                    rules_[c]["recipe"].append(ln.strip())
            continue
        mv = re.match(r"^\s*(export\s+)?([A-Za-z_][\w.]*)\s*(\?=|:=|::=|\+=|=)\s*(.*)$", ln)
        if mv and ":" not in mv.group(2):
            vars_[mv.group(2)] = mv.group(4).strip()
            cur = None
            continue
        mr = re.match(r"^([^\s:#=][^:=]*?)\s*::?\s*([^=].*)?$", ln)
        if mr and not ln.startswith("#"):
            prereq_part = (mr.group(2) or "").split(";", 1)
            tg = mr.group(1).split()
            for t in tg:
                rules_.setdefault(t, {"prereq": [], "recipe": []})
                rules_[t]["prereq"] += [p for p in prereq_part[0].split() if not p.startswith("$")]
                if len(prereq_part) > 1 and prereq_part[1].strip():
                    rules_[t]["recipe"].append(prereq_part[1].strip())
            cur = [t for t in tg if t != ".PHONY"] or None
            if tg and tg[0] == ".PHONY":
                cur = None
            continue
        if ln.strip() and not ln.startswith("#"):
            cur = None
    return rules_, vars_


def _subst(s: str, vars_: dict, depth: int = 0) -> str:
    if depth > 5:
        return s
    s2 = re.sub(r"\$\((\w+)\)|\$\{(\w+)\}",
                lambda m: vars_.get(m.group(1) or m.group(2), m.group(0)) if (m.group(1) or m.group(2)) != "MAKE"
                else m.group(0), s)
    return _subst(s2, vars_, depth + 1) if s2 != s else s2


def rake_block(text: str, name: str):
    """(header line, body, prerequisites) of ``task name`` in a Rakefile, or None."""
    lines = text.splitlines()
    nm = re.escape(name)
    hdr = re.compile(rf"^(\s*)task\s*\(?\s*(:{nm}\b|['\"]{nm}['\"]|{nm}:(?=\s|$))(.*)$")
    for i, ln in enumerate(lines):
        m = hdr.match(ln)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(3)
        prereqs = re.findall(r":(\w+)", re.split(r"\bdo\b|\{", rest)[0])
        prereqs += re.findall(r"['\"](\w[\w:]*)['\"]", re.split(r"\bdo\b|\{", rest)[0])
        if m.group(2).endswith(":") and not m.group(2).startswith(":"):
            pass
        body = []
        if re.search(r"\bdo\b|\{", rest):
            for ln2 in lines[i + 1:]:
                ind2 = len(ln2) - len(ln2.lstrip())
                if ln2.strip() in ("end", "}") and ind2 <= indent:
                    break
                body.append(ln2)
            m2 = re.search(r"\{(.*)\}\s*$", rest)
            if m2:
                body = [m2.group(1)]
        return ln, "\n".join(body), [p for p in prereqs if p != name]
    return None


def just_recipes(text: str) -> dict:
    """{name: (dependencies, body lines)} of a justfile (recipe header at column 0, indented body)."""
    out, cur = {}, None
    for ln in text.splitlines():
        if ln.strip().startswith("#") and not ln.startswith((" ", "\t")):
            continue
        if ln and not ln[0].isspace():
            cur = None
            m = re.match(r"^@?([A-Za-z_][\w-]*)\b([^:=]*?):(?!=)\s*(.*)$", ln)
            if m and not re.match(r"^(set|export|alias|import|mod)\b", ln):
                deps = re.findall(r"\(?([A-Za-z_][\w-]*)", m.group(3).split("#")[0])
                cur = m.group(1)
                out[cur] = (deps, [])
            continue
        if cur is not None and ln.strip():
            out[cur][1].append(ln.strip())
    return out


# ---------------------------------------------------------------------------------------------- workflows

def load_yaml(text: str):
    d = yaml.safe_load(text)
    if not isinstance(d, dict):
        raise ValueError("workflow is not a mapping")
    if True in d and "on" not in d:
        d["on"] = d.pop(True)
    return d


class OnError(Exception):
    pass


def events(wf: dict) -> set:
    """Events of a workflow; ``push`` is split into ``push`` (branches) and ``push-tags`` (tags-only filter)."""
    on = wf.get("on")
    if isinstance(on, str):
        ev = {on: None}
    elif isinstance(on, list):
        if not all(isinstance(x, str) for x in on):
            raise OnError("on: list with non-strings")
        ev = {x: None for x in on}
    elif isinstance(on, dict):
        ev = {str(k): v for k, v in on.items()}
    else:
        raise OnError(f"on: {type(on).__name__}")
    out = set()
    for k, v in ev.items():
        if k == "push" and isinstance(v, dict):
            keys = set(v)
            if keys & {"tags", "tags-ignore"} and not keys & {"branches", "branches-ignore"}:
                out.add("push-tags")
                continue
        out.add(k)
    return out


EVERY = {"pull_request", "pull_request_target", "merge_group", "push"}
MANUAL = {"workflow_dispatch", "release", "push-tags"}


def frequency(evs: set) -> str:
    if evs & EVERY:
        return "every-change"
    if "schedule" in evs:
        return "scheduled"
    if evs & MANUAL:
        return "manual"
    return "other"


_IF_TOKEN = re.compile(r"\s*(\(|\)|&&|\|\||==|!=|github\.event_name|'[^']*'|\"[^\"]*\")")


def if_filter(expr, evs: set) -> tuple[set, bool]:
    """Filter events by a job-level ``if:`` made only of github.event_name ==/!= literal, ||, && and parentheses.
    Returns (events, complex_flag). Any other ``if:`` is ignored (events unchanged) and flagged."""
    if expr is None:
        return evs, False
    if isinstance(expr, bool):
        return (evs if expr else set()), False
    s = str(expr).strip()
    m = re.fullmatch(r"\$\{\{(.*)\}\}", s, re.S)
    if m:
        s = m.group(1).strip()
    toks, pos = [], 0
    while pos < len(s):
        mm = _IF_TOKEN.match(s, pos)
        if not mm:
            if s[pos:].strip() == "":
                break
            return evs, True
        toks.append(mm.group(1))
        pos = mm.end()
    if not toks:
        return evs, True

    def ev_name(e):
        return "push" if e == "push-tags" else e

    def parse(i):
        v, i = parse_and(i)
        while i < len(toks) and toks[i] == "||":
            v2, i = parse_and(i + 1)
            v = (lambda a, b: lambda e: a(e) or b(e))(v, v2)
        return v, i

    def parse_and(i):
        v, i = parse_atom(i)
        while i < len(toks) and toks[i] == "&&":
            v2, i = parse_atom(i + 1)
            v = (lambda a, b: lambda e: a(e) and b(e))(v, v2)
        return v, i

    def parse_atom(i):
        if i < len(toks) and toks[i] == "(":
            v, i = parse(i + 1)
            if i >= len(toks) or toks[i] != ")":
                raise ValueError("paren")
            return v, i + 1
        if i + 2 < len(toks) + 0 and toks[i + 1] in ("==", "!="):
            a, op, b = toks[i], toks[i + 1], toks[i + 2]
            if a == "github.event_name" and b[0] in "'\"":
                lit = b[1:-1]
            elif b == "github.event_name" and a[0] in "'\"":
                lit = a[1:-1]
            else:
                raise ValueError("atom")
            if op == "==":
                return (lambda e: ev_name(e) == lit), i + 3
            return (lambda e: ev_name(e) != lit), i + 3
        raise ValueError("atom")

    try:
        f, i = parse(0)
        if i != len(toks):
            raise ValueError("trailing")
    except (ValueError, IndexError):
        return evs, True
    return {e for e in evs if f(e)}, False


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


def timeout_of(step: dict, job: dict):
    """Timeout minutes: the step's timeout-minutes, else the job's, else 360; an expression -> None (unknown)."""
    for v in (step.get("timeout-minutes"), job.get("timeout-minutes")):
        if v is not None:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            s = str(v).strip()
            if re.fullmatch(r"\d+(\.\d+)?", s):
                return float(s)
            return None
    return 360.0


def analyze_job(job: dict, wf: dict, ctx: Ctx, resolver: Resolver | None = None) -> dict:
    """Mutation steps, unresolved items and tool-term hits of one workflow job (§2.3-§2.6)."""
    resolver = resolver or Resolver(ctx)
    steps = job.get("steps") if isinstance(job.get("steps"), list) else []
    out = {"mutation_steps": [], "unresolved": [], "term_hits": [], "uses_actions": []}
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            continue
        sname = str(st.get("name") or "")
        wd = working_dir(st, job, wf)
        wd0 = wd if wd is not None else ""
        res = Res()
        uses = st.get("uses")
        if isinstance(uses, str):
            if USES_RE.search(uses.split("@")[0]):
                out["mutation_steps"].append({"index": i, "name": sname, "kind": "uses-action", "uses": uses,
                                              "mutations": [{"tool": "uses-action", "cmd": uses, "via": []}],
                                              "timeout": timeout_of(st, job), "wrapped": False})
                out["uses_actions"].append(uses)
                continue
            if uses.startswith("./"):
                _composite(uses, ctx, resolver, res)
        if st.get("run") is not None:
            resolver.resolve_seq(kept_commands(str(st["run"])), wd0, 0, [], res)
        if res.mutations:
            out["mutation_steps"].append({"index": i, "name": sname, "kind": "run", "mutations": res.mutations,
                                          "timeout": timeout_of(st, job),
                                          "wrapped": any(m.get("wrapped") for m in res.mutations)})
        for u in res.unresolved:
            out["unresolved"].append({**u, "step": i, "step_name": sname})
        for t in res.texts:
            if has_term(t["text"], ctx, name=t["kind"].endswith("-name"), composer=t["composer"]):
                out["term_hits"].append({"step": i, "kind": t["kind"], "name": t["name"]})
    return out


def _composite(uses: str, ctx: Ctx, resolver: Resolver, res: Res) -> None:
    """Local composite action: its ``runs.steps[].run`` are resolved as part of the calling step."""
    d = uses[2:].split("@")[0].rstrip("/")
    for n in ("action.yml", "action.yaml"):
        text = ctx.read(jpath(d, n))
        if text is None:
            continue
        res.texts.append({"kind": "action", "name": jpath(d, n), "text": text, "composer": False})
        try:
            a = yaml.safe_load(text)
        except yaml.YAMLError:
            res.unresolved.append({"name": jpath(d, n), "why": "action does not parse", "via": []})
            return
        steps = (((a or {}).get("runs") or {}).get("steps") or []) if isinstance(a, dict) else []
        for st in steps if isinstance(steps, list) else []:
            if isinstance(st, dict) and st.get("run") is not None:
                wd = str(st.get("working-directory") or "")
                resolver.resolve_seq(kept_commands(str(st["run"])), "" if "${{" in wd else wd.strip("./"), 1,
                                     [f"action:{d}|{jpath(d, n)}"], res)
        return


# ---------------------------------------------------------------------------------------------- name matching (§2.8)

def name_pattern(name: str) -> str:
    parts = re.split(r"\$\{\{.*?\}\}", name)
    return ".*".join(re.escape(p) for p in parts)


def strip_suffix(api_name: str) -> str | None:
    m = re.match(r"^(.*) \((.*)\)$", api_name)
    return m.group(1) if m else None


def job_matches(api_name: str, yaml_name: str, caller: str | None = None) -> bool:
    callee = name_pattern(yaml_name)
    pat = rf"^{name_pattern(caller)}( \(.*\))? / {callee}$" if caller is not None else rf"^{callee}$"
    if re.match(pat, api_name or "", re.S):
        return True
    s = strip_suffix(api_name or "")
    return s is not None and bool(re.match(pat, s, re.S))


def step_key(step: dict) -> tuple[str, str]:
    if step.get("name") is not None:
        return "name", str(step["name"])
    if step.get("uses") is not None:
        return "prefix", "Run " + str(step["uses"])[:40]
    first = next((ln.strip() for ln in str(step.get("run") or "").splitlines() if ln.strip()), "")
    return "prefix", "Run " + first[:40]


def step_matches(api_name: str, key: tuple[str, str]) -> bool:
    kind, v = key
    if kind == "name":
        return bool(re.match(rf"^{name_pattern(v)}$", api_name or "", re.S))
    return (api_name or "").startswith(v)


def pick_api_step(api_steps: list[dict], yaml_steps: list, idx: int) -> dict | None:
    """The API step for YAML step ``idx``: the j-th match, j = position of idx among YAML steps with the same key."""
    key = step_key(yaml_steps[idx])
    j = sum(1 for k in range(idx) if isinstance(yaml_steps[k], dict) and step_key(yaml_steps[k]) == key)
    matches = [s for s in sorted(api_steps, key=lambda s: s.get("number") or 0) if step_matches(s.get("name"), key)]
    return matches[j] if j < len(matches) else None


# ---------------------------------------------------------------------------------------------- durations (§3)

def iso(s: str):
    import datetime as dt
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def seconds(a: dict | None) -> float | None:
    if not a or not a.get("started_at") or not a.get("completed_at"):
        return None
    return (iso(a["completed_at"]) - iso(a["started_at"])).total_seconds()


def leg_eval(leg: dict, mut_api_steps: list, timeout_min) -> dict:
    """Evaluate one job leg (§2.8, §3). ``mut_api_steps``: the API steps of the job's mutation steps (None when not
    found). Returns {"evidence": bool, "value_s": float|None, "lower_bound": bool, "step_s": float}."""
    found = [s for s in mut_api_steps if s is not None]
    step_ok = bool(found) and any(s.get("conclusion") not in ("skipped", None) for s in found)
    concl = leg.get("conclusion")
    wall = seconds(leg)
    step_s = sum(x for x in (seconds(s) for s in found if s.get("conclusion") != "skipped") if x)
    out = {"evidence": False, "value_s": None, "lower_bound": False, "step_s": step_s, "conclusion": concl}
    if not step_ok or wall is None:
        return out
    at_timeout = timeout_min is not None and wall >= timeout_min * 60 - 60
    if concl in ("success", "failure"):
        out["evidence"] = True
        out["value_s"] = wall
        out["lower_bound"] = concl == "failure" and at_timeout
    elif concl == "cancelled" and at_timeout:
        out["value_s"] = wall
        out["lower_bound"] = True
    return out


def median_upto10(values: list[float]):
    """Median over up to 10 run values (mean of the two middle values when even); None when fewer than 3."""
    v = list(values[:10])
    if len(v) < 3:
        return None
    return float(statistics.median(v))


# ---------------------------------------------------------------------------------------------- history (§4)

NARROW_RE = re.compile(r"--incremental\b|incremental\s*:\s*true|--since\b|--in-diff\b|--git-diff-filter\b|"
                       r"--git-diff-lines\b|--git-diff-base\b|scmMutationCoverage|\+GIT\b|withHistory|historyInputFile|"
                       r"--(mutate|paths-to-mutate|file)[= ]+[\"']?(\$\(|`)\s*git diff")
LIMIT_RE = re.compile(r"(?i)(--shard|maxMutationsPerClass|max[_-]?mutants|mutation[_-]?limit|--sample)"
                      r"[\"']?\s*[=:]?\s*[\"']?(\d+)?")
IF_FALSE_RE = re.compile(r"(?i)^\s*(\$\{\{\s*)?false(\s*\}\})?\s*$")
TRIGGER_LINE_RE = re.compile(r"^\s*(on|push|pull_request|pull_request_target|merge_group|schedule|workflow_dispatch|"
                             r"branches|tags|cron|if)\s*:|^\s*-?\s*cron\s*:|^\s*on\s*:")
REASON_RE = re.compile(r"(?i)\b(slow\w*|speed( ?up)?|speeds?|faster|too long|takes?|took|time ?outs?|timed out|"
                       r"minutes?|mins?|hours?|hrs?|performance|expensive|costs?|costly|budget|billing|quota|"
                       r"ci (time|minutes)|resources?|heavy|save time|reduce time)\b")
ANY_MUT_RE = re.compile(r"stryker run|dotnet[- ]stryker|mutmut run|cosmic-ray exec|cargo[- ]mutants|"
                        r"(vendor|tools)/bin/infection|bin/infection|infection\.phar|mutant run|pitest|"
                        r"mutationCoverage|go-mutesting|gremlins unleash|mull-runner|\bmuter\b|mutatest")
CONFIG_BASENAMES = re.compile(r"^(stryker\.conf.*|stryker\.config.*|stryker-config\.json|infection\.json.*|"
                              r"cosmic-ray\.toml|\.mutant\.yml)$")


def is_config_path(p: str) -> bool:
    b = posixpath.basename(p)
    return bool(CONFIG_BASENAMES.match(b)) or p.endswith(".cargo/mutants.toml") or p.endswith("config/mutant.yml")


def reason_match(*texts) -> list[str]:
    return sorted({m.group(0).lower() for t in texts if t for m in REASON_RE.finditer(t)})


def patch_lines(patch: str | None) -> tuple[list[str], list[str]]:
    plus, minus = [], []
    for ln in (patch or "").splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            plus.append(ln[1:])
        elif ln.startswith("-"):
            minus.append(ln[1:])
    return plus, minus


def patch_touches(patch: str | None, workflow: bool) -> bool:
    if patch is None:
        return True
    plus, minus = patch_lines(patch)
    for ln in plus + minus:
        if has_term(ln, name=True) or NARROW_RE.search(ln) or LIMIT_RE.search(ln) or ANY_MUT_RE.search(ln):
            return True
        if workflow and TRIGGER_LINE_RE.search(ln):
            return True
    return False


def direct_mutation(cmd: str) -> str | None:
    """History-only mutation-step test (no repository files): a §2.3 command after stripping, an explicit PIT goal or
    Gradle pitest task, or a script/target/task invocation whose name contains a tool term."""
    s = strip_prefixes(cmd)
    t = match_simple(s)
    if t:
        return t
    tk = tokens(s)
    if MVN_RE.match(s) and any(PIT_GOAL_RE.match(x) for x in tk):
        return "pitest"
    if GRADLE_RE.match(s) and any(PIT_TASK_RE.match(x) for x in tk[1:]) and "-x" not in tk:
        return "pitest"
    if tk and posixpath.basename(tk[0]) in ("npm", "yarn", "pnpm", "make", "composer", "rake", "just", "task", "tox",
                                            "nox", "bun") and any(has_term(x, name=True) for x in tk[1:]):
        return "script:" + next(x for x in tk[1:] if has_term(x, name=True))
    if tk and (tk[0].endswith(".sh") or (tk[0] in ("bash", "sh") and len(tk) > 1)) and has_term(" ".join(tk), name=True):
        return "script:" + tk[-1]
    return None


def limits_of(text: str) -> dict:
    out = {}
    for m in LIMIT_RE.finditer(text or ""):
        k = m.group(1).lower().replace("_", "-")
        v = int(m.group(2)) if m.group(2) else None
        out[k] = v if k not in out or out[k] is None else (min(out[k], v) if v is not None else out[k])
    return out


def history_jobs(wf: dict | None) -> dict:
    """{job key: {freq, events, tools, flags, limits, if_false}} for mutation jobs of a workflow (history view)."""
    if not wf:
        return {}
    try:
        evs = events(wf)
    except OnError:
        evs = set()
    out = {}
    jobs = wf.get("jobs") if isinstance(wf.get("jobs"), dict) else {}
    for jk, job in jobs.items():
        if not isinstance(job, dict):
            continue
        tools, if_false = [], IF_FALSE_RE.match(str(job.get("if"))) is not None if "if" in job else False
        steps = job.get("steps") if isinstance(job.get("steps"), list) else []
        active_steps = 0
        for st in steps:
            if not isinstance(st, dict):
                continue
            hit = None
            if isinstance(st.get("uses"), str) and USES_RE.search(st["uses"].split("@")[0]):
                hit = "uses-action"
            elif st.get("run") is not None:
                for c in kept_commands(str(st["run"])):
                    hit = hit or direct_mutation(c)
            if hit:
                tools.append(hit)
                if not ("if" in st and IF_FALSE_RE.match(str(st.get("if")))):
                    active_steps += 1
        if not tools:
            continue
        jevs, _ = if_filter(job.get("if"), evs)
        text = json.dumps(job, default=str)
        out[str(jk)] = {"freq": frequency(jevs), "events": sorted(jevs), "tools": sorted(set(tools)),
                        "flags": sorted({m.group(0) for m in NARROW_RE.finditer(text)}), "limits": limits_of(text),
                        "if_false": if_false or active_steps == 0}
    return out


def compare_workflow(parent: dict | None, commit: dict | None) -> dict:
    """Kinds of narrowing change between two parsed versions of one workflow file (§4.1), plus the removed and added
    mutation commands for the cross-file check."""
    pj, cj = history_jobs(parent), history_jobs(commit)
    kinds, removed, added = set(), [], []
    for k, p in pj.items():
        c = cj.get(k)
        if c is None:
            removed.append({"job": k, "freq": p["freq"], "tools": p["tools"]})
            continue
        if c["if_false"] and not p["if_false"]:
            kinds.add("disabled")
        if p["freq"] == "every-change" and c["freq"] != "every-change" and not c["if_false"]:
            kinds.add("moved-off-change")
        if set(c["flags"]) - set(p["flags"]):
            kinds.add("narrowed")
        for lk, lv in c["limits"].items():
            if lk not in p["limits"] or (lv is not None and p["limits"][lk] is not None and lv < p["limits"][lk]):
                kinds.add("cut")
    for k, c in cj.items():
        if k not in pj:
            added.append({"job": k, "freq": c["freq"], "tools": c["tools"]})
    return {"kinds": sorted(kinds), "removed": removed, "added": added}


def _list_len(text: str | None, path: str):
    if text is None:
        return None
    b = posixpath.basename(path)
    try:
        if b.endswith(".json") or b.endswith(".dist") or b.endswith(".json5"):
            d = json.loads(text)
        elif b.endswith(".toml") and tomllib:
            d = tomllib.loads(text)
        elif b.endswith((".yml", ".yaml")):
            d = yaml.safe_load(text)
        else:
            m = re.search(r"\b(mutate|mutators)\s*:\s*\[([^\]]*)\]", text, re.S)
            return len(re.findall(r"['\"][^'\"]+['\"]", m.group(2))) if m else None
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    for k in ("mutate", "mutators"):
        v = d.get(k)
        if isinstance(v, (list, dict)):
            return len(v)
    return None


def compare_patch(patch: str | None, path: str, parent_text: str | None = None,
                  commit_text: str | None = None, script: bool = False) -> list[str]:
    """Kinds for a non-YAML tool config or a script file from its patch lines (gate note 7)."""
    plus, minus = patch_lines(patch)
    kinds = set()
    pn = {m.group(0) for ln in plus for m in NARROW_RE.finditer(ln)}
    mn = {m.group(0) for ln in minus for m in NARROW_RE.finditer(ln)}
    if pn - mn:
        kinds.add("narrowed")
    pl, ml = limits_of("\n".join(plus)), limits_of("\n".join(minus))
    for k, v in pl.items():
        if k not in ml or (v is not None and ml[k] is not None and v < ml[k]):
            kinds.add("cut")
    a, b = _list_len(parent_text, path), _list_len(commit_text, path)
    if a is not None and b is not None and b < a:
        kinds.add("cut")
    if script and any(ANY_MUT_RE.search(ln) for ln in minus) and not any(ANY_MUT_RE.search(ln) for ln in plus):
        kinds.add("disabled")
    return sorted(kinds)


# ---------------------------------------------------------------------------------------------- §4.5 pain, §5 decision

def pain_of(row: dict, handreads: dict) -> tuple[str, list[str]]:
    """Pain of a running row: ("yes"|"unknown"|"no", reasons). ``handreads``: {candidate id: verdict record}."""
    reasons = []
    dur = row.get("duration") or {}
    if dur.get("pain"):
        return "yes", ["duration"]
    hist = row.get("history") or {}
    cands = list(hist.get("candidates") or []) + list((row.get("issues") or {}).get("candidates") or [])
    for c in cands:
        h = handreads.get((row["repo"].lower(), c["id"]))
        if h and h.get("verdict") == "confirmed" and (c.get("date") or "") >= HISTORY_START:
            return "yes", [f"confirmed {c['id']}"]
    if dur.get("too_few_runs"):
        reasons.append("too_few_runs")
    if dur.get("runs_cap_few"):
        reasons.append("runs cap with < 3 values")
    if hist.get("errors") or (row.get("issues") or {}).get("errors"):
        reasons.append("history-error")
    if hist.get("capped") or (row.get("issues") or {}).get("capped"):
        reasons.append("300-request cap")
    if not hist.get("done") and not dur.get("pain"):
        reasons.append("history not run")
    if not (row.get("issues") or {}).get("done"):
        reasons.append("issues search not run")
    if any((row["repo"].lower(), c["id"]) not in handreads for c in cands):
        reasons.append("candidate not hand-read")
    return ("unknown" if reasons else "no"), reasons


Z = 1.96


def wilson_upper(k: int, n: int, z: float = Z) -> float:
    if n == 0:
        return 1.0
    p = k / n
    z2 = z * z
    return (p + z2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n)


def drop_reachable(n: int) -> int:
    return max(300, math.floor(3.8416 * n / 20 - 3.8416) + 1)


def decide(c: dict) -> dict:
    """§5. ``c``: running, pain_yes, pain_unknown, uncertain, read, N, all_read, any_truncated, any_incomplete,
    handcheck_ok, budget_over (discovery > 24 h or reading budget ended)."""
    r = c["read"]
    ur = wilson_upper(c["running"] + c["uncertain"], r)
    up = wilson_upper(c["pain_yes"] + c["pain_unknown"] + c["uncertain"], r)
    out = {"U_R": ur, "U_P": up, "U_R_N": ur * c["N"], "U_P_N": up * c["N"]}
    if c["running"] >= 100 and c["pain_yes"] >= 20:
        out["kind"] = "CONTINUE" if c.get("handcheck_ok") else "CONTINUE-pending-handcheck"
        out["line"] = f"CONTINUE: {c['running']} running, {c['pain_yes']} with time pain."
        return out
    a_ok = c["all_read"] and not c["any_truncated"] and not c["any_incomplete"]
    x = c["running"] + c["uncertain"]
    y = c["pain_yes"] + c["pain_unknown"] + c["uncertain"]
    if a_ok and (x < 100 or y < 20):
        out["kind"] = "DROP"
        out["line"] = f"DROP: whole frame read; running+uncertain {x}, pain yes+unknown+uncertain {y}."
        return out
    if r >= 300 and not c["any_incomplete"] and (out["U_R_N"] < 100 or out["U_P_N"] < 20):
        out["kind"] = "DROP"
        out["line"] = (f"DROP: estimates U_R×N {out['U_R_N']:.1f}, U_P×N {out['U_P_N']:.1f} after {r} read.")
        return out
    if c.get("budget_over"):
        out["kind"] = "NO DECISION"
        out["line"] = (f"NO DECISION: budget reached; read {r}, running {c['running']}, pain yes {c['pain_yes']}, "
                       f"pain unknown {c['pain_unknown']}, uncertain {c['uncertain']}, U_R×N {out['U_R_N']:.1f}, "
                       f"U_P×N {out['U_P_N']:.1f}.")
        return out
    out["kind"] = "KEEP READING"
    out["line"] = (f"KEEP READING: read {r}, running {c['running']}, pain yes {c['pain_yes']}, U_R×N "
                   f"{out['U_R_N']:.1f}, U_P×N {out['U_P_N']:.1f}.")
    return out
