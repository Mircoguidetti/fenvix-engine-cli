"""Pure rules of the agent-determinism count (PREREG.md). No network, no clock.

Copied (not imported) from db-serial-count 8150aa1 ``rules.py``: ``split_commands``, ``INSTALL_RE``, ``RUNNER_RE``
(extended here), ``PM_RE``, ``tokens``, ``jpath``, ``_pm_script``, the make-rule parser, ``load_yaml`` (PyYAML ``on:``
-> ``True``), ``triggers``, ``job_matches``, ``step_key``, ``step_matches``, ``pick_api_step``, ``wilson_upper``.
Copied from test-quality-count 432d4b0 ``rules.py``: ``STRIP_RES`` / ``strip_prefixes``. Everything else is new.
"""
from __future__ import annotations

import configparser
import json
import math
import posixpath
import random
import re
import shlex

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

import yaml

# ---------------------------------------------------------------------------------------------- constants (PREREG)

WINDOW_START = "2026-01-01"
HISTORY_START = "2024-01-01"
THRESHOLD = 50
QUERY_CAP = 20000
TEXT_CAP = 40
REQUEST_CAP = 300
RECORDING_FILE_CAP = 200
MANIFEST_CAP = 100
BLOB_TEXT_MAX = 2_000_000
RECORDING_MAX = 5_000_000
RUNS_CAP = 20
COMMENT_CAP = 40
TEXT_SEARCH_CAP = 100
STRATUM_FIRST = 300
CHUNK_SIZE = 150
SIZE_MAX = 400000
HARD_STOP = "2026-12-14T12:00:00Z"
READ_BUDGET_H = None  # withdrawn by the founder's "lettura A" (2026-11-26 19:01Z, CHANGES.md item 21)
DISCOVERY_BUDGET_H = 24.0
PREPASS_MAX_H = 20.0
CODE_PER_MIN = 9
TEXT_PER_MIN = 25
Z = 1.96
Z2 = 3.8416

HOSTS = ["api.openai.com", "openai.azure.com", "api.anthropic.com", "generativelanguage.googleapis.com",
         "aiplatform.googleapis.com", "bedrock-runtime.", "api.mistral.ai", "api.groq.com", "api.cohere.com",
         "api.cohere.ai", "api.together.xyz", "api.fireworks.ai", "openrouter.ai/api", "api.deepseek.com",
         "api.x.ai", "api.perplexity.ai", "cognitiveservices.azure.com"]

PY_EXACT = {"langchain", "langgraph", "crewai", "crewai-tools", "pyautogen", "autogen-agentchat", "autogen-core",
            "autogen-ext", "ag2", "llama-index", "openai-agents", "pydantic-ai", "pydantic-ai-slim", "smolagents",
            "agno", "phidata", "google-adk", "semantic-kernel", "claude-agent-sdk", "strands-agents", "haystack-ai",
            "dspy", "dspy-ai"}
PY_PREFIX = ("langchain-", "langgraph-", "llama-index-")
NPM_EXACT = {"langchain", "@openai/agents", "ai", "llamaindex", "@mastra/core", "@anthropic-ai/claude-agent-sdk"}
NPM_PREFIX = ("@langchain/", "@ai-sdk/", "@llamaindex/")
RETRIEVAL_ONLY = re.compile(r"^(langchain|llama-?index|llamaindex|@langchain/|@llamaindex/)")
SKIP_DIRS = {"node_modules", "vendor", "site-packages", ".venv", "venv", "dist", "build"}

RUNTIME, DEV, OPTIONAL = "runtime", "dev/test", "optional/extras"

# ---------------------------------------------------------------------------------------------- text regexes (§3.2)

PAIN_RE = re.compile(r"(?i)\b(flak\w*|non-?determinis\w*|nondetermin\w*|intermittent\w*|random(ly)?\s+fail\w*|"
                     r"fails?\s+randomly|inconsistent|unstable|var(y|ies|ying)|different\s+(outputs?|answers?|"
                     r"results?|responses?)|reproduc\w*|temperature|seed|xfail\w*|retr(y|ies|ied|ying)|re-?run\w*|"
                     r"skip\w*|disabl\w*|expensive|costs?|costly|tokens?|rate[- ]?limit\w*|mock\w*|cassettes?|"
                     r"record\w*|replay\w*)\b")
MODEL_RE = re.compile(r"(?i)\b(llms?|gpt[\w.-]*|openai|anthropic|claude|gemini|mistral|models?|agents?|langchain|"
                      r"langgraph|crewai|autogen|llama[ -]?index|pydantic[- ]ai|ai[- ]sdk|prompts?|completions?|"
                      r"evals?)\b")
MARKER_RE = re.compile(r"@pytest\.mark\.flaky|--reruns\b|jest\.retryTimes|\bretry\s*:\s*\d|"
                       r"skipif\([^)]*(OPENAI|ANTHROPIC|GOOGLE|GEMINI|MISTRAL|GROQ)_API_KEY")


def is_text_candidate(text: str) -> bool:
    return bool(PAIN_RE.search(text or "") and MODEL_RE.search(text or ""))


# ---------------------------------------------------------------------------------------------- discovery queries (§1)

