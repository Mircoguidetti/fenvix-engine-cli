"""Level 0 controls shared by every runner shell: the pytest plugin (``plugin.py``) and the runner-neutral driver
(``runners/``) call the same functions, in the same order.

What is here: the option table (``OPTIONS``: the same ``--det*`` options for pytest and for ``python -m detpy
<runner>``), the controls (``controls_of``), the epoch (``epoch_for``: the HEAD commit time, kept by the cache), the
hash seed, the installation of the clock, seeds, file-system order and bytecode controls (``install_controls``), the
network control and the recorder (``open_session``), the per-test bracket (``begin_test`` / ``end_test``), the trace
header (``trace_meta``) and the teardown (``uninstall``). What stays in each shell: how its own plugins are blocked
or kept, its own bytecode (pytest's assertion rewrite), its hooks.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import sys

from . import (__version__, _core, _machine, _sites, _state, clock, envobs, fsorder, fstime, network, osstate, reexec,
               seeds, sqlvirt, uncontrolled)
from ._patch import Patcher

CONTROLS = ("order", "seeds", "hashseed", "bytecode", "time", "fs", "net", "env", "tz", "locale", "os")
DEFAULT_TZ = "UTC"
DEFAULT_LOCALE = "C.UTF-8"
# fallbacks when the default locale does not exist on the machine (macOS has no C.UTF-8 before 13)
LOCALE_FALLBACKS = ("C.UTF-8", "C.utf8", "en_US.UTF-8", "C")
# the locale variables the pin sets (LC_ALL wins over every LC_* and LANG; LANGUAGE is gettext's own list)
LOCALE_VARS = ("LC_ALL", "LANG")
# engine-internal variables: not inputs of the code under test (their effects are recorded as their own inputs)
ENGINE_ENV_PREFIXES = ("DETPY_", "PYTEST_XDIST_")

# CI-volatile environment (design A, 2026-11-20): variables whose values change from run to run of the same job by
# construction, never because the project changed.
# * pinned: under --det (env control) they are set to these values before the tests run, in this process and in the
#   re-executed one (their children inherit them): run and attempt ids, job and runner names, the host name.
VOLATILE_PINNED = {
    "GITHUB_RUN_ID": "0", "GITHUB_RUN_NUMBER": "0", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "fenvix",
    "RUNNER_NAME": "fenvix-runner", "RUNNER_TRACKING_ID": "fenvix", "HOSTNAME": "localhost",
}
# * volatile: their values stay (they name paths that must exist, or tokens a tool needs), but they are never run
#   inputs and reads of them record no value: temp and workspace paths, per-step files, CI tokens and endpoints,
#   session plumbing. FENVIX_VOLATILE_ENV=NAME,PREFIX*,... adds a project's own (a per-run output path).
VOLATILE_KEPT = (
    "RUNNER_TEMP", "RUNNER_WORKSPACE", "RUNNER_TOOL_CACHE", "GITHUB_WORKSPACE", "GITHUB_ENV", "GITHUB_PATH",
    "GITHUB_OUTPUT", "GITHUB_STATE", "GITHUB_STEP_SUMMARY", "GITHUB_EVENT_PATH", "GITHUB_ACTION",
    "GITHUB_ACTION_PATH", "GITHUB_ACTIONS_STEP_DEBUG", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_RUNTIME_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_RESULTS_URL", "ACTIONS_CACHE_URL",
    "ACTIONS_ORCHESTRATION_ID", "TMPDIR", "TEMP", "TMP", "PWD", "OLDPWD", "_", "SHLVL", "INVOCATION_ID",
    "JOURNAL_STREAM", "SSH_AUTH_SOCK", "SSH_CLIENT", "SSH_CONNECTION", "SSH_TTY", "TERM_SESSION_ID",
    "WINDOWID", "XDG_SESSION_ID", "XDG_RUNTIME_DIR", "SYSTEMD_EXEC_PID", "FENVIX_VOLATILE_ENV",
    "SUDO_USER", "SUDO_UID", "SUDO_GID", "SUDO_COMMAND", "SUDO_HOME",  # session of a sudo wrapper
)
# the proxy variables the closed network sets for children (network._child_env, network.PROXY_KEYS)
PROXY_ENV = frozenset(("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy", "NO_PROXY",
                       "no_proxy"))
PINNED_CPU_COUNT = 2  # os.cpu_count & co. under --det: CI runners differ in CPUs (the engine keeps the real one)
PINNED_HOSTNAME = "localhost"  # socket.gethostname / platform.node / os.uname().nodename under --det (resolvable)


def volatile_env_patterns() -> tuple:
    """The volatile variables: the built-in ones and FENVIX_VOLATILE_ENV's (NAME or PREFIX*), as (exact, prefixes)."""
    extra = [x.strip() for x in os.environ.get("FENVIX_VOLATILE_ENV", "").split(",") if x.strip()]
    exact = set(VOLATILE_PINNED) | set(VOLATILE_KEPT) | {x for x in extra if not x.endswith("*")}
    prefixes = tuple(x[:-1] for x in extra if x.endswith("*"))
    return frozenset(exact), prefixes


