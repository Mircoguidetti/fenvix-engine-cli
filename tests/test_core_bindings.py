"""The Rust core as seen from Python."""

import json

import pytest

from detpy import _core


def test_recorder_trace_and_verify(tmp_path):
    def run(path, value):
        r = _core.Recorder(max_events=100)
        r.open(str(path), json.dumps({"seed": 1}), ["t::a", "t::b"])
        r.begin_test("t::a", 0)
        assert r.in_test
        r.record("time", "time.time", "t.py:1", "1000")
        r.record("entropy", "os.urandom", "t.py:2", value)
        fp_a = r.end_test("passed")
        r.begin_test("t::b", 1)
        r.record("random", "random.random", "t.py:5", "0.5")
        fp_b = r.end_test("passed")
        assert r.close()
        return fp_a, fp_b

    a1, b1 = run(tmp_path / "1.jsonl", "aa")
    a2, b2 = run(tmp_path / "2.jsonl", "bb")
    assert a1 != a2 and b1 == b2
    report = json.loads(_core.verify([str(tmp_path / "1.jsonl"), str(tmp_path / "2.jsonl")]))
    assert report["summary"]["stable"] == 1
    assert report["summary"]["diverged"] == 1
    bad = report["tests"][0]
    assert bad["nodeid"] == "t::a"
    d = bad["divergence"]
    assert d["index"] == 1 and d["reason"] == "entropy"
    assert d["event_a"]["at"] == "t.py:2"
    text = _core.verify_text([str(tmp_path / "1.jsonl"), str(tmp_path / "2.jsonl")])
    assert "NOT-COVERED t::a" in text


def test_events_outside_tests_are_dropped():
    r = _core.Recorder()
    r.record("time", "time.time", "", "1")
    assert r.dropped == 1
    assert r.end_test("passed") is None


def test_verify_rejects_bad_files(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("not json\n")
    with pytest.raises(ValueError):
        _core.verify([str(p), str(p)])
    with pytest.raises(OSError):
        _core.verify([str(tmp_path / "missing"), str(p)])


def test_shuffle_and_seeds():
    ids = [f"m{m}.py::t{t}" for m in range(3) for t in range(5)]
    p = _core.shuffle_order(ids, 4)
    assert sorted(p) == list(range(len(ids)))
    assert p == _core.shuffle_order(ids, 4)
    assert p != _core.shuffle_order(ids, 5)
    assert _core.derive_seed(1, "x") == _core.derive_seed(1, "x") != _core.derive_seed(1, "y")
    assert _core.order_digest(["a", "b"]) != _core.order_digest(["b", "a"])
    assert len(_core.digest(b"abc")) == 32


def test_cassette_roundtrip(tmp_path):
    c = _core.Cassette()
    i = c.open_connection("t::a", "example.com", 80)
    c.append("t::a", i, "send", b"GET / HTTP/1.0\r\n\r\n")
    c.append("t::a", i, "recv", b"HTTP/1.0 200 OK\r\n\r\nhi")
    c.set_tls("t::a", i)
    with pytest.raises(ValueError):
        c.append("t::a", i, "sideways", b"")
    with pytest.raises(KeyError):
        c.append("t::a", 9, "send", b"")
    path = tmp_path / "c.json"
    c.save(str(path))
    back = _core.Cassette.load(str(path))
    assert back.tests() == ["t::a"]
    assert back.find("t::a", "example.com", 80, 0) == 0
    assert back.find("t::a", "example.com", 80, 1) is None
    assert back.info("t::a", 0) == ("example.com", 80, True, 2)
    assert back.segments("t::a", 0)[1] == ("recv", b"HTTP/1.0 200 OK\r\n\r\nhi")


def test_backends_declared():
    b = {x["name"]: x for x in json.loads(_core.backends())}
    assert b["python-hooks"]["implemented"]
    assert not b["syscall"]["implemented"]