HOST_TERMS = ["api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com", "openai.azure.com",
              "bedrock-runtime", "api.mistral.ai", "api.groq.com", "api.cohere", "openrouter.ai", "api.deepseek.com"]
PATH_SHAPES = ["path:cassettes", "path:cassette", "path:recordings", "path:vcr"]
PKG_FILES = ["filename:pyproject.toml", "filename:requirements.txt", "filename:package.json"]
PAIN_TERMS = ["flaky", "flakiness", "nondeterministic", '"non-deterministic"', '"non deterministic"', "intermittent",
              '"randomly fails"', '"fails randomly"', "xfail", "unstable", "retry", "rerun"]
MODEL_TERMS = ["llm", "openai", "anthropic", "claude", "gemini", "gpt", '"model output"', "prompt", "eval",
               "langchain", "langgraph", "crewai", "autogen", "llamaindex", '"llama-index"', '"pydantic-ai"',
               '"ai sdk"', "agent"]
COST_TERMS = ['"tests are expensive"', '"expensive tests"', '"api costs" test', '"token cost" test', '"skip llm"',
              '"llm tests"', '"live llm"', '"real llm" test', '"mock the llm"', '"mock llm"', '"record and replay" llm',
              "cassette llm", "vcr openai"]
COST_WITH_MODEL = ['"skip llm"', '"llm tests"', '"live llm"', '"real llm" test', '"mock the llm"', '"mock llm"',
                   '"record and replay" llm', "cassette llm", "vcr openai"]
COST_NO_MODEL = ['"tests are expensive"', '"expensive tests"', '"api costs" test', '"token cost" test']
COST_OR = ["llm", "openai", "agent"]
ISSUES_PREFIX = f"is:public created:>={HISTORY_START}"
COMMITS_PREFIX = f"committer-date:>={HISTORY_START}"


def _has_test_word(q: str) -> bool:
    return bool(re.search(r"(^|\s)test($|\s)", q.replace('"', " ")))


def discovery_queries(cfg: dict | None = None) -> list[dict]:
    """Every §1 query as {key, family (code|issues|commits), stratum, q}. ``cfg`` holds the §0.2 probe decisions:
    ``dropped`` (keys dropped after the probe), ``recording_packages``, ``issues_or_ok`` (False: the S2 cost family is
    split into single terms), ``issues_type_split`` (True: each issues query runs with is:issue and with is:pr)."""
    cfg = cfg or {}
    out = []
    for h in HOST_TERMS:
        for s in PATH_SHAPES:
            out.append({"family": "code", "stratum": "S1", "q": f"{h} {s}"})
    for pkg in cfg.get("recording_packages") or []:
        for fn in PKG_FILES:
            out.append({"family": "code", "stratum": "S1", "q": f"{pkg} {fn}"})
    iss = [f"{ISSUES_PREFIX} {p} {m} test" for p in PAIN_TERMS for m in MODEL_TERMS]
    for q in COST_TERMS:
        if cfg.get("issues_or_ok", True):
            iss.append(f"{ISSUES_PREFIX} {q} (llm OR openai OR agent)")
        else:
            iss += [f"{ISSUES_PREFIX} {q} {m}" for m in COST_OR]
    if cfg.get("issues_type_split"):
        iss = [f"{q} {t}" for q in iss for t in ("is:issue", "is:pr")]
    out += [{"family": "issues", "stratum": "S2", "q": q} for q in iss]
    com = [f"{COMMITS_PREFIX} {p} {m} test" for p in PAIN_TERMS for m in MODEL_TERMS]
    for q in COST_WITH_MODEL:
        com.append(f"{COMMITS_PREFIX} {q}" + ("" if _has_test_word(q) else " test"))
    for q in COST_NO_MODEL:
        com += [f"{COMMITS_PREFIX} {q} {m}" for m in COST_OR]
    out += [{"family": "commits", "stratum": "S3", "q": q} for q in com]
    dropped = set(cfg.get("dropped") or [])
    for d in out:
        d["key"] = d["q"]
    return [d for d in out if d["key"] not in dropped]


def ranged_query(d: dict, a, b) -> str:
    """The query for one bisection node: code ``size:a..b``; issues/commits the date range replaces the query's own
    ``created:>=`` / ``committer-date:>=`` qualifier (never added as a second one)."""
    q = d["q"]
    if d["family"] == "code":
        return f"{q} size:{a}..{b}"
    if d["family"] == "issues":
        assert ISSUES_PREFIX in q
        return q.replace(f"created:>={HISTORY_START}", f"created:{a}..{b}", 1)
    assert COMMITS_PREFIX in q
    return q.replace(f"committer-date:>={HISTORY_START}", f"committer-date:{a}..{b}", 1)


def projected_requests(total_count: int) -> int:
    if total_count > QUERY_CAP:
        return 10
    return math.ceil(total_count / 100) + 2 * math.ceil(total_count / 1000)


# ---------------------------------------------------------------------------------------------- §3.2 repository queries

TEXT_GROUPS = [
    ("pain", None, ["flaky", "nondeterministic", '"non-deterministic"', "intermittent", "unstable"]),
] + [("model", m, ["skip", "disable", "expensive", "cost", "mock"]) for m in ["llm", "openai", "agent", "model",
                                                                             "prompt"]]