def is_volatile_env(name: str, patterns=None) -> bool:
    exact, prefixes = patterns or volatile_env_patterns()
    return name in exact or (bool(prefixes) and name.startswith(prefixes)) or name.startswith(ENGINE_ENV_PREFIXES)


def pin_volatile_env(controls) -> list:
    """Design A: set the pinned CI-volatile variables that are present (``VOLATILE_PINNED``) to their fixed values,
    before the hash-seed re-exec (the new process starts with them) and in this process. Returns their names."""
    if "env" not in controls:
        return []
    done = []
    for k, v in VOLATILE_PINNED.items():
        if k in os.environ and os.environ.get(k) != v:
            os.environ[k] = v
            done.append(k)
    return done
PATCHER = Patcher()
INFRA_PREFIXES = ("_pytest", "pytest", "pluggy", "detpy", "_hypothesis_pytestplugin", "xdist", "execnet")
# top-level packages of the running shell's plugins (pytest plugins): test infrastructure, never rebound to the
# virtual clock (set by the shell)
INFRA_PACKAGES: set = set()
FALLBACK_EPOCH = "2025-01-01T00:00:00+00:00"
EPOCH_SOURCE = {"source": "default"}


class UsageError(Exception):
    """A wrong ``--det*`` option (the pytest shell raises it as ``pytest.UsageError``)."""


# The --det* options: (flags, keyword arguments of argparse's add_argument / pytest's addoption).
OPTIONS: list[tuple[tuple[str, ...], dict]] = [
    (("--det",), dict(action="store_true", default=False, help="enable deterministic execution (Level 0)")),
    (("--det-seed",), dict(type=int, default=None, metavar="N",
                           help="reproducible shuffle of the test order and seed of every generator (default: fixed "
                                "order, seed 0)")),
    (("--det-order",), dict(default=None, metavar="FILE",
                            help="run exactly the test ids listed in FILE (one per line), in that order; other tests "
                                 "are deselected. With --det-seed the seed still drives every generator, not the "
                                 "order (replay bundles written by `detpy repro`)")),
    (("--det-trace",), dict(default=None, metavar="PATH",
                            help="where to write the execution trace (default: <rootdir>/.detpy/trace.jsonl)")),
    (("--det-compare",), dict(default=None, metavar="TRACE",
                              help="compare fingerprints with a previous trace and report tests not covered by "
                                   "Level 0")),
    (("--det-record",), dict(action="store_true", default=False,
                             help="allow external network access and record responses into the cassette")),
    (("--det-cassette",), dict(default=None, metavar="PATH",
                               help="network cassette (default: <rootdir>/.detpy/cassette.json); replayed when "
                                    "present")),
    (("--det-cassette-max-age",), dict(type=float, default=0.0, metavar="DAYS",
                                       help="do not replay recordings older than DAYS (or without a recording date): "
                                            "those tests meet the closed network and must be re-recorded with "
                                            "--det-record (default 0: no limit)")),
    (("--det-allow-host",), dict(action="append", default=[], metavar="HOST",
                                 help="external host that may be reached (repeatable)")),
    (("--det-epoch",), dict(default="auto", metavar="ISO",
                            help="wall-clock value at the start of every test (default auto: the commit time of the "
                                 f"checked-out git HEAD, else {FALLBACK_EPOCH})")),
    (("--det-tick",), dict(type=int, default=1000, metavar="NS",
                           help="nanoseconds the virtual clock advances on every read (default 1000)")),
    (("--det-tick-adapt",), dict(type=int, default=8, metavar="N",
                                 help="double the tick after N consecutive clock reads with no other event (0 = "
                                      "fixed tick)")),
    (("--det-sleep",), dict(choices=("virtual", "real"), default="virtual",
                            help="virtual: time.sleep only advances the clock; real: it also waits")),
    (("--det-disable",), dict(default="", metavar="LIST",
                              help=f"comma separated controls to turn off: {','.join(CONTROLS)}")),
    (("--det-tz",), dict(default=os.environ.get("FENVIX_TZ") or DEFAULT_TZ, metavar="ZONE",
                         help=f"time zone every test runs in (TZ, applied before the interpreter re-executes; default "
                              f"$FENVIX_TZ, else {DEFAULT_TZ}). 'keep' keeps the machine's: it is then recorded as a "
                              f"run input, and `fenvix verify` reports runs with different zones as divergent")),
    (("--det-locale",), dict(default=os.environ.get("FENVIX_LOCALE") or DEFAULT_LOCALE, metavar="NAME",
                             help=f"locale every test runs in (LC_ALL and LANG; LANGUAGE removed; default "
                                  f"$FENVIX_LOCALE, else {DEFAULT_LOCALE}, else the first of "
                                  f"{', '.join(LOCALE_FALLBACKS[1:])} that exists). 'keep' keeps the machine's "
                                  "(recorded as a run input)")),
    (("--det-entropy",), dict(default=None, choices=("control", "observe"), metavar="control|observe",
                              help="OS entropy (os.urandom, os.getrandom, ssl.RAND_bytes, uuid4, secrets): 'control' "
                                   "(the default) seeds it per test from --det-seed; 'observe' keeps the real entropy "
                                   "and records every draw (a test that draws it is never identical; NOT seeded: for "
                                   "crypto tests)")),
    (("--det-urandom",), dict(action="store_true", default=False,
                              help="OS entropy controlled (the default since 2026-11-21; kept for older command "
                                   "lines: see --det-entropy)")),
    (("--det-keep-aslr",), dict(action="store_true", default=False,
                                help="do not disable address space randomisation when re-executing")),
    (("--det-no-reexec",), dict(action="store_true", default=False,
                                help="never re-exec the interpreter to fix PYTHONHASHSEED")),
    (("--det-max-events",), dict(type=int, default=10_000, metavar="N",
                                 help="events stored verbatim per test (the fingerprint always covers all of them)")),
    (("--det-outcomes",), dict(default=None, metavar="PATH",
                               help="write {nodeid: outcome} as JSON (works without --det; used by the harness)")),
    (("--det-cache",), dict(default=None, metavar="DIR",
                            help="cache with proof (needs --det, Python 3.12+): reuse a test's previous result from "
                                 "DIR only when every input it depended on (code executed, files read, environment "
                                 "variables read, runtime, configuration) is unchanged; failures are never reused; "
                                 "prints a receipt")),
    (("--det-cache-verify",), dict(type=float, default=0.0, metavar="FRACTION",
                                   help="run this random fraction of the reusable tests anyway and compare with the "
                                        "cached result")),
    (("--det-cache-dists",), dict(action="store_true", default=False,
                                  help="with --det-cache (PROTOTYPE): installed distributions enter a test's key one "
                                       "by one (those it loaded, read or queried) instead of as one digest of the "
                                       "whole environment")),
    (("--det-cache-no-follow",), dict(action="store_true", default=False,
                                      help="with --det-cache: never cache a test that starts a process (default: the "
                                           "processes run under strace and their files, program and environment "
                                           "become inputs of the test)")),
    (("--det-cache-max-age",), dict(type=float, default=30.0, metavar="DAYS",
                                    help="with --det-cache: never reuse a result recorded more than DAYS ago on the "
                                         "real clock (default 30; 0 = no limit). Bounds real-clock reads detpy "
                                         "cannot see (C code such as TLS validity)")),
    (("--det-cache-epoch-window",), dict(type=float, default=30.0, metavar="DAYS",
                                         help="with --det-cache and --det-epoch=auto: keep the cache's epoch while the "
                                              "HEAD commit time is at most DAYS later (default 30), so tests that read "
                                              "the clock are reusable across commits")),
    (("--det-cache-shared",), dict(default=None, metavar="DIR",
                                   help="with --det-cache: a store shared with other sessions and machines (a "
                                        "directory every job sees; also DETPY_CACHE_SHARED). Candidates are fetched "
                                        "before the reuse decision and checked like local entries; this session's "
                                        "entries are pushed at the end (by the controller under -n)")),
    (("--det-cache-keys",), dict(default=None, metavar="PATH",
                                 help="with --det-cache (input of the culprit finder): also write every test's inputs, "
                                      "resolved to names and digests, to PATH as JSON, for every outcome (failures "
                                      "included); nothing else changes")),
    (("--det-cache-receipts",), dict(default=None, metavar="PATH",
                                     help="where to write the per-test receipts (JSON lines; default "
                                          "DIR/receipts.jsonl)")),
]


