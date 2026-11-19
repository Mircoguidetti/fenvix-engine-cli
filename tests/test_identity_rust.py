"""Equivalence of the runtime identity of ``--det-cache`` after it moved to Rust (rust-hotpaths-2,
``crates/detpy-py/src/identity.rs``) with the Python original kept verbatim in
``tests/rust_hotpaths_ref/_ref_identity.py``.

* ``runtime_identity`` on this machine's environment: the same digest, dict and editable list; the same memo file;
* ``_dist_infos`` on fake site-packages trees (dist-info / egg-info dirs with METADATA / PKG-INFO / RECORD /
  direct_url.json variants: file:// URLs inside and outside the root, malformed JSON, missing files, unicode and
  undecodable names, a directory named direct_url.json, distributions of a custom finder): the same result and a
  byte-identical memo after a first and a second run and after each change of a distribution;
* ``cache_epoch`` on every branch, with a byte-identical ``epoch.json``;
* ``tz_locale_identity`` and start()'s env0 (``_safe``) on strings with surrogates.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import shutil
import sys
from importlib import metadata
from pathlib import Path

import pytest

from detpy import _core, proofcache

REF = Path(__file__).parent / "rust_hotpaths_ref"
# a distribution without a Version (importlib.metadata warns, in the original as here)
pytestmark = pytest.mark.filterwarnings("ignore:Implicit None on return values:DeprecationWarning")


def _load_ref():
    spec = importlib.util.spec_from_file_location("detpy._ref_identity", REF / "_ref_identity.py")
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    spec.loader.exec_module(m)
    return m


ref = _load_ref()


def _exc(fn, *a, **k):
    """(result, None) or (None, exception type name)."""
    try:
        return fn(*a, **k), None
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__


def _read(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _both(fn_ref, fn_new, memo_dir: Path, seed: bytes | None, *args):
    """Run both on copies of the same memo (``seed``): the same result and the same memo bytes afterwards."""
    a, b = memo_dir / "ref.json", memo_dir / "new.json"
    for p in (a, b):
        if p.exists():
            p.unlink()
        if seed is not None:
            p.write_bytes(seed)
    ra = _exc(fn_ref, *args, str(a))
    rb = _exc(fn_new, *args, str(b))
    assert ra == rb
    assert _read(a) == _read(b)
    assert sorted(os.listdir(memo_dir)) == ["new.json", "ref.json"] or seed is None and not a.exists()
    return ra[0], _read(a)


# ---------------------------------------------------------------------------------------------------------------
# this machine's environment


def test_runtime_identity_on_this_environment(tmp_path):
    root = str(Path(__file__).parent.parent)
    for memo in (None, str(tmp_path / "m.json")):
        a = ref.runtime_identity(root, memo and memo + ".ref")
        b = proofcache.runtime_identity(root, memo)
        assert a == b
        assert list(a[1]) == list(b[1])  # key order of the dict too
        if memo:
            assert _read(memo + ".ref") == _read(memo)
            # warm: served by the memo, unchanged file
            assert ref.runtime_identity(root, memo + ".ref") == proofcache.runtime_identity(root, memo) == a
            assert _read(memo + ".ref") == _read(memo)
    assert b[1]["n_distributions"] > 0


def test_dist_infos_on_this_environment_with_a_shared_memo(tmp_path):
    root = str(Path(__file__).parent.parent)
    memo = str(tmp_path / "m.json")
    a = ref._dist_infos(root, memo)
    first = _read(memo)
    b = proofcache._dist_infos(root, memo)  # the Rust reading of the file the original wrote
    assert a == b and _read(memo) == first
    os.unlink(memo)
    assert proofcache._dist_infos(root, memo) == a and _read(memo) == first


# ---------------------------------------------------------------------------------------------------------------
# fake site-packages trees


def _dist(site: Path, dirname, files: dict):
    d = site / dirname if isinstance(dirname, str) else Path(os.fsdecode(bytes(site) + b"/" + dirname))
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = d / name
        if content is None:
            p.mkdir()
        elif isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return d


def _meta(name, version="1.0"):
    return f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\nlong description\n"


def _url(path):
    return json.dumps({"url": "file://" + str(path), "dir_info": {"editable": True}})


def _tree(tmp: Path):
    site, root, other = tmp / "site", tmp / "proj", tmp / "elsewhere"
    for d in (site, root / "pkg", other):
        d.mkdir(parents=True, exist_ok=True)
    rec = "pkg/__init__.py,sha256=abc,10\npkg-1.0.dist-info/RECORD,,\n"
    _dist(site, "plain-1.0.dist-info", {"METADATA": _meta("Plain"), "RECORD": rec})
    _dist(site, "norecord-2.0.dist-info", {"METADATA": _meta("NoRecord", "2.0")})
    _dist(site, "crlf-1.0.dist-info", {"METADATA": _meta("CrLf").replace("\n", "\r\n"), "RECORD": "a\r\nb\r\n"})
    _dist(site, "eggy-0.1.egg-info", {"PKG-INFO": _meta("Eggy", "0.1")})
    _dist(site, "folded-1.0.dist-info", {"METADATA": "Metadata-Version: 2.1\nName: Folded\n  continued\n"
                                                     "Version: 1.0\n", "RECORD": rec})
    _dist(site, "noversion-1.0.dist-info", {"METADATA": "Metadata-Version: 2.1\nName: NoVersion\n"})
    _dist(site, "noname-1.0.dist-info", {"METADATA": "Metadata-Version: 2.1\nVersion: 3\n", "RECORD": rec})
    _dist(site, "ünïcødé-1.0.dist-info", {"METADATA": _meta("Ünïcødé_ΣΑΣ"), "RECORD": "ü,,\n"})
    _dist(site, b"und\xffcodable-1.0.dist-info", {"METADATA": _meta("Undecodable"), "RECORD": rec})
    _dist(site, "bom-1.0.dist-info", {"METADATA": "﻿" + _meta("Bom")})
    # direct_url.json variants
    _dist(site, "edit_in-1.0.dist-info", {"METADATA": _meta("EditIn"), "direct_url.json": _url(root)})
    _dist(site, "edit_sub-1.0.dist-info", {"METADATA": _meta("EditSub"), "direct_url.json": _url(root / "pkg")})
    _dist(site, "edit_missing-1.0.dist-info", {"METADATA": _meta("EditMissing"),
                                               "direct_url.json": _url(root / "not" / "there")})
    _dist(site, "edit_out-1.0.dist-info", {"METADATA": _meta("EditOut"), "direct_url.json": _url(other)})
    _dist(site, "edit_prefix-1.0.dist-info", {"METADATA": _meta("EditPrefix"),
                                              "direct_url.json": _url(str(root) + "x")})
    _dist(site, "edit_rel-1.0.dist-info", {"METADATA": _meta("EditRel"),
                                           "direct_url.json": '{"url": "file://proj"}'})
    _dist(site, "edit_https-1.0.dist-info", {"METADATA": _meta("EditHttps"),
                                             "direct_url.json": '{"url": "https://example.invalid/x"}'})
    _dist(site, "bad_json-1.0.dist-info", {"METADATA": _meta("BadJson"), "direct_url.json": '{"url": '})
    _dist(site, "empty_json-1.0.dist-info", {"METADATA": _meta("EmptyJson"), "direct_url.json": ""})
    _dist(site, "list_json-1.0.dist-info", {"METADATA": _meta("ListJson"), "direct_url.json": f"[{_url(root)}]"})
    _dist(site, "int_url-1.0.dist-info", {"METADATA": _meta("IntUrl"), "direct_url.json": '{"url": 7}'})
    _dist(site, "null_url-1.0.dist-info", {"METADATA": _meta("NullUrl"), "direct_url.json": '{"url": null}'})
    _dist(site, "dup_url-1.0.dist-info", {"METADATA": _meta("DupUrl"),
                                          "direct_url.json": '{"url": "https://x", "url": "file://%s"}' % root})
    _dist(site, "nan_json-1.0.dist-info", {"METADATA": _meta("NanJson"),
                                           "direct_url.json": '{"n": NaN, "url": "file://%s"}' % root})
    _dist(site, "surrogate_json-1.0.dist-info", {"METADATA": _meta("SurrogateJson"),
                                                 "direct_url.json": '{"url": "file://%s/\\udcff"}' % root})
    _dist(site, "escaped_json-1.0.dist-info", {"METADATA": _meta("EscapedJson"),
                                               "direct_url.json": '{"url": "file:\\/\\/%s"}' % root})
    _dist(site, "crlf_json-1.0.dist-info", {"METADATA": _meta("CrlfJson"),
                                            "direct_url.json": _url(root).replace(", ", ",\r\n")})
    _dist(site, "bom_json-1.0.dist-info", {"METADATA": _meta("BomJson"), "direct_url.json": "﻿" + _url(root)})
    _dist(site, "latin1_json-1.0.dist-info", {"METADATA": _meta("Latin1Json"),
                                              "direct_url.json": b'{"url": "file://\xe9"}'})
    _dist(site, "dir_json-1.0.dist-info", {"METADATA": _meta("DirJson"), "direct_url.json": None})
    # a symlinked dist-info dir (realpath differs from the path found)
    real = _dist(tmp / "store", "linked-1.0.dist-info", {"METADATA": _meta("Linked"), "RECORD": rec,
                                                          "direct_url.json": _url(root)})
    (site / "linked-1.0.dist-info").symlink_to(real)
    return site, root


# sys.path without the installed distributions (the standard library stays importable)
_BASE_PATH = [p for p in sys.path if p and "-packages" not in p]


@pytest.fixture
def fake_site(tmp_path, monkeypatch):
    site, root = _tree(tmp_path)
    monkeypatch.setattr(sys, "path", [str(site)] + _BASE_PATH)
    return site, root


def _check_runs(tmp_path, root, seed=None, runs=2, nomemo=True):
    memo_dir = tmp_path / "memo"
    memo_dir.mkdir(exist_ok=True)
    results = []
    for i in range(runs):
        res, data = _both(ref._dist_infos, proofcache._dist_infos, memo_dir, seed, root)
        results.append(res)
        seed = data  # the next run starts from the memo this one wrote
    assert proofcache._dist_infos(root) == ref._dist_infos(root)  # without a memo
    if nomemo:
        assert proofcache._dist_infos(root) == results[-1]
    return results[-1], seed


def test_fake_site_first_and_second_run(tmp_path, fake_site):
    site, root = fake_site
    (parts, editable), memo = _check_runs(tmp_path, str(root))
    assert any(p.startswith("plain==1.0:") for p in parts)
    assert sorted(os.path.basename(e.rstrip("/")) for e in editable) == sorted(
        ["edit_in-1.0.dist-info", "edit_sub-1.0.dist-info", "edit_missing-1.0.dist-info", "dup_url-1.0.dist-info",
         "nan_json-1.0.dist-info", "surrogate_json-1.0.dist-info", "escaped_json-1.0.dist-info",
         "crlf_json-1.0.dist-info", "linked-1.0.dist-info"])
    assert b"\\udcff" in memo  # the undecodable dist-info name, escaped as json.dump escapes it
    # the root given through a symlink and with a trailing separator: the same
    (tmp_path / "rootlink").symlink_to(root)
    _check_runs(tmp_path, str(tmp_path / "rootlink") + "/")


def test_fake_site_memo_follows_every_change(tmp_path, fake_site):
    site, root = fake_site
    _, memo = _check_runs(tmp_path, str(root))
    steps = [
        lambda: (site / "plain-1.0.dist-info" / "RECORD").write_text("changed,,\n"),
        lambda: (site / "plain-1.0.dist-info" / "METADATA").write_text(_meta("Plain", "2.0")),
        lambda: (site / "edit_out-1.0.dist-info" / "direct_url.json").write_text(_url(root)),
        lambda: (site / "edit_in-1.0.dist-info" / "direct_url.json").unlink(),
        lambda: _dist(site, "added-1.0.dist-info", {"METADATA": _meta("Added"), "RECORD": "x,,\n"}),
        lambda: shutil.rmtree(site / "norecord-2.0.dist-info"),
        lambda: (site / "linked-1.0.dist-info").unlink(),
    ]
    for step in steps:
        step()
        _, memo2 = _check_runs(tmp_path, str(root), memo)
        assert memo2 != memo
        memo = memo2


def test_fake_site_seeded_memos(tmp_path, fake_site):
    site, root = fake_site
    _, memo = _check_runs(tmp_path, str(root))
    entries = json.loads(memo)
    k0 = next(iter(entries))
    seeds = [
        b"", b"not json", b"{}", b'{"x": ["dist", "y"]}', b"\xff\xfe", b"{\"a\": NaN}",
        json.dumps(dict(entries, **{k0: None})).encode(),  # a null entry: computed again
        json.dumps(dict(list(entries.items())[::-1])).encode(),  # another key order: equal dicts, not rewritten
        json.dumps(dict(entries, extra=["project", None])).encode(),  # a stale entry: rewritten without it
        json.dumps(dict(entries, extra=["project", "/x/\udcff/"])).encode(),
        json.dumps(entries, ensure_ascii=False).encode(),  # non-ASCII memo (read through Python)
        memo.replace(b'["dist", "plain', b'["dist", "stale'),  # a wrong cached value is served as cached
    ]
    for seed in seeds:
        _check_runs(tmp_path, str(root), seed, runs=1, nomemo=False)


def test_fake_site_duplicate_path_entries(tmp_path, fake_site, monkeypatch):
    site, root = fake_site
    monkeypatch.setattr(sys, "path", [str(site), str(site), str(site / "missing")] + _BASE_PATH)
    _check_runs(tmp_path, str(root))


def test_dist_metadata_errors_raise_as_in_the_original(tmp_path, monkeypatch):
    site = tmp_path / "site"
    _dist(site, "badutf-1.0.dist-info", {"METADATA": b"Name: \xff\nVersion: 1\n"})
    monkeypatch.setattr(sys, "path", [str(site)] + _BASE_PATH)
    a = _exc(ref._dist_infos, str(tmp_path))
    assert a[1] is not None and a == _exc(proofcache._dist_infos, str(tmp_path))


class _Custom(metadata.Distribution):
    def __init__(self, files: dict, path=None):
        self.files_ = files
        if path is not None:
            self._path = path

    def read_text(self, filename):
        v = self.files_.get(filename)
        if isinstance(v, Exception):
            raise v
        return v

    def locate_file(self, path):
        return Path(path)


class _Finder:
    def __init__(self, dists):
        self.dists = dists

    def find_spec(self, *a, **k):
        return None

    def find_distributions(self, context=None):
        return iter(self.dists)


def test_custom_finder_distributions(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    store = _dist(tmp_path, "store-1.0.dist-info", {"METADATA": _meta("Stored")})
    store2 = _dist(tmp_path, "store-2.0.dist-info", {"METADATA": _meta("Stored", "2.0")})
    dists = [
        _Custom({"METADATA": _meta("CustomA"), "RECORD": "r,,\n"}),
        _Custom({"METADATA": _meta("CustomEdit"), "direct_url.json": _url(root)}),
        _Custom({"METADATA": _meta("CustomEditPath"), "direct_url.json": _url(root)}, path=store),
        _Custom({"METADATA": _meta("CustomPath"), "RECORD": RuntimeError("no")}, path=str(store2)),
        _Custom({"METADATA": _meta("CustomBytes"), "direct_url.json": _url(root).encode()}),
        _Custom({"METADATA": _meta("CustomRaises"), "direct_url.json": ValueError("x")}),
        _Custom({"METADATA": None}),
    ]
    monkeypatch.setattr(sys, "path", list(_BASE_PATH))
    monkeypatch.setattr(sys, "meta_path", [_Finder(dists)] + sys.meta_path)
    (parts, editable), _ = _check_runs(tmp_path, str(root))
    assert any(p.startswith("customa==1.0:") for p in parts) and "?==" in "".join(parts)
    assert editable == [str(store) + "/"]


def test_runtime_identity_on_a_fake_site(tmp_path, fake_site):
    site, root = fake_site
    memo_dir = tmp_path / "rt"
    memo_dir.mkdir()
    for seed in (None, None):
        res, _ = _both(ref.runtime_identity, proofcache.runtime_identity, memo_dir, seed, str(root))
        assert res is not None


# ---------------------------------------------------------------------------------------------------------------
# cache_epoch


EPOCHS = [
    None, b"", b"not json", b"[]", b'"x"', b"7", b"{}", b'{"epoch_ns": null}', b'{"epoch_ns": [1]}',
    b'{"epoch_ns": true}', b'{"epoch_ns": "1000"}', b'{"epoch_ns": " 1_000 "}', b'{"epoch_ns": "x"}',
    b'{"epoch_ns": 1.9}', b'{"epoch_ns": -5}', b'{"epoch_ns": 1e400}', b'{"epoch_ns": NaN}',
    b'{"epoch_ns": 1180591620717411303424}', b'{"epoch_ns": 1000, "epoch_ns": 900}', b'{"epoch_ns": 1000}\n',
    '{"epoch_ns": 1000, "é": 1}'.encode(), b'{"epoch_ns": 1000, "taken_from": "git HEAD commit time"}',
    b'{"epoch_ns": "\xd9\xa1\xd9\xa2"}', b"\xff",
]


@pytest.mark.parametrize("content", EPOCHS)
@pytest.mark.parametrize("head,window", [(1000, 0), (1500, 600), (1500, 400), (500, 0), (10**20, 10**25),
                                         (2**70, 1)])
def test_cache_epoch_branches(tmp_path, content, head, window):
    out = {}
    for name, fn in (("ref", ref.cache_epoch), ("new", proofcache.cache_epoch)):
        d = tmp_path / name
        d.mkdir()
        if content is not None:
            (d / "epoch.json").write_bytes(content)
        r = _exc(fn, str(d), head, window)
        out[name] = (r, _read(d / "epoch.json"), sorted(os.listdir(d)))
    assert out["ref"] == out["new"]


def test_cache_epoch_directory_cases(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for rel in ("rel/cache", "./a/../b//c/", "x"):
        for name, fn in (("ref", ref.cache_epoch), ("new", proofcache.cache_epoch)):
            assert fn(f"{name}/{rel}", 77, 0) == 77
        written = [_read(os.path.normpath(f"{tmp_path}/{name}/{rel}/epoch.json")) for name in ("ref", "new")]
        assert written[0] == written[1] and written[0] is not None
    # the cache dir is a file: nothing written, the head returned
    (tmp_path / "file").write_text("")
    assert ref.cache_epoch(str(tmp_path / "file"), 5, 0) == proofcache.cache_epoch(str(tmp_path / "file"), 5, 0) == 5
    # undecodable directory name
    bad = os.fsdecode(bytes(tmp_path) + b"/c\xff")
    assert ref.cache_epoch(bad + "r", 9, 0) == proofcache.cache_epoch(bad + "n", 9, 0) == 9
    assert _read(bad + "r/epoch.json") == _read(bad + "n/epoch.json")


def test_cache_epoch_kept_value_and_type(tmp_path):
    for fn in (ref.cache_epoch, proofcache.cache_epoch):
        d = tmp_path / fn.__module__
        assert fn(str(d), 1000, 10) == 1000
        r = fn(str(d), 1005, 10)
        assert r == 1000 and type(r) is int


# ---------------------------------------------------------------------------------------------------------------
# tz / locale, env0


@pytest.mark.parametrize("tz", [None, "", "Test_Zone", ":Test_Zone", "Missing", "sub", "/abs/zone", ":", "Ünï",
                                "bad\udcff"])
@pytest.mark.parametrize("tzdir", [None, "", "zones", "zones/"])
def test_tz_locale_identity(tmp_path, monkeypatch, tz, tzdir):
    z = tmp_path / "zones"
    (z / "sub").mkdir(parents=True)
    (z / "Test_Zone").write_bytes(b"TZif-one")
    (z / "Ünï").write_bytes(b"TZif-two")
    (tmp_path / "abs").mkdir()
    (tmp_path / "abs" / "zone").write_bytes(b"TZif-abs")
    if tz is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", str(tmp_path) + tz if tz.startswith("/abs") else tz)
    if tzdir is None:
        monkeypatch.delenv("TZDIR", raising=False)
    else:
        monkeypatch.setenv("TZDIR", str(tmp_path / tzdir) + ("/" if tzdir.endswith("/") else "") if tzdir else "")
    monkeypatch.setitem(os.environb, b"LC_TIME", b"de_DE.\xff")
    monkeypatch.setenv("LANG", "C.UTF-8")
    a, b = ref.tz_locale_identity(), proofcache.tz_locale_identity()
    assert a == b and list(a) == list(b)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _strings(rng: random.Random, n: int, escapable_only=False):
    alphabet = ["a", "Z", "=", "\\", "é", "€", "\U0001f600", "\x00", "\x7f", "\udc80", "\udcff", "\udcc3", "\udca9",
                "\udce2", "\udc82", "\udcac", "\udced", "\udcb2"] + ([] if escapable_only else ["\udc41", "\ud83d"])
    for _ in range(n):
        yield "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))


def test_safe_matches_the_original():
    rng = random.Random(7)
    fixed = ["", "plain", "é", "\udcff", "a\udc80b\udcc3\udca9", "\udced\udcb2\udc80", "\udcf0\udc9f\udc98\udc80",
             "x\udc41", "\ud800", "\udfff", "a􏿿"]
    for s in fixed + list(_strings(rng, 3000)):
        a, b = _exc(ref._safe, s), _exc(_core.safe_str, s)
        assert a == b, s
        if a[1] is None:
            assert type(b[0]) is str


def test_env0_matches_the_original():
    rng = random.Random(11)
    items = list(os.environ.items()) + [("DETPY_REEXEC", "1"), ("DETPY_PYC_CACHE", "\udcff")]
    items += [(k, v) for k, v in zip(_strings(rng, 500, True), _strings(rng, 500, True))]
    items += [("a\udc80", "1"), ("a\\x80", "2"), ("a\\x80", "\udcff"), ("\udcff", "")]
    a = ref.env0_of(items)
    b = _core.safe_env(items, ref._DETPY_OWN_ENV)
    assert a == b and list(a.items()) == list(b.items())
    assert _exc(ref.env0_of, [("k", "\ud800")]) == _exc(_core.safe_env, [("k", "\ud800")], ref._DETPY_OWN_ENV)
    assert _core.safe_env(os.environ.items(), proofcache._DETPY_OWN_ENV) == ref.env0_of(os.environ.items())