def repo_text_queries(repo: str, kind: str, or_ok: bool = True) -> list[str]:
    """The six §3.2 strings for ``kind`` issues|commits (12 per member). ``or_ok`` False (the §0.2b OR check failed
    for this kind): each OR group is split into single-term queries."""
    date = f"created:>={HISTORY_START}" if kind == "issues" else f"committer-date:>={HISTORY_START}"
    out = []
    for _, m, terms in TEXT_GROUPS:
        pre = f"repo:{repo} {date}" + (f" {m}" if m else "")
        if or_ok:
            out.append(f"{pre} ({' OR '.join(terms)})")
        else:
            out += [f"{pre} {t}" for t in terms]
    return out


def operator_count(q: str) -> int:
    """Boolean operators (AND, OR, NOT) outside quotes."""
    s = re.sub(r'"[^"]*"', " ", q)
    return len(re.findall(r"(?<![\w-])(AND|OR|NOT)(?![\w-])", s))


# ---------------------------------------------------------------------------------------------- libraries (§2.2)

def norm_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def py_lib(name: str) -> str | None:
    n = norm_py(name)
    return n if n in PY_EXACT or n.startswith(PY_PREFIX) else None


def npm_lib(name: str) -> str | None:
    n = name.strip().lower()
    return n if n in NPM_EXACT or n.startswith(NPM_PREFIX) else None


class ManifestError(Exception):
    pass


def manifest_kind(path: str) -> str | None:
    parts = path.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return None
    b = parts[-1]
    if re.fullmatch(r"requirements.*\.txt", b):
        return "requirements"
    return {"pyproject.toml": "pyproject", "setup.py": "setup.py", "setup.cfg": "setup.cfg", "Pipfile": "pipfile",
            "environment.yml": "environment", "package.json": "package.json"}.get(b)


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def req_name(line: str) -> str | None:
    s = line.split("#", 1)[0].strip() if not line.strip().startswith("#") else ""
    if not s or s.startswith(("-", "git+", "http:", "https:", "file:", ".", "/")):
        return None
    m = _REQ_NAME.match(s)
    return m.group(1) if m else None


def _req_kind(path: str) -> str:
    return DEV if re.search(r"(?i)(dev|test|lint|ci|doc)", posixpath.basename(path)) else RUNTIME


def _pep508_list(items, kind: str) -> list[tuple[str, str]]:
    out = []
    for x in items or []:
        if isinstance(x, str):
            n = req_name(x)
            if n:
                out.append((n, kind))
        elif isinstance(x, dict):  # PEP 735 {include-group = ...}
            continue
        else:
            raise ManifestError(f"dependency entry {type(x).__name__}")
    return out


def _poetry_table(tbl, kind: str) -> list[tuple[str, str]]:
    out = []
    if not isinstance(tbl, dict):
        return out
    for n, v in tbl.items():
        if n.lower() == "python":
            continue
        k = OPTIONAL if isinstance(v, dict) and v.get("optional") else kind
        out.append((n, k))
    return out


def parse_manifest(path: str, text: str) -> list[tuple[str, str]]:
    """(dependency name, kind) pairs. Raises ManifestError when the manifest does not parse or has an unexpected
    shape (any other exception while reading it is turned into ManifestError)."""
    try:
        return _parse_manifest(path, text)
    except ManifestError:
        raise
    except Exception as e:
        raise ManifestError(f"{type(e).__name__}: {str(e)[:100]}")