CONFIG_KEYS = {"seed": "--det-seed", "tz": "--det-tz", "locale": "--det-locale", "epoch": "--det-epoch",
               "tick": "--det-tick", "cassette": "--det-cassette", "cassette_max_age": "--det-cassette-max-age",
               "disable": "--det-disable", "trace": "--det-trace"}
CONFIG_FLAGS = {"urandom": "--det-urandom", "keep_aslr": "--det-keep-aslr"}
CONFIG_KEYS["entropy"] = "--det-entropy"


def entropy_controlled(ns) -> bool:
    """Coordinator decision 2026-11-21 (the frozen exam's F-01.random.pinned): OS entropy is controlled by default
    under --det, like Node's crypto; ``--det-entropy=observe`` keeps it real and observed."""
    if getattr(ns, "det_urandom", False):  # what the [entropy] hint names: it controls in every case
        return True
    return getattr(ns, "det_entropy", None) != "observe"


def config_args(root: str | None, given: list) -> list:
    """``--det`` options from the project's configuration (audit G-1536): ``FENVIX_DET=1`` in the environment, or a
    ``[tool.fenvix]`` table in ``pyproject.toml`` (``det = true``, ``seed``, ``tz``, ``locale``, ``epoch``, ``tick``,
    ``cassette``, ``cassette_max_age``, ``disable``, ``trace``, ``urandom``, ``keep_aslr``, ``allow_hosts``). Returns
    the arguments to add in front of ``given`` (nothing when neither turns ``--det`` on, and never an option
    ``given`` already has: the command line wins)."""
    table: dict = {}
    path = os.path.join(root or os.getcwd(), "pyproject.toml")
    if os.path.isfile(path):
        try:
            import tomllib

            with open(path, "rb") as f:
                table = (tomllib.load(f).get("tool") or {}).get("fenvix") or {}
        except Exception:  # an unreadable pyproject: no configuration from it
            table = {}
    env_on = os.environ.get("FENVIX_DET", "").strip().lower() in ("1", "true", "yes", "on")
    if not (env_on or table.get("det") is True or "--det" in given):
        return []
    have = {a.split("=", 1)[0] for a in given}
    out = [] if "--det" in have else ["--det"]
    for key, flag in CONFIG_KEYS.items():
        if key in table and flag not in have:
            out.append(f"{flag}={table[key]}")
    for key, flag in CONFIG_FLAGS.items():
        if table.get(key) is True and flag not in have:
            out.append(flag)
    if "--det-allow-host" not in have:
        out += [f"--det-allow-host={h}" for h in table.get("allow_hosts") or []]
    return out


