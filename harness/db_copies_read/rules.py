"""Matching, pain rules (PREREG §3) and free per-worker levels (PREREG §4) for db-copies-read.

Pure functions over stored JSON; no network. Every rule here is pre-registered in PREREG.md; a change after the
first table row exists is allowed only for a code bug (PREREG "Changes after PREREG").
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

WINDOW_START = "2024-01-01T00:00:00Z"

# ---------------------------------------------------------------------------------------------- term lists (§3.2)
SPEED = ["slow", "slower", "takes too long", "too long", "minutes", "hours", "timeout", "timed out", "speed up",
         "faster", "long-running", "long running"]
TEST = ["test", "tests", "testing", "test suite", "pytest", "jest", "mocha", "vitest", "go test", "integration tests"]
DBSERIAL = ["database", "db", "postgres", "postgresql", "mysql", "mariadb", "mongodb", "mongo", "sqlite", "fixture",
            "fixtures", "serial", "sequential", "sequentially", "one at a time"]
PARALLEL = ["parallel", "parallelize", "parallelise", "parallelism", "parallelization", "parallelisation", "xdist",
            "pytest-xdist", "workers", "concurrency", "concurrently"]
FAILURE = ["flaky", "deadlock", "race condition", "conflict", "duplicate key", "already exists", "unique constraint",
           "locked"]


def _term_re(term: str) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[ -]", term)]
    return re.compile(r"\b" + r"(?: |-)".join(words) + r"\b", re.I)


_TERM_RES = {t: _term_re(t) for t in set(SPEED + TEST + DBSERIAL + PARALLEL + FAILURE)}


def terms_in(text: str, terms: list[str]) -> list[str]:
    """Terms of ``terms`` found as whole words / phrases in ``text`` (case-insensitive)."""
    return [t for t in terms if _TERM_RES[t].search(text)]


# ---------------------------------------------------------------------------------------------- flag tokens (§3.2)
# A token starts at the line start or after whitespace, a quote, or one of ( [ { , = and ends at the line end or
# before whitespace, a quote, or one of ) ] } , ; (the config-key forms such as ``maxWorkers: 1,`` end in a comma).
L = r"(?:^|(?<=[\s'\"`(\[{,=]))"
R = r"(?=$|[\s'\"`)\]},;])"
N = r"(?:\s+|=)"


def _num(s: str) -> int | None:
    try:
        return int(s)
    except ValueError:
        return None


def _is_pytest_line(line: str) -> bool:
    return bool(re.search(r"\b(?:py\.test|pytest)\b", line, re.I)) or bool(re.search(r"\baddopts\b", line, re.I))


def _is_go_test_line(line: str) -> bool:
    return bool(re.search(r"\bgo\s+test\b", line))


def _is_jest_line(line: str) -> bool:
    return bool(re.search(r"\bjest\b", line, re.I))


def _is_manage_test_line(line: str) -> bool:
    return bool(re.search(r"manage\.py\s+test\b", line))


def _is_mocha_line(line: str) -> bool:
    return bool(re.search(r"\bmocha\b", line, re.I))


def flag_tokens(line: str) -> list[tuple[str, str]]:
    """Return [(polarity, token)] for every pre-registered flag token on one line; polarity 'parallel' or 'serial'.

    Scopes: ``-n`` pytest lines and ``addopts`` only; ``--parallel`` ``manage.py test`` lines only; ``-w``/``-i``
    Jest lines; ``-p`` ``go test`` lines only; ``--jobs`` mocha lines."""
    out: list[tuple[str, str]] = []
    if _is_pytest_line(line):
        for m in re.finditer(L + r"-n" + N + r"(auto|\d+)" + R, line):
            v = m.group(1)
            if v == "auto" or (_num(v) or 0) >= 2:
                out.append(("parallel", m.group(0)))
            elif v == "0":
                out.append(("serial", m.group(0)))
    for m in re.finditer(L + r"--numprocesses" + N + r"(auto|logical|\d+)" + R, line):
        v = m.group(1)
        if not v.isdigit() or int(v) >= 2:
            out.append(("parallel", m.group(0)))
        elif v == "0":
            out.append(("serial", m.group(0)))
    if _is_manage_test_line(line):
        for m in re.finditer(L + r"--parallel(?:" + N + r"(auto|\d+))?" + R, line):
            out.append(("parallel", m.group(0)))
    for m in re.finditer(r"\bparallelize\(", line):
        out.append(("parallel", m.group(0)))
    for m in re.finditer(L + r"(?:--maxWorkers" + N + r"|maxWorkers:\s*)['\"]?(\d+%?)['\"]?" + R, line):
        v = m.group(1)
        if v.endswith("%") or int(v) >= 2:
            out.append(("parallel", m.group(0)))
        elif v == "1":
            out.append(("serial", m.group(0)))
    if _is_jest_line(line):
        for m in re.finditer(L + r"-w" + N + r"(\d+%?)" + R, line):
            v = m.group(1)
            if v.endswith("%") or int(v) >= 2:
                out.append(("parallel", m.group(0)))
            elif v == "1":
                out.append(("serial", m.group(0)))
        for m in re.finditer(L + r"-i" + R, line):
            out.append(("serial", m.group(0)))
    if _is_go_test_line(line):
        for m in re.finditer(L + r"-p" + N + r"(\d+)" + R, line):
            v = int(m.group(1))
            if v >= 2:
                out.append(("parallel", m.group(0)))
            elif v == 1:
                out.append(("serial", m.group(0)))
    for m in re.finditer(L + r"--test-concurrency" + N + r"(\d+)" + R, line):
        v = int(m.group(1))
        if v >= 2:
            out.append(("parallel", m.group(0)))
        elif v == 1:
            out.append(("serial", m.group(0)))
    for m in re.finditer(L + r"fileParallelism:\s*(true|false)" + R, line):
        out.append(("parallel" if m.group(1) == "true" else "serial", m.group(0)))
    for m in re.finditer(L + r"--no-file-parallelism" + R, line):
        out.append(("serial", m.group(0)))
    for m in re.finditer(L + r"--runInBand" + R, line):
        out.append(("serial", m.group(0)))
    if _is_mocha_line(line):
        for m in re.finditer(L + r"--jobs" + N + r"(\d+)" + R, line):
            if int(m.group(1)) >= 2:
                out.append(("parallel", m.group(0)))
    return out


def has_parallel_token(text: str) -> bool:
    return any(p == "parallel" for ln in text.splitlines() for p, _ in flag_tokens(ln))


def has_serial_token(text: str) -> bool:
    return any(p == "serial" for ln in text.splitlines() for p, _ in flag_tokens(ln))


# serial tokens whose runner is parallel by default (Jest, Vitest, go test across packages): adding one abandons
# parallelism by itself (P4). Others (-n 0, --test-concurrency 1) count only when a parallel token is removed too.
def _default_parallel_serial(token: str) -> bool:
    t = token.strip()
    return bool(re.match(r"(--runInBand|-i$|-w|--maxWorkers|maxWorkers:|fileParallelism:|--no-file-parallelism|-p)", t))


# ---------------------------------------------------------------------------------------------- text handling
_CODE = re.compile(r"```.*?(?:```|$)", re.S)


def prose(text: str | None) -> str:
    """Text with triple-backtick blocks removed (text terms in code blocks are ignored, §3.2)."""
    return _CODE.sub(" ", text or "")


def text_match(text: str) -> dict:
    """Term-list hits over the prose of one item; each list matched independently over the whole text (gate M4)."""
    p = prose(text)
    return {
        "speed": terms_in(p, SPEED),
        "test": terms_in(p, TEST),
        "dbserial": terms_in(p, DBSERIAL) + (["<serial flag>"] if has_serial_token(p) else []),
        "parallel": terms_in(p, PARALLEL) + (["<parallel flag>"] if has_parallel_token(p) else []),
        "failure": terms_in(p, FAILURE),
    }


def text_rules(kind: str, text: str) -> list[str]:
    """Rules satisfied by the text of one item: P1, P1-db, P2-text (pull or commit only), P3-text."""
    m = text_match(text)
    out = []
    if m["speed"] and m["test"]:
        out.append("P1")
        if m["dbserial"]:
            out.append("P1-db")
    if kind in ("pull", "commit") and m["parallel"] and m["test"]:
        out.append("P2-text")
    if m["failure"] and m["dbserial"] and m["parallel"]:
        out.append("P3-text")
    return out


def matched_by_text(kind: str, text: str) -> bool:
    """"Matched by title/body" (§3.1): a P1, P2-text or P3-text match."""
    return any(r in ("P1", "P2-text", "P3-text") for r in text_rules(kind, text))


def quote_for(text: str, rules: list[str]) -> str:
    """The exact matching text (at most 300 characters): the first prose line holding a term of the first rule."""
    p = prose(text)
    lists = {"P1": SPEED, "P1-db": SPEED, "P2-text": PARALLEL, "P3-text": FAILURE}
    want = lists.get(rules[0], SPEED) if rules else SPEED
    for ln in p.splitlines():
        if terms_in(ln, want) or (rules and rules[0] == "P2-text" and has_parallel_token(ln)):
            return ln.strip()[:300]
    for ln in p.splitlines():
        if ln.strip():
            return ln.strip()[:300]
    return ""


# ---------------------------------------------------------------------------------------------- exclusions (§3.3)
BOT_LOGINS = {"dependabot", "renovate", "github-actions"}


def is_bot(user: dict | None) -> bool:
    if not user:
        return False
    login = (user.get("login") or "").lower()
    return user.get("type") == "Bot" or login.endswith("[bot]") or login in BOT_LOGINS


def is_bump(title: str) -> bool:
    t = (title or "").lstrip()
    return t.startswith("Bump ") or t.lower().startswith("chore(deps)") or t.startswith("Update dependency")


_CI_SPEED = re.compile(r"actions/cache|docker layer cache|layer caching|cache (?:the )?dependencies|"
                       r"dependency cach|\blint(?:ing)? (?:speed|faster|slow)|build (?:speed|faster|slow)", re.I)
_RELEASE = re.compile(r"^(?:chore\(release\)|release[:\s]|v?\d+\.\d+\.\d+\b|changelog\b|.*\brelease notes?\b)", re.I)


def exclusion(kind: str, user: dict | None, title: str, text: str, created: str | None, rules: list[str]) -> str | None:
    """``excluded_reason`` for an item, or None."""
    if created and created < WINDOW_START:
        return "before-2024"
    if is_bot(user):
        return "bot"
    if is_bump(title):
        return "dependency-bump"
    if _RELEASE.match((title or "").strip()):
        return "changelog-or-release"
    if _CI_SPEED.search(prose(text)) and "P1" not in rules:
        return "ci-speed-not-tests"
    return None


# ---------------------------------------------------------------------------------------------- diffs (§3.2 P2/P4)
DOC_FILE = re.compile(r"(^|/)(readme[^/]*|docs?/.*|.*\.md|.*\.rst|changelog[^/]*)$", re.I)
DEP_FILE = re.compile(r"(^|/)(pyproject\.toml|requirements[^/]*\.txt|Pipfile|setup\.cfg|setup\.py|package\.json|go\.mod)$")


def _patch_lines(patch: str | None) -> tuple[list[str], list[str]]:
    add, rem = [], []
    for ln in (patch or "").splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            add.append(ln[1:])
        elif ln.startswith("-"):
            rem.append(ln[1:])
    return add, rem


def _norm_tok(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().replace("=", " "))


def diff_changes(files: list[dict]) -> dict:
    """Net flag tokens added/removed and pytest-xdist added, over a commit's or pull's ``files`` (docs ignored)."""
    added_par, removed_par, added_ser, removed_ser = [], [], [], []
    xdist_added = False
    for f in files or []:
        name = f.get("filename") or ""
        if DOC_FILE.search(name):
            continue
        add, rem = _patch_lines(f.get("patch"))
        a_tok = [(p, _norm_tok(t), ln) for ln in add for p, t in flag_tokens(ln)]
        r_tok = [(p, _norm_tok(t), ln) for ln in rem for p, t in flag_tokens(ln)]
        for p, t, ln in a_tok:
            hit = next((x for x in r_tok if x[0] == p and x[1] == t), None)
            if hit:
                r_tok.remove(hit)
                continue
            (added_par if p == "parallel" else added_ser).append({"file": name, "token": t, "line": ln[:300]})
        for p, t, ln in r_tok:
            (removed_par if p == "parallel" else removed_ser).append({"file": name, "token": t, "line": ln[:300]})
        if DEP_FILE.search(name):
            a = sum(1 for ln in add if re.search(r"pytest[-_]xdist", ln, re.I))
            r = sum(1 for ln in rem if re.search(r"pytest[-_]xdist", ln, re.I))
            if a > r:
                xdist_added = True
    return {"added_parallel": added_par, "removed_parallel": removed_par, "added_serial": added_ser,
            "removed_serial": removed_ser, "xdist_added": xdist_added}


def diff_rules(ch: dict) -> list[str]:
    out = []
    if ch["added_parallel"] or ch["xdist_added"]:
        out.append("P2-diff")
    if ch["added_serial"] and (ch["removed_parallel"] or any(_default_parallel_serial(x["token"]) for x in ch["added_serial"])):
        out.append("P4")
    return out


# ---------------------------------------------------------------------------------------------- runner line (gate M2)
WRAP = [r"timeout\s+\S+\s+", r"uv\s+run\s+", r"python3?\s+-m\s+", r"pnpm\s+(?:\S+\s+)*?exec\s+", r"npx\s+",
        r"npm\s+run\s+"]


def command_word(line: str) -> tuple[str, str]:
    """(word, rest) after removing the wrappers ``timeout <d>``, ``uv run``, ``python -m``, ``pnpm ... exec``, ``npx``."""
    s = line.strip()
    changed = True
    while changed:
        changed = False
        for w in WRAP:
            m = re.match(w, s)
            if m:
                s = s[m.end():]
                changed = True
    parts = s.split(None, 1)
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


def runner_of(line: str) -> str | None:
    word, rest = command_word(line)
    if word in ("pytest", "py.test"):
        return "pytest"
    if word in ("python", "python3") and re.match(r"manage\.py\s+test\b", rest):
        return "django"
    if word == "manage.py" or word.endswith("/manage.py"):
        return "django" if rest.startswith("test") else None
    if word == "go" and rest.startswith("test"):
        return "go"
    if word in ("jest", "mocha", "vitest"):
        return word
    if word == "node" and rest.startswith("--test"):
        return "node"
    return None


def pick_runner_check(step: dict, kind: str) -> dict | None:
    """The timed step's ``checks[]`` entry with ``serial: true`` whose command word is the runner of ``kind``."""
    for c in step.get("checks") or []:
        if c.get("serial") and runner_of(c.get("line") or "") == kind:
            return c
    return None