def _parse_manifest(path: str, text: str) -> list[tuple[str, str]]:
    kind = manifest_kind(path)
    if kind == "requirements":
        return [(n, _req_kind(path)) for n in (req_name(ln) for ln in text.splitlines()) if n]
    if kind in ("pyproject", "pipfile"):
        try:
            d = tomllib.loads(text)
        except Exception as e:
            raise ManifestError(f"toml: {str(e)[:100]}")
        out = []
        if kind == "pipfile":
            out += _poetry_table(d.get("packages"), RUNTIME) + _poetry_table(d.get("dev-packages"), DEV)
            return out
        proj = d.get("project") or {}
        out += _pep508_list(proj.get("dependencies"), RUNTIME)
        for _, lst in (proj.get("optional-dependencies") or {}).items():
            out += _pep508_list(lst, OPTIONAL)
        for _, lst in (d.get("dependency-groups") or {}).items():
            out += _pep508_list(lst, DEV)
        tool = d.get("tool") or {}
        po = tool.get("poetry") or {}
        out += _poetry_table(po.get("dependencies"), RUNTIME) + _poetry_table(po.get("dev-dependencies"), DEV)
        for _, g in (po.get("group") or {}).items():
            out += _poetry_table((g or {}).get("dependencies"), DEV)
        pdm = tool.get("pdm") or {}
        for _, lst in (pdm.get("dev-dependencies") or {}).items():
            out += _pep508_list(lst, DEV)
        uv = tool.get("uv") or {}
        out += _pep508_list(uv.get("dev-dependencies"), DEV)
        return out
    if kind == "setup.py":
        return _setup_py(text)
    if kind == "setup.cfg":
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            cp.read_string(text)
        except configparser.Error as e:
            raise ManifestError(f"setup.cfg: {str(e)[:100]}")
        out = []
        if cp.has_option("options", "install_requires"):
            out += [(n, RUNTIME) for n in map(req_name, cp.get("options", "install_requires").splitlines()) if n]
        if cp.has_section("options.extras_require"):
            for k in cp.options("options.extras_require"):
                out += [(n, OPTIONAL) for n in map(req_name, cp.get("options.extras_require", k).splitlines()) if n]
        return out
    if kind == "environment":
        try:
            d = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            raise ManifestError(f"yaml: {str(e)[:100]}")
        if not isinstance(d, dict):
            raise ManifestError("environment.yml is not a mapping")
        out = []
        for x in d.get("dependencies") or []:
            if isinstance(x, str):
                m = re.match(r"^\s*(?:[\w-]+::)?([A-Za-z0-9][A-Za-z0-9._-]*)", x)
                if m:
                    out.append((m.group(1), RUNTIME))
            elif isinstance(x, dict):
                for ln in x.get("pip") or []:
                    n = req_name(str(ln))
                    if n:
                        out.append((n, RUNTIME))
        return out
    if kind == "package.json":
        try:
            d = json.loads(text)
        except json.JSONDecodeError as e:
            raise ManifestError(f"json: {str(e)[:100]}")
        if not isinstance(d, dict):
            raise ManifestError("package.json is not an object")
        out = []
        for sec, k in (("dependencies", RUNTIME), ("peerDependencies", RUNTIME), ("devDependencies", DEV),
                       ("optionalDependencies", OPTIONAL)):
            v = d.get(sec) or {}
            if not isinstance(v, dict):
                raise ManifestError(f"{sec} is not an object")
            out += [(n, k) for n in v]
        return out
    return []


def _literal_block(text: str, start: int, open_ch: str, close_ch: str) -> str | None:
    if start >= len(text) or text[start] != open_ch:
        return None
    depth, i, q = 0, start, None
    while i < len(text):
        ch = text[i]
        if q:
            if ch == "\\":
                i += 2
                continue
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None


def _setup_py(text: str) -> list[tuple[str, str]]:
    out = []
    for key, open_ch, close_ch, kind in (("install_requires", "[", "]", RUNTIME),
                                         ("extras_require", "{", "}", OPTIONAL)):
        for m in re.finditer(rf"\b{key}\s*=\s*", text):
            blk = _literal_block(text, m.end(), open_ch, close_ch)
            if blk is None:
                raise ManifestError(f"setup.py: {key} is not a literal")
            if kind == OPTIONAL:
                blk = re.sub(r"(['\"])[^'\"]*\1\s*:", " ", blk)  # drop the extras names
            for s in re.findall(r"'([^']*)'|\"([^\"]*)\"", blk):
                n = req_name(s[0] or s[1])
                if n:
                    out.append((n, kind))
    return out


def libraries_of(path: str, deps: list[tuple[str, str]]) -> list[tuple[str, str]]:
    js = manifest_kind(path) == "package.json"
    out = []
    for n, k in deps:
        lib = npm_lib(n) if js else py_lib(n)
        if lib:
            out.append((lib, k))
    return out


def recording_packages_of(path: str, deps: list[tuple[str, str]], packages: list[str]) -> list[str]:
    js = manifest_kind(path) == "package.json"
    want = {(p.lower() if js else norm_py(p)) for p in packages}
    return sorted({(n.lower() if js else norm_py(n)) for n, _ in deps} & want)


# ---------------------------------------------------------------------------------------------- commands (§2.3)

INSTALL_RE = re.compile(r"\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|bun|apt(-get)?|brew|go)\s+"
                        r"(install|i|add|ci|get|mod download)\b")
RUNNER_RE = re.compile(r"\b(jest|vitest|mocha|pytest|python3? -m pytest|tox|nox|manage\.py test|rspec|rails test|"
                       r"bin/rails test|rake (test|spec)\b|go test|node --test|make test[\w-]*|bun test|deno test|"
                       r"python3? -m unittest|hatch test|nx test|turbo (run )?test[\w:-]*)\b")
STRIPPED_RUNNER_RE = re.compile(r"^(unittest|pytest)\b")
PM_RE = re.compile(r"\b(npm|yarn|pnpm|bun)\b( run)? (test[\w:-]*)\b")
HELP_RE = re.compile(r"\s--(help|version)\b")
ACTION_TEST_RE = re.compile(r"(?i)pytest|test")
ACTION_NOT_RE = re.compile(r"(?i)report|summary|publish|coverage")

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
]


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


def strip_prefixes(cmd: str) -> str:
    c = cmd.strip()
    while True:
        prev = c
        for rx in STRIP_RES:
            c = rx.sub("", c, count=1).strip()
        if c == prev:
            return c


def is_runner_command(cmd: str) -> bool:
    """Gate note 7: matched before and after prefix stripping (``python -m unittest`` -> ``unittest``)."""
    s = strip_prefixes(cmd)
    return bool(RUNNER_RE.search(cmd) or PM_RE.search(cmd) or RUNNER_RE.search(s) or PM_RE.search(s)
                or STRIPPED_RUNNER_RE.match(s))