def controls_of(disable: str) -> frozenset:
    """The active controls: every control but the ``--det-disable`` ones."""
    off = {c.strip() for c in (disable or "").split(",") if c.strip()}
    unknown = off - set(CONTROLS)
    if unknown:
        raise UsageError(f"--det-disable: unknown control(s) {sorted(unknown)}; known: {CONTROLS}")
    return frozenset(CONTROLS) - off


def skip_module(name: str, mod) -> bool:
    """Modules whose references to real clock objects must not be rebound.

    Besides the standard library and detpy itself, the running shell's plugins (``INFRA_PACKAGES``: pytest plugins
    such as pytest-benchmark, pytest-timeout) are test infrastructure: they keep real timers, otherwise
    time-calibrated loops would spin on virtual time.
    """
    top = name.split(".", 1)[0]
    if top in INFRA_PREFIXES or top.startswith("pytest_") or top in INFRA_PACKAGES:
        return True
    f = getattr(mod, "__file__", None)
    if not f:
        return True  # builtins / namespace packages
    kind, _ = _sites._classify(f)
    return kind != _sites._USER


def head_commit_time(root: str) -> int | None:
    """Commit time (seconds) of the git HEAD containing ``root``, or None."""
    import subprocess

    try:
        p = subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=root, capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout.strip()
    return int(out) if p.returncode == 0 and out.isdigit() else None


def epoch_ns(text: str, root: str) -> int:
    """--det-epoch: an ISO time, or "auto" = the HEAD commit time (T2).

    A test written at a commit may take dates before the commit as past; a fixed
    epoch older than the commit made such tests fail only under --det. The commit
    time is a pure function of the checkout and never later than the real time.
    """
    if text == "auto":
        ct = head_commit_time(root)
        if ct is not None:
            EPOCH_SOURCE.update(source="git HEAD commit time", value=ct)
            return ct * 1_000_000_000
        EPOCH_SOURCE.update(source="fixed default (no git HEAD)", value=FALLBACK_EPOCH)
        text = FALLBACK_EPOCH
    else:
        EPOCH_SOURCE.update(source="--det-epoch", value=text)
    return parse_epoch(text)


