"""Round 2 of rust-hotpaths: the capture's sqlite trace and rare-event helpers in Rust (``crates/detpy-py/src/sqlcap.rs``,
``sockcap.rs``) against the Python functions they replace (``tests/rust_hotpaths_ref/_ref_proofcache.py``).

* the statement matchers against ``re`` (``_SQL_REAL_CLOCK``, ``_SQL_NO_SCHEMA``, ``_SQL_DDL``, ``_SQL_ATTACH``) on
  generated statements: keywords in mixed case and with the characters ``re.I`` folds onto ASCII letters, Unicode
  letters, digits, marks, connector punctuation and whitespace around them;
* ``_sqlite_file`` on str / bytes / PathLike / other objects, with and without ``uri``, ``file:`` forms with a host,
  ``%``-escapes (invalid ones and non-UTF-8 sequences included), fragments and ``mode=memory``;
* ``_loopback_hex``, ``_numeric_host``, ``_addr``, ``_spawn_detail``, and ``_own_listener`` / ``_both_ends_mine`` /
  ``_own_socket_inodes`` on real sockets.

Whole sessions over sqlite, socket and spawn tests are compared in ``tests/test_capture_rust.py``.
"""

from __future__ import annotations

import importlib.util
import os
import random
import re
import socket
import sys
from pathlib import Path

import pytest

from detpy import _core

REF = Path(__file__).parent / "rust_hotpaths_ref"