def tokens(s: str) -> list[str]:
    try:
        return shlex.split(s, comments=False)
    except ValueError:
        return s.split()


def jpath(wd: str, name: str) -> str:
    p = posixpath.normpath(posixpath.join(wd or ".", name))
    return "" if p == "." else p


def _pm_script(cmd: str):
    """(manager, script name) for `npm run X` / `npm test` / `yarn X` / `pnpm X` / `bun run X`, else None."""
    t = tokens(cmd)
    for i, w in enumerate(t):
        base = posixpath.basename(w)
        if base in ("npm", "yarn", "pnpm", "bun"):
            rest = t[i + 1:]
            while rest and rest[0].startswith("-") and rest[0] != "--":
                rest = rest[1:]
            if not rest:
                return None
            if rest[0] in ("run", "run-script"):
                rest = rest[1:]
                while rest and rest[0].startswith("-") and rest[0] != "--":
                    rest = rest[1:]
                return (base, rest[0]) if rest else None
            if rest[0] in ("test", "t", "tst"):
                return base, "test"
            if base in ("yarn", "pnpm") and rest[0] not in ("install", "add", "exec", "dlx", "x", "why", "info",
                                                              "workspace", "workspaces", "-r", "--filter"):
                return base, rest[0]
            return None
    return None


def _make_rules(text: str) -> dict:
    rules = {}
    cur = None
    for ln in re.sub(r"\\\n", " ", text).splitlines():
        if ln.startswith("\t"):
            if cur is not None:
                for t in cur:
                    rules[t]["recipe"].append(ln.strip())
            continue
        if re.match(r"^\s*(export\s+)?[A-Za-z_][\w.]*\s*(\?=|:=|::=|\+=|=)", ln):
            cur = None
            continue
        mr = re.match(r"^([^\s:#=][^:=]*?)\s*::?\s*([^=].*)?$", ln)
        if mr and not ln.startswith("#"):
            parts = (mr.group(2) or "").split(";", 1)
            cur = mr.group(1).split()
            for tgt in cur:
                rules.setdefault(tgt, {"prereq": [], "recipe": []})
                rules[tgt]["prereq"] += [p for p in parts[0].split() if not p.startswith("$")]
                if len(parts) > 1 and parts[1].strip():
                    rules[tgt]["recipe"].append(parts[1].strip())
            continue
        if ln.strip() and not ln.startswith("#"):
            cur = None
    return rules


def resolves_to_runner(cmd: str, wd: str, read, level: int = 0) -> bool:
    """True when ``cmd`` is a test runner or resolves to one through package.json scripts (npm/yarn/pnpm/bun), make
    targets, tox ``commands`` or nox ``session.run`` within 3 levels. Missing files resolve to False."""
    if is_runner_command(cmd):
        return True
    if level >= 3:
        return False
    c = strip_prefixes(cmd)
    pm = _pm_script(c)
    if pm:
        pj = read(jpath(wd, "package.json"))
        try:
            scripts = (json.loads(pj).get("scripts") or {}) if pj else {}
        except (json.JSONDecodeError, AttributeError):
            scripts = {}
        body = scripts.get(pm[1]) if isinstance(scripts, dict) else None
        return isinstance(body, str) and any(resolves_to_runner(x, wd, read, level + 1) for x in kept_commands(body))
    m = re.match(r"^(make|\$\(MAKE\))\b(.*)", c)
    if m:
        args, mdir, targets, i = tokens(m.group(2)), wd, [], 0
        while i < len(args):
            if args[i] == "-C" and i + 1 < len(args):
                mdir = jpath(wd, args[i + 1])
                i += 2
                continue
            if not args[i].startswith("-") and "=" not in args[i]:
                targets.append(args[i])
            i += 1
        text = read(jpath(mdir, "Makefile")) or read(jpath(mdir, "makefile")) or read(jpath(mdir, "GNUmakefile"))
        if text is None:
            return False
        rules = _make_rules(text)
        if not targets:
            targets = [next((t for t in rules if not t.startswith(".") and "%" not in t), None)]
        return any(_make_target(t, rules, mdir, read, level + 1, set()) for t in targets if t)
    return False


def _make_target(t: str, rules: dict, mdir: str, read, level: int, seen: set) -> bool:
    if t not in rules or t in seen or level > 3:
        return False
    seen.add(t)
    if any(_make_target(p, rules, mdir, read, level + 1, seen) for p in rules[t]["prereq"]):
        return True
    for raw in rules[t]["recipe"]:
        for sc in kept_commands(re.sub(r"^[@+-]+", "", raw)):
            sc = re.sub(r"^\$\(MAKE\)", "make", sc.strip())
            if re.match(r"^make\b", sc):
                tg = [a for a in tokens(sc)[1:] if not a.startswith("-") and "=" not in a]
                if any(_make_target(x, rules, mdir, read, level + 1, seen) for x in tg):
                    return True
                continue
            if resolves_to_runner(sc, mdir, read, level):
                return True
    return False