def epoch_for(ns, root: str) -> int:
    """The session's epoch. Under ``--det-cache`` with ``--det-epoch=auto`` it is the cache's epoch: the HEAD commit
    time when the cache took it, kept while HEAD is at most ``--det-cache-epoch-window`` days later. The epoch is a
    configuration input of every test that reads the clock; one that moved at every commit made those tests (and,
    through a clock read at import time, every test) unreusable from one commit to the next."""
    ns_epoch = epoch_ns(ns.det_epoch, root)
    cache = getattr(ns, "det_cache", None)
    if cache and ns.det_epoch == "auto" and EPOCH_SOURCE.get("source") == "git HEAD commit time":
        window = getattr(ns, "det_cache_epoch_window", 30.0)
        kept = _core.cache_epoch(cache, ns_epoch, int(window * 86400 * 1_000_000_000))  # Rust: identity.rs
        if kept != ns_epoch:
            EPOCH_SOURCE.update(source="cache epoch (HEAD commit time when the cache took it)",
                                value=kept // 1_000_000_000, head=ns_epoch // 1_000_000_000)
        return kept
    return ns_epoch


def parse_epoch(text: str) -> int:
    try:
        d = _dt.datetime.fromisoformat(text)
    except ValueError as e:
        raise UsageError(f"--det-epoch: {e}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    delta = d - _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def hashseed_variants() -> int:
    """How many hash seeds the ``--det-seed`` values share (audit G-1531): ``--det-seed=N`` runs under
    ``PYTHONHASHSEED = N mod K`` (K = ``$FENVIX_HASHSEEDS``, default 8). Every seed keeps its own order and generator
    seeds; an exploration over many seeds precompiles the libraries K times instead of once per seed (MEASURED by
    the audit: 13 s and 27 MB to 246 MB per new seed)."""
    try:
        return max(1, min(4294967296, int(os.environ.get("FENVIX_HASHSEEDS", "8"))))
    except ValueError:
        return 8


def hashseed(seed: int | None) -> str:
    return str((seed or 0) % hashseed_variants())


def hashseed_value() -> str:
    return str(_state.STATE.config.seed % hashseed_variants())


def _locale_exists(name: str) -> bool:
    import locale

    try:
        prev = locale.setlocale(locale.LC_CTYPE)
        try:
            locale.setlocale(locale.LC_CTYPE, name)
        finally:
            locale.setlocale(locale.LC_CTYPE, prev)
        return True
    except locale.Error:
        return False


PINNED: dict = {}


def pin_tz_locale(ns, controls) -> None:
    """The time zone and locale controls: set TZ, LC_ALL and LANG (and remove LANGUAGE) in this process's environment
    before the hash-seed re-exec, so the re-executed interpreter starts in them (its C library reads them at start
    up), and apply them in this process too (``time.tzset``, ``setlocale(LC_CTYPE)``) when there is no re-exec.
    With 'keep' (or ``--det-disable=tz|locale``) the machine's values stay and are recorded as run inputs."""
    tz = getattr(ns, "det_tz", None) or DEFAULT_TZ
    if "tz" in controls and tz != "keep":
        os.environ["TZ"] = tz
        try:
            import time

            time.tzset()
        except AttributeError:  # pragma: no cover - not on POSIX
            pass
        PINNED["tz"] = tz
    loc = getattr(ns, "det_locale", None) or DEFAULT_LOCALE
    if "locale" in controls and loc != "keep":
        # the same choice in the re-executed process (same machine, same candidates)
        cands = (loc,) + (LOCALE_FALLBACKS if loc == DEFAULT_LOCALE else ())
        chosen = next((c for c in cands if _locale_exists(c)), None)
        if chosen is None:
            raise UsageError(f"--det-locale: locale {loc!r} does not exist on this machine")
        for v in LOCALE_VARS:
            os.environ[v] = chosen
        os.environ.pop("LANGUAGE", None)
        try:
            import locale

            locale.setlocale(locale.LC_CTYPE, chosen)
        except Exception:  # pragma: no cover - checked above
            pass
        PINNED["locale"] = chosen


def _tz_input() -> str:
    if "tz" in PINNED:
        return f"{PINNED['tz']} (pinned)"
    import time

    ident = _core.tz_locale_identity(os.environ)
    return f"TZ={os.environ.get('TZ', '<unset>')} tzname={','.join(time.tzname)} zone={_digest_text(json.dumps(ident, sort_keys=True, default=str))} (not pinned)"


def _locale_input() -> str:
    if "locale" in PINNED:
        return f"{PINNED['locale']} (pinned)"
    import locale

    vals = {k: os.environ.get(k) for k in ("LC_ALL", "LC_CTYPE", "LC_TIME", "LC_NUMERIC", "LC_COLLATE",
                                          "LC_MONETARY", "LC_MESSAGES", "LANG", "LANGUAGE") if k in os.environ}
    return f"{sorted(vals.items())} ctype={locale.setlocale(locale.LC_CTYPE)} (not pinned)"


def _digest_text(t: str) -> str:
    return _core.digest(t.encode("utf-8", "surrogateescape"))[:16]


def env_inputs(skip=()) -> dict:
    """One run input per environment variable (``env:NAME``: a digest of NAME=value, so secrets never reach the
    trace), engine-internal and CI-volatile variables excepted (``VOLATILE_PINNED``, ``VOLATILE_KEPT``,
    ``FENVIX_VOLATILE_ENV``). The verifier reports a test that read one whose value differs as ``input-differs``."""
    out = {}
    # the engine's own read (os.environ._data, decoded as os.environ does): not an enumeration by the code under
    # test, which the cache's and the env control's wrappers of os.environ would record (a runner shell writes its
    # trace header while the capture is active: every test then depended on the whole environment)
    e = os.environ
    data = getattr(e, "_data", None)
    items = list(e.items()) if data is None else [(e.decodekey(k), e.decodevalue(v)) for k, v in dict.items(data)]
    patterns = volatile_env_patterns()
    for k, v in items:
        if k.startswith(ENGINE_ENV_PREFIXES) or is_volatile_env(k, patterns) or k in skip:  # engine's, CI-volatile
            continue
        # a name or value that is not valid UTF-8 (surrogate-escaped) is spelled with its bytes escaped: the trace
        # is JSON, and its digest still covers the exact bytes
        name = os.fsencode(k).decode("utf-8", "backslashreplace")
        out[f"env:{name}"] = _core.digest(os.fsencode(k) + b"=" + os.fsencode(v))[:16]
    return out


# G-0168: test modules pytest's assertion rewrite compiled from source in this process because its cache missed. A
# process that compiles them allocates what one that loads them does not, so id()-dependent behaviour (the order of a
# set of plain objects) can differ between such a run and a later one, even with ASLR off. The process that starts a
# --det run writes them into the cache before the re-exec (plugin.prewarm_rewrite_cache); what is still compiled here
# (a module the walk did not find, a rewriter patched by a plugin, a run without re-exec) is a run input, so the
# verifier never calls such a run identical to a warm one. "workers": the sum the xdist controller received.
REWRITE = {"cold": 0, "workers": 0}


def _rewrite_input() -> str:
    n = REWRITE["cold"] + REWRITE["workers"]
    return f"; test modules rewritten from source in this run (cold rewrite cache: {n})" if n else ""


def run_inputs(net_mode, runner: str, runner_version) -> dict:
    """Every input of the run Level 0 controls or observes, as text: written in the trace header (``inputs``) and
    compared by the verifier (``crates/detpy-core/src/verify.rs``), which reports two runs whose inputs differ as
    divergent with the first differing input named. A control that is off is recorded as off, never left out."""
    cfg = _state.STATE.config
    c = cfg.controls
    cassette = cfg.cassette_path
    try:
        cas = _digest_text(open(cassette, "rb").read().decode("latin-1")) if cassette and os.path.exists(cassette) else "none"
    except OSError:
        cas = "unreadable"
    inputs = {
        "runtime": f"{platform.python_implementation()} {platform.python_version()} {sys.platform} "
                   f"{platform.machine()}",
        "runner": f"{runner} {runner_version or ''}".strip(),
        "hashseed": os.environ.get("PYTHONHASHSEED") or "<random>",
        "seed": str(cfg.seed) if "seeds" in c else f"{cfg.seed} (seeds control off)",
        "shuffle": "yes" if cfg.shuffle else "no",
        "clock": (f"virtual epoch_ns={cfg.epoch_ns} tick_ns={cfg.tick_ns} adapt={cfg.tick_adapt} sleep={cfg.sleep}"
                  if "time" in c else "real (time control off)"),
        "tz": _tz_input(),
        "locale": _locale_input(),
        "env": "recorded (every os.environ read is an event)" if "env" in c else "reads not recorded (env control off)",
        "network": (f"{net_mode} allow={','.join(sorted(cfg.allow_hosts))} cassette={cas}" if "net" in c
                    else "open (net control off)"),
        "fs": "sorted" if "fs" in c else "real (fs control off)",
        "entropy": "controlled" if cfg.control_urandom else "observed",
        "bytecode": ("precompiled" if reexec.bytecode_active(hashseed_value()) else "default") + _rewrite_input(),
        "aslr": {True: "off", False: "on", None: "unknown"}[reexec.aslr_disabled()],
        "order": "fixed" if "order" in c else "runner order (order control off)",
        "os": osstate.input_text() if "os" in c else "real (os control off)",
    }
    # the closed network replaces the proxy variables (children get the discard port, network._child_env): while it is
    # closed they are its part, not inputs; while recording (the real network) they are inputs
    closed = "net" in c and not cfg.record_net
    inputs.update(env_inputs(skip=PROXY_ENV if closed else ()))
    return inputs


def reexec_status(ns, controls, root: str, block: list[str], before_exec=None) -> str:
    """The hash-seed re-exec (``reexec``): exec the same command line again under the fixed hash seed (and ASLR off,
    deterministic bytecode) when needed and possible; does not return then. Returns the status line otherwise.
    ``before_exec`` runs just before the exec (pytest restores its captured file descriptors)."""
    pin_tz_locale(ns, controls)
    pin_volatile_env(controls)
    if "hashseed" not in controls:
        return "not-needed"
    want_bytecode = "bytecode" in controls
    need = reexec.plan(hashseed(ns.det_seed), not ns.det_keep_aslr, want_bytecode)
    if not any(need.values()):
        return "ok"
    ok, why = reexec.can_reexec()
    if ok and not ns.det_no_reexec:
        if before_exec is not None:
            before_exec()
        reexec.reexec(hashseed(ns.det_seed), not ns.det_keep_aslr, want_bytecode, root, block)  # no return
    reason = "--det-no-reexec" if ns.det_no_reexec else why
    if need["hashseed"]:
        return f"PYTHONHASHSEED not fixed ({reason})"
    missing = [k for k in ("aslr", "bytecode") if need[k]]
    return f"hash seed fixed; not applied: {','.join(missing)} ({reason})"


def make_config(ns, root: str, controls) -> _state.Config:
    """The Level 0 configuration of the session (``_state.STATE.config``)."""
    cfg = _state.Config(
        seed=ns.det_seed or 0,
        shuffle=ns.det_seed is not None and not getattr(ns, "det_order", None),
        epoch_ns=epoch_for(ns, root),
        tick_ns=max(0, ns.det_tick),
        tick_adapt=max(0, ns.det_tick_adapt),
        sleep=ns.det_sleep,
        controls=controls,
        record_net=ns.det_record,
        allow_hosts=tuple(ns.det_allow_host),
        control_urandom=entropy_controlled(ns),
        max_events=ns.det_max_events,
    )
    cfg.cassette_max_age = getattr(ns, "det_cassette_max_age", 0.0) or 0.0
    _state.STATE.config = cfg
    return cfg


def install_controls(cfg: _state.Config, root: str | None) -> list:
    """Install the seeds, clock and file-system order controls (in this order). Returns the clock's rebound
    references."""
    _sites.refresh(root)
    controls = cfg.controls
    if "seeds" in controls:
        seeds.install(PATCHER, cfg.control_urandom)
    rebound: list = []
    if "time" in controls:
        rebound = clock.install(PATCHER, cfg.epoch_ns, cfg.tick_ns, skip_module, cfg.tick_adapt)
        fstime.install(PATCHER)
        sqlvirt.install(PATCHER)  # SQLite's 'now', CURRENT_TIMESTAMP, random(), randomblob() per connection
    if "fs" in controls:
        fsorder.install(PATCHER)
    if "env" in controls:
        pin_volatile_env(controls)  # no re-exec (or a shell that installs here): pin in this process
        envobs.install()
        pin_hostname(PATCHER)
        pin_cpu_count(PATCHER)
    if "os" in controls:
        osstate.install(PATCHER, cfg)  # after fstime: wraps its open
    uncontrolled.install(PATCHER)
    return rebound


def pin_hostname(patcher) -> None:
    """Design A: the host name is CI-volatile (each runner has its own): socket.gethostname, platform.node and
    os.uname().nodename answer ``PINNED_HOSTNAME`` under --det (``localhost``: it still resolves, to loopback)."""
    import platform
    import socket

    patcher.set(socket, "gethostname", lambda: PINNED_HOSTNAME)
    patcher.set(platform, "node", lambda: PINNED_HOSTNAME)
    real_uname = getattr(os, "uname", None)
    if real_uname is not None:
        def uname():
            r = real_uname()
            return os.uname_result((r.sysname, PINNED_HOSTNAME, r.release, r.version, r.machine))

        patcher.set(os, "uname", uname)
    try:  # platform.uname() caches the node it saw first
        cached = getattr(platform, "_uname_cache", None)
        if cached is not None:
            patcher.set(platform, "_uname_cache", cached._replace(node=PINNED_HOSTNAME))
    except Exception:
        pass


def pin_cpu_count(patcher) -> None:
    """Design A, same class as the host name: the CPU count differs between CI runners (pool sizes, chunking, a
    test that prints it). Under --det os.cpu_count, os.process_cpu_count, os.sched_getaffinity and
    multiprocessing.cpu_count answer ``PINNED_CPU_COUNT`` (affinity: CPUs 0..N-1). The engine's own work is sized on
    the real count (``_machine``, captured at import)."""
    import multiprocessing

    n = PINNED_CPU_COUNT
    patcher.set(os, "cpu_count", lambda: n)
    if hasattr(os, "process_cpu_count"):
        patcher.set(os, "process_cpu_count", lambda: n)
    if hasattr(os, "sched_getaffinity"):
        patcher.set(os, "sched_getaffinity", lambda pid: set(range(n)))
    patcher.set(multiprocessing, "cpu_count", lambda: n)


class real_cpu_count:
    """``with real_cpu_count():`` the engine's own planning (``-n auto``) reads the machine, not the pinned count."""

    def __enter__(self):
        import multiprocessing

        real = {"cpu_count": _machine._cpu_count, "process_cpu_count": _machine._process_cpu_count,
                "sched_getaffinity": _machine._sched_getaffinity}
        self.saved = [(os, k, getattr(os, k)) for k, v in real.items() if v is not None and hasattr(os, k)]
        self.saved.append((multiprocessing, "cpu_count", multiprocessing.cpu_count))
        for mod, k, _ in self.saved:
            setattr(mod, k, real[k] if mod is os else (lambda: _machine.cpu_count() or 1))
        return self

    def __exit__(self, *exc):
        for mod, k, v in self.saved:
            setattr(mod, k, v)
        return False


def hash_checked_imports(root: str) -> bool:
    """Review R-019b N5: under ``--det`` without the bytecode control (``--det-no-reexec``, ``--det-disable``, or no
    re-exec possible), validate the bytecode of every imported project module by its source's hash.

    With the control, the import system reads only the precompile's checked-hash pycs (``reexec``), which it
    validates by hash itself. Without it, it uses the project's ``__pycache__``, whose timestamp pycs are valid for
    ``(int(mtime), size)``: after a same-size edit checked out within the same second, the previous version's
    bytecode runs, and the proof key (from the source) pairs the new source with the old outcome (a cached false
    pass). ``SourceFileLoader.get_code`` is patched for project sources (under the rootdir, without the precompile's
    excluded names): a pyc is used only when it is a hash-based pyc of exactly the current source; otherwise the
    source is compiled and, when bytecode may be written, cached as a checked-hash pyc (which plain Python also
    validates by hash). The decision and the hash are in Rust (``_core.HashCheckedPycs``); this is the importlib
    interface. Other modules (libraries) keep the import system's own check."""
    try:
        import importlib.util
        from importlib import _bootstrap_external as be
        from importlib.machinery import SourceFileLoader

        variant = reexec._hash_variant()
        compile_bytecode, code_to_hash_pyc = be._compile_bytecode, be._code_to_hash_pyc
        cache_from_source, magic = importlib.util.cache_from_source, importlib.util.MAGIC_NUMBER
    except (ImportError, AttributeError):
        return False
    check = _core.HashCheckedPycs(os.path.abspath(root), list(reexec._EXCLUDE_NAMES), magic,
                                  int.from_bytes(magic, "little"), *(variant or (1, 3)))
    real = SourceFileLoader.get_code

    def get_code(self, fullname):
        path = self.get_filename(fullname)
        if variant is None:  # the Rust hash is not the interpreter's: never read a project pyc
            if not check.applies(path):
                return real(self, fullname)
            with open(path, "rb") as fh:
                return self.source_to_code(fh.read(), path)
        try:
            cfile = cache_from_source(path)
        except NotImplementedError:
            cfile = None
        got = check(path, cfile)
        if got is None:
            return real(self, fullname)
        source, source_hash, data = got
        if data is not None:
            try:
                return compile_bytecode(memoryview(data)[16:], name=fullname, bytecode_path=cfile, source_path=path)
            except (ImportError, EOFError):
                pass
        code = self.source_to_code(source, path)
        if cfile is not None and not sys.dont_write_bytecode:
            try:
                self._cache_bytecode(path, cfile, code_to_hash_pyc(code, source_hash, True))
            except NotImplementedError:
                pass
        return code

    PATCHER.set(SourceFileLoader, "get_code", get_code)
    return True


GITIGNORE = ("# written by fenvix: run state (traces, plans, repro work files) is not committed;\n"
             "# the network cassette is meant to be committed (it is reviewed like a fixture)\n"
             "*\n!.gitignore\n!cassette.json\n")


def sleep_label(cfg) -> str:
    """What ``time.sleep`` does (audit G-2198: "virtual" was printed with the time control off)."""
    return cfg.sleep if "time" in cfg.controls else "real (time control off)"


def ensure_state_dir(root: str) -> None:
    """``<root>/.detpy`` with a ``.gitignore`` that ignores everything but itself and the cassette (audit G-2207)."""
    d = os.path.join(root, ".detpy")
    # the same work in every run, whether the directory existed or not: what the engine allocates before the first
    # test decides the addresses the tests see (audit G-0168: a set of plain objects iterated in another order in
    # the first run of a fresh checkout than in every later run)
    try:
        if not os.path.isdir(d):
            os.mkdir(d)
        with open(os.path.join(d, ".gitignore"), "w") as f:
            f.write(GITIGNORE)
    except OSError:
        pass


def open_session(root: str, cassette: str | None, record: bool, allow_hosts, max_events: int) -> str | None:
    """The network control (with its cassette) and the recorder. Returns the network mode."""
    cfg = _state.STATE.config
    ensure_state_dir(root)
    cfg.cassette_path = cassette or os.path.join(root, ".detpy", "cassette.json")
    mode = None
    if "net" in cfg.controls:
        age = getattr(cfg, "cassette_max_age", 0.0)
        extra = {"max_age_days": age} if age else {}
        mode = network.install(PATCHER, record, cfg.cassette_path, allow_hosts, **extra)
    _state.STATE.recorder = _core.Recorder(max_events=max_events)
    return mode


def begin_test(nodeid: str, index: int) -> None:
    """A test starts (it runs, it is not reused): the recorder's bracket and every per-test control."""
    st = _state.STATE
    controls = st.config.controls
    st.recorder.begin_test(nodeid, index)
    _state.reset_threads()
    uncontrolled.start_test()
    if "os" in controls:
        osstate.start_test()
    if "time" in controls:
        clock.start_test()
        fstime.start_test()
    st.nodeid = nodeid
    if "seeds" in controls:
        seeds.start_test(PATCHER, nodeid)
    if "net" in controls:
        network.start_test()


def end_test(outcome: str):
    """The test that ran ends with ``outcome``: returns its fingerprint (or None)."""
    st = _state.STATE
    controls = st.config.controls
    if "seeds" in controls:
        seeds.end_test()
    if "net" in controls:
        network.end_test()
    uncontrolled.end_test()  # threads that ran during the test (G-0180)
    st.nodeid = None
    return st.recorder.end_test(outcome)


def trace_meta(status: str, net_mode, rebound: int, order_digest: str, runner: str, runner_version: str | None,
               disabled_plugins=(), adjustments=()) -> dict:
    """The trace header: the same fields for every runner (``runner`` names it; the pytest shell also writes
    ``pytest`` with its version)."""
    cfg = _state.STATE.config
    meta = {
        "detpy": __version__,
        "seed": cfg.seed,
        "shuffle": cfg.shuffle,
        "controls": sorted(cfg.controls),
        "hashseed": os.environ.get("PYTHONHASHSEED"),
        "reexec": status,
        "aslr_disabled": reexec.aslr_disabled(),
        "bytecode": ("precompiled" if reexec.bytecode_active(hashseed_value()) else "default"),
        "precompile_s": (float(os.environ[reexec.PRECOMPILE_ENV]) if reexec.PRECOMPILE_ENV in os.environ else None),
        "tick_adapt": cfg.tick_adapt,
        "epoch_ns": cfg.epoch_ns,
        "epoch_source": EPOCH_SOURCE.get("source"),
        "tick_ns": cfg.tick_ns,
        "sleep": cfg.sleep,
        "network": net_mode,
        "urandom_controlled": cfg.control_urandom,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": sys.platform,
        "runner": runner,
    }
    if runner_version is not None:
        meta[runner] = runner_version
    meta.update({"disabled_plugins": list(disabled_plugins), "adjustments": list(adjustments),
                 "rebound_references": rebound, "order_digest": order_digest})
    # the shared vocabulary's required header fields (G-2218) and the run inputs the verifier compares
    meta["runtime"] = platform.python_implementation()
    meta["runtime_version"] = platform.python_version()
    meta["inputs"] = run_inputs(net_mode, runner, runner_version)
    # every os.environ read by a test is an event (envobs): the verifier then reports a differing variable only for
    # the tests that read it (design A)
    meta["env_reads_recorded"] = "env" in cfg.controls
    return meta


def uninstall() -> None:
    PATCHER.undo_all()
    osstate.uninstall()
    envobs.uninstall()
    fstime.uninstall()
    clock.uninstall()
    sqlvirt.uninstall()
    seeds.uninstall()
    network.uninstall()
    _state.STATE.recorder = None
    _state.STATE.nodeid = None
    _sites.set_basetemp_provider(None)