# ---------------------------------------------------------------------------------------------- levels (§4)
def dep_names(text: str) -> set[str]:
    """Lower-case package names that look like dependencies in a dependency file's text."""
    return set(m.group(1).lower() for m in re.finditer(r"(?<![\w.-])([A-Za-z][\w.-]*)", text or ""))


def strip_comments(text: str) -> str:
    """Dependency text without ``#`` comments (requirements, TOML, Pipfile, setup.cfg); a comment is not a dependency."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in (text or "").splitlines())


def has_dep(texts: list[str], name: str) -> bool:
    pat = re.compile(r"(?<![\w-])" + re.escape(name).replace(r"\-", "[-_]") + r"(?![\w-])", re.I)
    return any(pat.search(strip_comments(t)) for t in texts)


ORMS = ["SQLAlchemy", "Django", "psycopg", "psycopg2", "asyncpg", "Prisma", "TypeORM", "Knex", "Sequelize",
        "drizzle-orm", "pgx", "gorm", "sqlx"]


def orms_in(dep_texts: list[str]) -> list[str]:
    out = []
    for o in ORMS:
        if o == "pgx":
            if any(re.search(r"jackc/pgx", t or "") for t in dep_texts):
                out.append(o)
        elif o == "gorm":
            if any(re.search(r"gorm\.io/gorm|jinzhu/gorm", t or "") for t in dep_texts):
                out.append(o)
        elif o == "sqlx":
            if any(re.search(r"jmoiron/sqlx|(?<![\w-])sqlx(?![\w-])", t or "") for t in dep_texts):
                out.append(o)
        elif o == "Prisma":
            if any(re.search(r"[\"'](?:@prisma/client|prisma)[\"']", t or "") for t in dep_texts):
                out.append(o)
        elif has_dep(dep_texts, o):
            out.append(o)
    return out


def has_testcontainers(dep_texts: list[str]) -> bool:
    return any(re.search(r"testcontainers", t or "", re.I) for t in dep_texts)


DSM = re.compile(r"DJANGO_SETTINGS_MODULE['\"]?\s*[:=,]\s*['\"]?([\w.]+)")


def django_project(dep_texts: list[str], dsm_texts: list[str], tree_paths: list[str]) -> tuple[bool, str]:
    """Django project (§2a): django dependency, DJANGO_SETTINGS_MODULE set, or a manage.py in the tree."""
    if has_dep(dep_texts, "django"):
        return True, "django dependency"
    for t in dsm_texts:
        if DSM.search(t or ""):
            return True, "DJANGO_SETTINGS_MODULE set"
    if any(p == "manage.py" or p.endswith("/manage.py") for p in tree_paths):
        return True, "manage.py in tree"
    return False, ""


def addopts_lines(config_texts: dict[str, str]) -> list[tuple[str, int, str]]:
    """(file, line number, text) of every ``addopts`` line (and its continuation lines) in pytest config files."""
    out = []
    for path, text in config_texts.items():
        lines = (text or "").splitlines()
        for i, ln in enumerate(lines):
            if re.match(r"\s*addopts\s*=", ln):
                out.append((path, i + 1, ln))
                j = i + 1
                while j < len(lines) and (lines[j].startswith((" ", "\t")) or lines[j].strip().startswith(("\"", "'", "]"))):
                    if lines[j].strip():
                        out.append((path, j + 1, "addopts " + lines[j]))
                    j += 1
    return out


def level_for(kind: str, is_django: bool, dep_texts: list[str]) -> str:
    if kind == "django":
        return "built-in"
    if kind == "pytest" and is_django:
        dj = has_dep(dep_texts, "pytest-django")
        xd = has_dep(dep_texts, "pytest-xdist")
        if dj and xd:
            return "plugin-installed"
        if dj:
            return "plugin-partial"
        return "plugin-not-installed"
    return "none"


def state_for(level: str, kind: str, runner_line: str, addopts: list[tuple[str, int, str]],
              settings_text: str | None) -> tuple[str, str]:
    """(state, why). ``off`` needs the runner line without the option (the evidence line is attached by the caller)."""
    if level == "none":
        return "n/a", "no free per-worker option for this stack"
    if kind == "django":
        if any(p == "parallel" for p, _ in flag_tokens(runner_line)):
            return "on", "--parallel on the timed command"
        if settings_text is None:
            return "unknown", "settings module not fetched"
        if re.search(r"\bparallel\b", settings_text, re.I) or re.search(r"\bTEST_RUNNER\b", settings_text):
            return "unknown", "settings mention parallel or TEST_RUNNER"
        return "off", "manage.py test without --parallel; no parallel default or TEST_RUNNER in settings"
    on_line = any(p == "parallel" for p, _ in flag_tokens(runner_line))
    on_cfg = [a for a in addopts if any(p == "parallel" for p, _ in flag_tokens(a[2]))]
    if on_line or on_cfg:
        return "on", "-n/--numprocesses present"
    return "off", "no -n/--numprocesses in the timed command or addopts"


PER_TEST = re.compile(r"\b(TransactionTestCase|TestCase|django_db|rollback|begin_nested|transaction\.atomic|"
                      r"create_database|drop_database)\b")


def per_test_notes(files: dict[str, str]) -> list[dict]:
    out = []
    for path, text in files.items():
        for i, ln in enumerate((text or "").splitlines()):
            if PER_TEST.search(ln):
                out.append({"file": path, "line": i + 1, "text": ln.strip()[:200]})
                if len(out) >= 20:
                    return out
    return out


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