def is_test_step(step: dict, wd: str, read) -> bool:
    if not isinstance(step, dict):
        return False
    uses = step.get("uses")
    if isinstance(uses, str):
        name = uses.split("@")[0]
        return bool(ACTION_TEST_RE.search(name)) and not ACTION_NOT_RE.search(name)
    run = step.get("run")
    if not isinstance(run, (str, int, float)):  # never str() a parsed list/mapping (YAML alias expansion)
        return False
    return any(resolves_to_runner(c, wd, read) for c in kept_commands(str(run)))


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
    if isinstance(on, (list, dict)):
        return set(map(str, on))
    raise ValueError("on: does not parse")


def working_dir(step: dict, job: dict, wf: dict) -> str:
    for src in (step.get("working-directory"),
                ((job.get("defaults") or {}).get("run") or {}).get("working-directory"),
                ((wf.get("defaults") or {}).get("run") or {}).get("working-directory")):
        if src is not None:
            s = str(src)
            if "${{" in s:
                return ""
            p = posixpath.normpath(s)
            return "" if p in (".", "/", "./") else p.lstrip("/").removeprefix("./")
    return ""


def name_pattern(name: str) -> str:
    parts = re.split(r"\$\{\{.*?\}\}", name)
    return ".*".join(re.escape(p) for p in parts)


def job_matches(api_name: str, yaml_name: str, caller: str | None = None) -> bool:
    callee = name_pattern(yaml_name)
    pat = rf"^{name_pattern(caller)}( \(.*\))? / {callee}$" if caller is not None else rf"^{callee}$"
    if re.match(pat, api_name, re.S):
        return True
    m = re.match(r"^(.*) \((.*)\)$", api_name)
    return m is not None and bool(re.match(pat, m.group(1), re.S))


def step_key(step: dict) -> tuple[str, str]:
    if isinstance(step.get("name"), (str, int, float)):
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


def pick_api_step(api_steps: list[dict], yaml_steps: list[dict], idx: int) -> dict | None:
    key = step_key(yaml_steps[idx])
    j = sum(1 for k in range(idx) if isinstance(yaml_steps[k], dict) and step_key(yaml_steps[k]) == key)
    matches = [s for s in sorted(api_steps, key=lambda s: s.get("number") or 0) if step_matches(s.get("name"), key)]
    return matches[j] if j < len(matches) else None


def run_evidence(jobs: list[dict], target: dict) -> str:
    """One run's evidence for a test job target {job_name, caller, yaml_steps, idxs}: ``yes`` (the job concluded
    success/failure and a test step ran, not skipped), ``unmatched`` (the job concluded but no test step was found
    among its API steps), or ``none``."""
    out = "none"
    for j in jobs:
        if not job_matches(j.get("name") or "", target["job_name"], target.get("caller")):
            continue
        if j.get("conclusion") not in ("success", "failure"):
            continue
        found = False
        for i in target["idxs"]:
            s = pick_api_step(j.get("steps") or [], target["yaml_steps"], i)
            if s is None:
                continue
            found = True
            if s.get("conclusion") not in ("skipped", None):
                return "yes"
        if not found:
            out = "unmatched"
    return out


# ---------------------------------------------------------------------------------------------- recordings (§3.1)

REC_SEGMENTS = {"cassettes", "cassette", "vcr", "vcr_cassettes", "recordings", "__recordings__"}
REC_SUFFIXES = ("fixtures/vcr", "__snapshots__/vcr")
TEST_SEGMENTS = {"test", "tests", "spec", "fixtures", "__tests__"}
REC_EXT = (".yaml", ".yml", ".json", ".har")


def recording_path(path: str) -> bool:
    d = posixpath.dirname(path)
    return any(s in REC_SEGMENTS for s in d.split("/")) or d.endswith(REC_SUFFIXES)


def recording_file(path: str) -> str | None:
    """``path`` (path rule), ``shape`` (to be checked for the VCR/HAR shape) or None (not a recording candidate)."""
    parts = path.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]) or not path.lower().endswith(REC_EXT):
        return None
    if recording_path(path):
        return "path"
    if any(p in TEST_SEGMENTS for p in parts[:-1]):
        return "shape"
    return None


def hosts_in(text: str) -> list[str]:
    low = (text or "").lower()
    return [h for h in HOSTS if h in low]


def _shape(d) -> tuple[bool, bool]:
    vcr = har = False
    if isinstance(d, dict):
        it = d.get("interactions")
        if isinstance(it, list):
            vcr = any(isinstance(x, dict) and isinstance(x.get("request"), dict) and "uri" in x["request"] for x in it)
        log = d.get("log")
        if isinstance(log, dict) and isinstance(log.get("entries"), list):
            har = any(isinstance(x, dict) and isinstance(x.get("request"), dict) and "url" in x["request"]
                      for x in log["entries"])
    return vcr, har


def recording_facts(path_hint: str | None, text: str | None, size: int | None = None) -> dict:
    """What the pipeline keeps of a fetched recording file: hosts found, VCR/HAR shape, a snippet for the hand check."""
    if text is None:
        return {"size": size, "text": False}
    hs = hosts_in(text)
    try:
        d = json.loads(text)
        parse = "json"
    except ValueError:
        try:
            d = yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
            parse = "yaml"
        except Exception:
            d, parse = None, "error"
    vcr, har = _shape(d)
    snip = None
    if hs:
        i = text.lower().find(hs[0])
        snip = text[max(0, i - 150):i + 150]
    return {"size": size, "text": True, "hosts": hs, "vcr": vcr, "har": har, "parse": parse, "snippet": snip}