@pytest.fixture(scope="module")
def ref():
    spec = importlib.util.spec_from_file_location("detpy._ref_proofcache_sqlcap", REF / "_ref_proofcache.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _outcome(f, *args):
    try:
        return ("ok", f(*args))
    except Exception as e:  # noqa: BLE001
        return ("err", type(e))


# -- statements ------------------------------------------------------------------------------------------------
_KEYWORDS = ["'now'", '"now"', "current_timestamp", "current_date", "current_time", "current_", "date", "time",
             "datetime", "julianday", "unixepoch", "strftime", "begin", "commit", "end", "rollback", "savepoint",
             "release", "pragma", "attach", "detach", "drop", "vacuum", "analyze", "reindex", "create", "alter",
             "database", "stamp", "select", "insert"]
# whitespace (ASCII, \x1c-\x1f, Unicode), not whitespace (ZWSP, MVS), word characters re counts (letters of every
# case, decimal / other digits, letter numbers), others it does not (combining marks, connector punctuation but _)
_SEPS = ["", " ", "  ", "\t", "\n", "\r\n", "\x0b", "\x0c", "\x1c", "\x1f", "\x85", "\xa0", " ", " ",
         " ", "　", "​", "᠎", "(", ")", "( )", "()", "(　)", "'", '"', "''", "'x'", '"%Y"',
         "_", "x", "1", "\xe9", "\xdf", "٣", "Ⅻ", "\xb2", "́", "‿", "\xb7", "-", ",", ";", ".",
         "ǅ", "İ", "ı", "ſ", "K", "\U0001d7d8", "\U0001f600", "\udcff", "\ud800", "%"]
_FOLD = {"i": ["I", "İ", "ı"], "s": ["S", "ſ"], "k": ["K", "K"]}


def _mutate(rng: random.Random, kw: str) -> str:
    out = []
    for c in kw:
        r = rng.random()
        if c in _FOLD and r < 0.15:
            out.append(rng.choice(_FOLD[c]))
        elif r < 0.5:
            out.append(c.upper())
        else:
            out.append(c)
        if rng.random() < 0.01:
            out.append(rng.choice(_SEPS))
    return "".join(out)


def _statements(n: int, seed: int):
    rng = random.Random(seed)
    ws = ["", " ", "\t\n", "　", "\x1c", "​", "x"]
    for _ in range(n):
        if rng.random() < 0.25:
            # ATTACH-shaped: the quoted name with doubled quotes, unterminated, followed by more quotes
            name = "".join(rng.choice(["a", "'", "''", "\xe9", " ", "%2", "\udcff", "\n"]) for _ in range(rng.randint(0, 6)))
            yield (rng.choice(ws) + _mutate(rng, "attach") + rng.choice(ws)
                   + (_mutate(rng, "database") + rng.choice(ws) if rng.random() < 0.5 else "")
                   + rng.choice(["'", "", '"']) + name + rng.choice(["'", "", "''", "' as x", "'''"]))
            continue
        parts = []
        for _ in range(rng.randint(1, 8)):
            parts.append(rng.choice(_SEPS))
            if rng.random() < 0.7:
                parts.append(_mutate(rng, rng.choice(_KEYWORDS)))
        yield "".join(parts)


_HANDWRITTEN = [
    "select date('now')", "SELECT CURRENT_TIMESTAMP", "select current_timestamps", "select xcurrent_date",
    "select date ( )", "select date(\n)", "select date(x)", "select datetime()", "select datetime ()",
    "select julianday( )", "select unixepoch()", "select strftime('%s')", "select strftime ( \"%Y\" )",
    "select strftime('%s', 'now')", "select strftime('%s' , x)", "select date　( )", "select date​()",
    "select édate()", "select _date()", "select date_()", "select ́date()", "select ‿date()",
    "select ٣date()", "select datİme()", "select ſtrftime('x')", "select CURRENT_TIMÉ",
    "select current_timeé", "  begin", "　commit", "end;", "endx", "rollbacḱ", "rollback_",
    "\x1cpragma x", "​pragma x", "DROP table", "ATTACH 'a.db' AS a", "attach database 'a''b.db' as a",
    "attach database'x' as a", "attach  database  'x'", "attach'x'", "attach 'abc''", "attach 'a''b''c",
    "attach 'unterminated", "attach database 'x", " Attach\tDATABASE\n'fé.db' AS x", "attach 　'x'",
    "create table t (x default current_timestamp)", "CREATE TRIGGER tr", "alter table", "creat table",
    "creaté", "ALTER ", "", " ", "'NOW'", "'n0w'", "\"Now\"", "'now", "select 1",
]


def test_statement_matchers_match_re(ref):
    n = 0
    for s in [*_HANDWRITTEN, *_statements(60000, 1)]:
        attach = ref._SQL_ATTACH.match(s)
        want = (bool(ref._SQL_REAL_CLOCK.search(s)),
                (bool(ref._SQL_NO_SCHEMA.match(s)), bool(ref._SQL_DDL.match(s)), attach and attach.group(1)))
        assert (_core.sql_real_clock(s), _core.sql_statement_kind(s)) == want, ascii(s)
        n += want[0] + want[1][0] + want[1][1] + bool(want[1][2])
    assert n > 10000  # the generator reaches the matching branches


def test_case_folding_onto_ascii_letters_is_what_the_matchers_assume():
    # re.I lets these non-ASCII characters match an ASCII letter of a pattern (and no other); sqlcap.rs's ci_eq
    lit = re.compile("|".join("abcdefghijklmnopqrstuvwxyz"), re.I)
    found = {c: [x for x in "abcdefghijklmnopqrstuvwxyz" if re.fullmatch(x, chr(c), re.I)]
             for c in range(0x80, sys.maxunicode + 1) if lit.fullmatch(chr(c))}
    assert found == {0x130: ["i"], 0x131: ["i"], 0x17F: ["s"], 0x212A: ["k"]}


def test_word_and_space_classes_against_re_on_every_character():
    # \b and \s of every code point (the matchers ask str.isalnum / str.isspace: the same as re's)
    word = re.compile(r"\w")
    space = re.compile(r"\s")
    for c in range(sys.maxunicode + 1):
        ch = chr(c)
        assert bool(word.match(ch)) == (ch.isalnum() or ch == "_"), hex(c)
        assert bool(space.match(ch)) == ch.isspace(), hex(c)
    # and through the matchers, for a sample of them around a keyword
    rng = random.Random(2)
    for c in rng.sample(range(sys.maxunicode + 1), 20000) + list(range(0x100)):
        ch = chr(c)
        for s in (f"{ch}date()", f"date{ch}()", f"date({ch})", f"{ch}commit", f"commit{ch}", f"attach{ch}'x'"):
            assert _core.sql_real_clock(s) == bool(re.search(r"\bdate\s*\(\s*\)", s, re.I)), ascii(s)
            nk = _core.sql_statement_kind(s)
            assert nk[0] == bool(re.match(r"\s*(commit|attach)\b", s, re.I)), ascii(s)


# -- _sqlite_file ------------------------------------------------------------------------------------------------
class _PL:
    def __init__(self, v):
        self.v = v

    def __fspath__(self):
        if isinstance(self.v, Exception):
            raise self.v
        return self.v


_PREFIXES = ["", "file:", "FILE:", "file:/", "file://", "file:///", "file://localhost/", "file://localhost",
             "file://host/", "file://host", "file:////", ":memory:", "file::memory:", "file:%2F"]
_PATHS = ["a.db", "/abs/x.db", "rel/../y.db", "", "x%20y.db", "%zz", "%4", "%", "%%41", "%C3%A9", "%c3%a9", "%C3",
          "%FF%FE", "%ed%a0%80", "%f0%9f%98%80", "%f0%9f%98", "\xe9%41", "%41\xe9%42", "%C3\xe9%A9", "a#frag",
          "a%23b", "/x/./y//z/..", "\udcff.db", "%e2%82%ac\udcfe", "::memory:", "~/x", "//double", "./"]
_QUERIES = ["", "?", "?mode=memory", "?mode=ro", "?cache=shared&mode=memory", "?mode=memory#x", "?x#mode=memory",
            "#?mode=memory", "?mode=Memory", "?mode=memory&", "?a=1&mode=memory&b", "?mode=memoryx"]


def _sqlite_inputs():
    rng = random.Random(3)
    for p in _PREFIXES:
        for q in _PATHS:
            for r in _QUERIES:
                s = p + q + r
                yield s
                if rng.random() < 0.2:
                    yield _PL(s)
                if not any(0xD800 <= ord(c) < 0xE000 for c in s):
                    if rng.random() < 0.2:
                        yield s.encode()
                    if rng.random() < 0.1:
                        yield _PL(s.encode())
    alphabet = ["%", "0", "9", "a", "F", "g", "/", "#", "?", "&", "=", "\xe9", "\udcff", "file:", "//", "localhost",
                "mode=memory", ":memory:", "%C3", "%A9", "%ED", "%80"]
    for _ in range(5000):
        yield "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 10)))
    yield from [b"\xff.db", b"file:\xff%41", b"file:x\x80?mode=memory", _PL(b"\xfe"), _PL(1), _PL(None),
                _PL(TypeError("x")), _PL(ValueError("x")), _PL(RuntimeError("x")), Path("p.db"), Path("/a/../b"),
                1, None, 1.5, bytearray(b"x.db"), memoryview(b"x.db"), ["x.db"], object(), "a\0b", b"a\0b"]


def test_sqlite_file_matches_reference(ref, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = 0
    for db in _sqlite_inputs():
        for uri in (False, True):
            got, want = _outcome(_core.sqlite_file_of, db, uri), _outcome(ref._sqlite_file, db, uri)
            assert got == want, (db, uri)
            n += want[0] == "ok" and want[1] is not None
    assert n > 5000


def test_sqlite_file_reads_getcwd_at_each_use(ref, monkeypatch):
    for cwd in ("/some/where", "/", "rel", ""):
        monkeypatch.setattr(os, "getcwd", lambda c=cwd: c)
        for db in ("x.db", "../x.db", "file:y%20z?mode=ro", "/abs.db"):
            assert _core.sqlite_file_of(db, True) == ref._sqlite_file(db, True), (cwd, db)

    def gone():
        raise FileNotFoundError("cwd removed")

    monkeypatch.setattr(os, "getcwd", gone)
    assert _core.sqlite_file_of("x.db", False) is None and ref._sqlite_file("x.db", False) is None


# -- sockets, addresses, spawns -----------------------------------------------------------------------------------
def test_loopback_hex_matches_reference(ref):
    cases = ["0100007F", "0101007F", "0100007E", "00000000", "0000000000000000FFFF00000100007F",
             "0000000000000000FFFF00000101A8C0", "00000000000000000000000001000000", "00000000000000000000000000000001",
             "00000000000000000000000000000000", "", "0", "0100007", "0100007G", "01 00 00 7F", " 0100007F ",
             "0 100007F", "01\t00007F", "0100007F\x0b", "0100007F\x1c", "０100007F", "0100007f", "0x0100007F"]
    rng = random.Random(4)
    for _ in range(20000):
        n = rng.choice([4, 8, 16, 32, 33, 31, 34])
        s = "".join(rng.choice("0000000F7fF1 \x0c") for _ in range(n))
        cases.append(s)
        cases.append("".join(rng.choice("0123456789abcdefABCDEF") for _ in range(rng.choice([8, 32]))))
    for c in cases:
        assert _core.cap_loopback_hex(c) == ref._loopback_hex(c), ascii(c)


def test_numeric_host_and_addr_match_reference(ref):
    hosts = ["127.0.0.1", "::1", "fe80::1%eth0", "fe80::1%", "localhost", "1.2.3", "1.2.3.4.5", "٣.1.1.1", "",
             "%", "::ffff:1.2.3.4", "01.2.3.4", "example.com", "1.2.3.4%x", "[::1]", "::", "0.0.0.0", "\udcff"]
    for h in hosts:
        assert _core.cap_numeric_host(h) == ref._numeric_host(h), h

    class Fmt:
        def __format__(self, spec):
            return "fmt!"

        def __str__(self):
            return "str!"

    class Bad:
        def __str__(self):
            raise TypeError("no")

    class Worse:
        def __str__(self):
            raise RuntimeError("no")

    for args in [(None, ("h", 1)), (None, ("h",)), (None, ()), (None, "/tmp/sock"), (None, b"\0abstract"), (None,),
                 (), (None, ("::1", 80, 0, 0)), (None, (Fmt(), Fmt())), (None, Fmt()), (None, Bad()), (None, Worse()),
                 (None, ("h\udcff", 2)), (None, ["h", 1]), (None, {0: 1})]:
        assert _outcome(_core.cap_addr, args) == _outcome(ref._addr, args), args


def test_spawn_detail_matches_reference(ref):
    class P:
        def __fspath__(self):
            return "/bin/pathlike"

    cases = [("subprocess.Popen", ("/usr/bin/git", ["git", "status"], None, None)),
             ("subprocess.Popen", (None, ["/bin/true", "x"], None, None)), ("subprocess.Popen", (None, "ls -l", None, None)),
             ("subprocess.Popen", (None, b"/bin/ls", None, None)), ("subprocess.Popen", (None, [], None, None)),
             ("subprocess.Popen", (None, 5, None, None)), ("subprocess.Popen", (None, [P()], None, None)),
             ("subprocess.Popen", (None, [5], None, None)), ("subprocess.Popen", (b"/x/\xff", [], None, None)),
             ("subprocess.Popen", ()), ("os.system", ("echo hi",)), ("os.system", (b"  /bin/ls  -l",)),
             ("os.system", ("",)), ("os.system", ("　\x1cprog\x85arg",)), ("os.system", (5,)), ("os.system", ()),
             ("os.spawnv", (0, "/bin/sh", ["sh"], None)), ("os.spawn", (0,)), ("os.posix_spawn", ("/bin/x", [], {})),
             ("os.exec", (P(), [], None)), ("os.execv", ("relative/prog", [])), ("os.fork", ()), ("os.forkpty", ()),
             ("os.exec", (None,)), ("os.exec", ("",))]
    for event, args in cases:
        pair = (_outcome(ref._spawn_detail, event, args), _outcome(_core.cap_spawn_detail, ref._DETPY_DIR, event, args))
        assert pair[0] == pair[1], (event, args)
        assert pair[0][0] == "ok"


def _listener(family=socket.AF_INET, host="127.0.0.1"):
    s = socket.socket(family, socket.SOCK_STREAM)
    s.bind((host, 0))
    s.listen()
    return s


def test_own_listener_and_both_ends_mine_on_real_sockets(ref):
    opened = []

    def keep(s):
        opened.append(s)
        return s

    try:
        srv = keep(_listener())
        port = srv.getsockname()[1]
        free = keep(socket.socket())
        free.bind(("127.0.0.1", 0))
        unused = free.getsockname()[1]  # bound, not listening
        cli = keep(socket.socket())
        udp = keep(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        unix_a, unix_b = socket.socketpair(socket.AF_UNIX)
        keep(unix_a), keep(unix_b)
        cases = [(cli, ("127.0.0.1", port)), (cli, ("127.0.0.2", port)), (cli, ("localhost", port)),
                 (cli, ("127.0.0.1", unused)), (cli, ("127.0.0.1", str(port))), (cli, ("127.0.0.1", "x")),
                 (cli, ("127.0.0.1",)), (cli, "127.0.0.1"), (cli,), (), (udp, ("127.0.0.1", port)),
                 (unix_a, ("127.0.0.1", port)), (object(), ("127.0.0.1", port)), (cli, ("10.0.0.1", port)),
                 (cli, ("127.0.0.1%lo", port)), (cli, (b"127.0.0.1", port)), (cli, ("127.0.0.1", -1)),
                 (cli, ("127.0.0.1", 2 ** 70)), (cli, {0: "127.0.0.1", 1: port})]
        if socket.has_ipv6:
            try:
                srv6 = keep(_listener(socket.AF_INET6, "::"))
                cli6 = keep(socket.socket(socket.AF_INET6))
                port6 = srv6.getsockname()[1]
                cases += [(cli6, ("::1", port6)), (cli6, ("::ffff:127.0.0.1", port6)), (cli6, ("::1", port)),
                          (cli6, ("::ffff:127.0.0.1", port))]
            except OSError:
                pass
        n = 0
        for args in cases:
            got, want = _outcome(_core.cap_own_listener, args), _outcome(ref._own_listener, args)
            assert got == want, args
            n += want == ("ok", True)
        assert n >= 1
        # a connected pair: both ends are this process's
        conn = keep(socket.create_connection(("127.0.0.1", port)))
        acc, _ = srv.accept()
        keep(acc)
        assert _core.cap_own_socket_inodes() == ref._own_socket_inodes()

        class Fake:
            family = socket.AF_INET
            type = socket.SOCK_STREAM

            def __init__(self, peer):
                self.peer = peer

            def getpeername(self):
                if isinstance(self.peer, Exception):
                    raise self.peer
                return self.peer

        closed = socket.socket()
        closed.close()
        socks = [conn, acc, cli, srv, udp, unix_a, closed, object(), Fake(conn.getsockname()),
                 Fake(("127.0.0.1", unused)), Fake(("notip", 1)), Fake(("127.0.0.1", "x")), Fake(()),
                 Fake(("127.0.0.1",)), Fake(OSError("x")), Fake(ValueError("x")), Fake((b"127.0.0.1", 1)),
                 Fake(("127.0.0.1", acc.getsockname()[1]))]
        m = 0
        for s in socks:
            got, want = _outcome(_core.cap_both_ends_mine, s), _outcome(ref._both_ends_mine, s)
            assert got == want, s
            m += want == ("ok", True)
        assert m >= 3
    finally:
        for s in opened:
            s.close()