def recording_hit(kind: str, facts: dict) -> bool:
    if not facts.get("hosts"):
        return False
    return kind == "path" or bool(facts.get("vcr") or facts.get("har"))


# ---------------------------------------------------------------------------------------------- texts / pain (§3-§4)

def text_order(texts: list[dict]) -> list[dict]:
    """§4.1: discovery hits first, then the rest; each part newest first (ties by URL)."""
    def key(t):
        return (0 if t.get("discovery") else 1, _neg_date(t.get("created_at") or ""), t["url"])
    return sorted(texts, key=key)


def _neg_date(s: str) -> str:
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def final_label(first: str | None, second: str | None) -> str:
    """confirmed only when both readers say confirmed. A confirmed or unclear first read without its second read is
    ``pending``. A rejected first read that the second reader (sample) calls confirmed -> unclear (PREREG)."""
    if first is None:
        return "pending"
    if first == "confirmed":
        if second is None:
            return "pending"
        return "confirmed" if second == "confirmed" else "unclear"
    if first == "unclear":
        return "pending" if second is None else "unclear"
    if first == "rejected":
        return "unclear" if second == "confirmed" else "rejected"
    raise ValueError(first)


def member_pain(recording: dict | None, flags: list[str], candidates: list[dict], reads: dict) -> dict:
    """Pain of one member. ``recording``: a §3.1 hit or None; ``flags``: text-capped, text-error, tree-truncated,
    recording-capped, request-cap, texts-missing; ``candidates`` in §4.1 order; ``reads``: url -> {first, second}."""
    if recording:
        return {"pain": "yes", "kind": "recording", "evidence": recording, "why": []}
    why = list(flags)
    for i, t in enumerate(candidates[:TEXT_CAP]):
        r = reads.get(t["url"]) or {}
        lab = final_label((r.get("first") or {}).get("label"), (r.get("second") or {}).get("label"))
        if lab == "confirmed":
            return {"pain": "yes", "kind": "text", "evidence": {"url": t["url"], "created_at": t.get("created_at"),
                                                                 "quote": (r.get("first") or {}).get("quote"),
                                                                 "reason": (r.get("first") or {}).get("reason")},
                    "why": []}
        if lab == "unclear":
            why.append("unclear")
        elif lab == "pending":
            why.append("not-read")
    if len(candidates) > TEXT_CAP:
        why.append("text-cap")
    why = sorted(set(why))
    return {"pain": "unknown" if why else "no", "kind": None, "evidence": None, "why": why}


# ---------------------------------------------------------------------------------------------- order (§1)

def stratum_order(repos: list[dict], seed: int = 1) -> list[dict]:
    lst = sorted(repos, key=lambda r: r["html_url"])
    random.Random(seed).shuffle(lst)
    return lst


def interleave(a: list, b: list) -> list:
    out = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return out


def static_order(s1: list, s2: list, s3: list, first: int = STRATUM_FIRST) -> list:
    """The planned read order when no candidate is excluded: S1[:300], S2/S3 interleaved to 300 each, rest of S1,
    rest of S2/S3 interleaved."""
    return s1[:first] + interleave(s2[:first], s3[:first]) + s1[first:] + interleave(s2[first:], s3[first:])


def plan_next(orders: dict, done: set, read_counts: dict, size: int = CHUNK_SIZE,
              first: int = STRATUM_FIRST) -> list:
    """Next chunk of candidate ids following §1 with exclusions known so far: phase 1 takes S1 until 300 are read,
    phase 2 S2 and S3 one to one until each has 300 read, then the rest of S1, then the rest of S2/S3 one to one.
    A phase takes at most the number of reads it still needs, so it never overshoots 300 within a chunk."""
    left = {s: [x for x in orders.get(s, []) if x not in done] for s in ("S1", "S2", "S3")}
    need = {s: max(0, first - read_counts.get(s, 0)) for s in left}
    if need["S1"] and left["S1"]:
        return left["S1"][:min(size, need["S1"])]
    a = left["S2"][:need["S2"]] if need["S2"] else []
    b = left["S3"][:need["S3"]] if need["S3"] else []
    if a or b:
        return interleave(a, b)[:size]
    if left["S1"]:
        return left["S1"][:size]
    return interleave(left["S2"], left["S3"])[:size]


# ---------------------------------------------------------------------------------------------- §5 statistics

def wilson_upper(k: int, n: int, z: float = Z) -> float:
    if n == 0:
        return 1.0
    p = k / n
    z2 = z * z
    return (p + z2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n)


def stratum_bound(A: int, read: int, N: float, all_read: bool, any_truncated: bool, any_incomplete: bool) -> dict:
    U = wilson_upper(A, read)
    if all_read and not any_truncated and not any_incomplete:
        return {"U": U, "B": float(A), "how": "count"}
    if read >= STRATUM_FIRST and not any_incomplete:
        return {"U": U, "B": U * N, "how": "wilson"}
    return {"U": U, "B": None, "how": "undefined"}


def wilson_lower(k: int, n: int, z: float = Z) -> float:
    if n == 0:
        return 0.0
    p = k / n
    z2 = z * z
    return max(0.0, (p + z2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n))


def intervals_disjoint(k1: int, n1: int, k2: int, n2: int) -> bool:
    """True when both samples are non-empty and their Wilson 95% intervals do not overlap (the S3 old/new pool check,
    coordinator 2026-11-26 19:10Z)."""
    if not n1 or not n2:
        return False
    return wilson_upper(k1, n1) < wilson_lower(k2, n2) or wilson_upper(k2, n2) < wilson_lower(k1, n1)


def project(strata: dict) -> dict:
    """The founder's "lettura A" projection (2026-11-26 19:01Z; coordinator 19:04Z): over the candidate pool, per
    stratum the rate times the candidates of the stratum, summed. Point: pain yes / read. Interval: Wilson 95% lower
    bound of pain yes, upper bound of A_s (pain yes + unknown + uncertain, as in §5, so an unresolved member counts
    against a DROP). A fully read stratum projects its own counts."""
    out = {"read": 0, "yes": 0, "point": 0.0, "lower": 0.0, "upper": 0.0, "by_stratum": {}}
    for s, v in strata.items():
        n, C = v.get("read") or 0, v.get("candidates") or 0
        if v.get("all_read"):
            pt, lo, up = float(v["yes"]), float(v["yes"]), float(v["A"])
        else:
            pt = (v["yes"] / n * C) if n else 0.0
            lo = wilson_lower(v["yes"], n) * C
            up = wilson_upper(v["A"], n) * C
        out["by_stratum"][s] = {"read": n, "candidates": C, "yes": v["yes"], "rate": (v["yes"] / n) if n else None,
                                "point": pt, "lower": lo, "upper": up}
        out["read"] += n
        out["yes"] += v["yes"]
        out["point"] += pt
        out["lower"] += lo
        out["upper"] += up
    return out


def zero_bound(N: dict, reads: dict) -> float:
    return sum(Z2 * N[s] / (reads[s] + Z2) for s in N)


def equal_split_reads(N_s: float) -> int:
    return max(STRATUM_FIRST, math.ceil(3 * Z2 * N_s / THRESHOLD - Z2))


def decide(c: dict) -> dict:
    """c: yes, handcheck_ok, strata {S1,S2,S3: {yes, A, read, candidates, all_read}}, state (blocked, prepass_stop,
    hard_stop, read_started, rule_failure). The founder's "lettura A" (2026-11-26 19:01Z; coordinator 19:04Z):
    reading time does not decide; CONTINUE at THRESHOLD; no DROP before the stop (HARD_STOP); at the stop NOT ENOUGH
    DATA, or DROP when the projection's summed upper bound is below THRESHOLD. The 24 h budget end is withdrawn."""
    st = c.get("state") or {}
    if st.get("blocked"):
        return {"kind": "NO DECISION", "first": "BLOCKED",
                "line": "NO DECISION: reading never started; BLOCKED (no code-search route answers 200)."}
    if st.get("rule_failure"):
        return {"kind": "NO DECISION", "first": "DONE",
                "line": f"NO DECISION: a rule failed twice ({st['rule_failure']})."}
    if not c.get("read_started"):
        if st.get("prepass_stop"):
            return {"kind": "NO DECISION", "first": "NOT DONE",
                    "line": "NO DECISION: reading never started; projected discovery above 20 h (pre-pass stop)."}
        if st.get("hard_stop"):
            return {"kind": "NO DECISION", "first": "DONE",
                    "line": "NO DECISION: reading never started; hard stop reached before the first candidate."}
        return {"kind": "NOT STARTED", "first": "NOT DONE", "line": "NOT STARTED: no candidate read yet."}
    pj = project(c.get("strata") or {})
    ptxt = (f"{pj['read']} read, pain yes {c['yes']} (rate {c['yes'] / pj['read']:.4f})" if pj["read"] else
            f"0 read, pain yes {c['yes']}") + \
        f"; projected over the candidate pool {pj['point']:.1f} (95% {pj['lower']:.1f} to upper {pj['upper']:.1f})"
    if c["yes"] >= THRESHOLD and c.get("handcheck_ok"):
        return {"kind": "CONTINUE", "first": "DONE", "projection": pj,
                "line": f"CONTINUE: {c['yes']} agent repositories with agent-test non-determinism pain."}
    if st.get("hard_stop") and c.get("handcheck_ok"):
        if pj["upper"] < THRESHOLD:
            return {"kind": "DROP", "first": "DONE", "projection": pj,
                    "line": f"DROP: {ptxt} < {THRESHOLD}."}
        return {"kind": "NOT ENOUGH DATA", "first": "DONE", "projection": pj,
                "line": f"NOT ENOUGH DATA: {ptxt}."}
    return {"kind": "IN PROGRESS", "first": "NOT DONE", "projection": pj, "line": f"IN PROGRESS: {ptxt}."}
