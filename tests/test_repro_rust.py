"""Equivalence of ``detpy repro`` / ``detpy explore`` after their decisions moved to Rust (rust-hotpaths-2,
``crates/detpy-core/src/repro.rs``) with the Python original kept verbatim in
``tests/rust_hotpaths_ref/_ref_repro.py``.

* ddmin on randomized predicates: same minimal lists and the same predicate calls, in order (exceptions included);
* prefix_through, order_for, _slug, is_fail, Run.outcome on generated inputs; _divergence on real traces;
* reproduce / explore / replay driven by a simulated runner on randomized suites (polluters, setters, always-failing
  tests, unstable fingerprints, run budgets): the same runner calls, the same results, bundles and explore.json;
* end to end on the test projects of ``tests/test_repro.py`` (real pytest subprocesses): identical bundle.json,
  explore.json and printed text with the times masked.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import random
import re
import shutil
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from detpy import _core, repro

REF = Path(__file__).parent / "rust_hotpaths_ref"


def _load_ref():
    spec = importlib.util.spec_from_file_location("detpy._ref_repro", REF / "_ref_repro.py")
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    sys.modules[spec.name] = m  # dataclasses look their module up
    spec.loader.exec_module(m)
    return m


ref = _load_ref()


def _exc(fn, *a, **k):
    """(result, None) or (None, (exception type name, message)); the out-of-runs exception under one name."""
    try:
        return fn(*a, **k), None
    except Exception as e:  # noqa: BLE001 - compared, not handled
        name = type(e).__name__
        return None, ("OutOfRuns" if name == "ReproOutOfRuns" else name, str(e))


def _mask(x):
    """Times masked (they are wall-clock measurements)."""
    if isinstance(x, dict):
        return {k: ("<t>" if k in ("seconds", "duration", "precompile_s") else _mask(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_mask(v) for v in x]
    return x


# ---------------------------------------------------------------------------------------------------------------------
# ddmin


def _predicates(rng: random.Random, n: int):
    items = list(range(n))
    need = set(rng.sample(items, rng.randint(0, min(n, 4))))
    alt = set(rng.sample(items, rng.randint(1, min(n, 3)))) if n else set()
    salt = rng.random()
    return [
        ("subset", lambda sub: need <= set(sub)),
        ("either", lambda sub: need <= set(sub) or (bool(alt) and alt <= set(sub))),
        ("any", lambda sub: bool(need & set(sub))),
        ("count", lambda sub: len(sub) >= max(1, len(need))),
        # not monotone: an arbitrary function of the sublist (ddmin must still call it in the same order)
        ("hash", lambda sub: hashlib.sha1(repr((salt, sub)).encode()).digest()[0] < 160),
        ("parity", lambda sub: sum(sub) % 3 != 1),
        ("truthy-int", lambda sub: len(sub) % 2),  # truthiness of a non-bool result
    ]


def _run_ddmin(mod, items, pred, stop_after=None):
    calls = []

    def still_fails(sub):
        calls.append(list(sub))
        if stop_after is not None and len(calls) > stop_after:
            raise KeyError("stop")
        return pred(sub)

    got, err = _exc(mod.ddmin, list(items), still_fails)
    return got, err, calls


def test_ddmin_matches_reference_on_random_predicates():
    rng = random.Random(1234)
    checked = 0
    for trial in range(400):
        n = rng.randint(0, 24)
        items = [f"t{i}" for i in range(n)] if trial % 3 == 0 else list(range(n))
        for name, p in _predicates(rng, n):
            pred = (lambda sub, p=p: p([int(str(x).lstrip("t")) for x in sub])) if trial % 3 == 0 else p
            a = _run_ddmin(ref, items, pred)
            b = _run_ddmin(repro, items, pred)
            assert a == b, (trial, name, items)
            checked += 1
            if a[2] and trial % 7 == 0:  # an exception from the predicate stops both at the same call
                k = rng.randint(0, len(a[2]))
                assert _run_ddmin(ref, items, pred, k) == _run_ddmin(repro, items, pred, k)
    assert checked == 400 * 7


def test_ddmin_known_answers():
    assert repro.ddmin(list(range(10)), lambda sub: {3, 7} <= set(sub)) == [3, 7]
    assert repro.ddmin(list(range(10)), lambda sub: True) == []
    assert repro.ddmin([], lambda sub: True) == []
    objs = [object() for _ in range(5)]
    got = repro.ddmin(objs, lambda sub: objs[2] in sub)
    assert got == [objs[2]] and got[0] is objs[2]  # the items themselves, not copies


# ---------------------------------------------------------------------------------------------------------------------
# small functions


def _ids(rng, n):
    parts = ["test_a", "TestX::test_b", "test_c[1-2]", "test_é[ü]", "t::u", "x" * 80, "a:::b", "s p a c e",
             "q'uote", "😀", ""]
    return [f"pkg/test_{rng.randint(0, 9)}.py::{rng.choice(parts)}{i}" for i in range(n)]


def test_prefix_through_matches_reference():
    rng = random.Random(7)
    for _ in range(300):
        order = _ids(rng, rng.randint(0, 12))
        targets = order[:] + ["missing::x", "it's 'q'"]
        for t in rng.sample(targets, min(4, len(targets))):
            assert _exc(repro.prefix_through, order, t) == _exc(ref.prefix_through, order, t)
    dup = ["a", "b", "a", "c"]
    assert repro.prefix_through(dup, "a") == ref.prefix_through(dup, "a") == ["a", "b"]


def test_order_for_matches_reference():
    rng = random.Random(8)
    for _ in range(200):
        ids = _ids(rng, rng.randint(0, 30))
        for config in ["fixed", "1", "3", str(rng.randint(0, 2**63)), " 7 ", "+5", "1_0", "-1", "x", "", "0x10",
                       str(2**64)]:
            assert _exc(repro.order_for, ids, config) == _exc(ref.order_for, ids, config), config


def test_slug_matches_reference():
    rng = random.Random(9)
    alphabet = "abcXYZ019_.-/:[]() é😀'\"\\\t\n::"
    samples = _ids(rng, 200) + ["", "::", "a::", "::b", "a::b::c", "x" * 200, "é" * 70]
    samples += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 90))) for _ in range(500)]
    for s in samples:
        assert repro._slug(s) == ref._slug(s), s


def test_is_fail_and_outcome_match_reference():
    values = ["passed", "failed", "error", "xfailed", "skipped", "missing", "setup-error", "FAILED", "", None, 1, 0,
              ["failed"], {"failed": 1}, b"failed", "teardown failed"]

    class S(str):
        pass

    values += [S("failed"), S("passed")]
    for v in values:
        assert repro.is_fail(v) == ref.is_fail(v), v
    outcomes = {"a": "passed", "b": "failed", "c": None, "d": 3}
    for nid in ["a", "b", "c", "d", "zz"]:
        r_new = repro.Run("fixed", [], outcomes, {}, {}, 0.0, 0, "")
        r_ref = ref.Run("fixed", [], outcomes, {}, {}, 0.0, 0, "")
        assert r_new.outcome(nid) == r_ref.outcome(nid)


# ---------------------------------------------------------------------------------------------------------------------
# a simulated runner: outcomes are a function of the order, as under --det


class Sim:
    """A suite where victims fail after their polluter, brittle tests fail without their setter, some tests always
    fail; fingerprints can be unstable; traces are files (garbage: _divergence reports the reader's error)."""

    def __init__(self, mod, rng: random.Random, workdir: Path):
        self.mod = mod
        n = rng.randint(2, 10)
        self.collected = [f"t.py::test_{i}" for i in range(n)]
        self.pollutes = {}
        self.needs = {}
        for t in self.collected:
            r = rng.random()
            others = [x for x in self.collected if x != t]
            if r < 0.3:
                self.pollutes[t] = set(rng.sample(others, rng.randint(1, min(2, len(others)))))
            elif r < 0.45:
                self.needs[t] = set(rng.sample(others, 1))
        self.always = {t for t in self.collected if rng.random() < 0.1}
        self.unstable = {t for t in self.collected if rng.random() < 0.15}
        self.no_fp = {t for t in self.collected if rng.random() < 0.1}
        self.weird = {t: rng.choice(["skipped", "xfailed", "error", None]) for t in self.collected if rng.random() < 0.1}
        self.workdir = workdir
        self.orders = {}
        self.runs = 0
        self.seconds = 0.0
        self.log = []
        self.calls = []
        self.keep_traces = rng.random() < 0.7
        self.pytest_args = ["-p", "no:randomly", "-k", "it's"]
        self.python = sys.executable if rng.random() < 0.8 else "/opt/py"
        self.garbage = rng.random() < 0.5

    def order_of(self, config):
        self.calls.append(("order_of", config))
        if config not in self.orders:
            self.orders[config] = ref.order_for(self.collected, config)
        return self.orders[config]

    def _outcome(self, t, before):
        if t in self.weird:
            return self.weird[t]
        if t in self.always:
            return "failed"
        if t in self.pollutes and self.pollutes[t] & set(before):
            return "failed"
        if t in self.needs and not (self.needs[t] & set(before)):
            return "failed"
        return "passed"

    def run(self, config, order, tag):
        self.calls.append(("run", config, None if order is None else list(order), tag))
        self.runs += 1
        full = order if order is not None else ref.order_for(self.collected, config)
        outcomes, fps, exc = {}, {}, {}
        for i, t in enumerate(full):
            o = self._outcome(t, full[:i])
            outcomes[t] = o
            if t not in self.no_fp:
                fps[t] = f"fp-{o}-{self.runs if t in self.unstable else 0}"
            if ref.is_fail(o):
                exc[t] = f"AssertionError: {t}"
        trace = self.workdir / f"{tag}.jsonl"
        self.workdir.mkdir(parents=True, exist_ok=True)
        if self.garbage:
            trace.write_text("not a trace\n")
        else:
            trace.unlink(missing_ok=True)
        dur = 0.001 * self.runs
        self.log.append({"tag": tag, "config": config, "tests": len(full), "seconds": dur, "exit": 0})
        return self.mod.Run(config, list(full), outcomes, fps, exc, dur, 1 if exc else 0, str(trace), False,
                            {"controls": ["seeds", "fs"], "seed": config, "order_missing": []})

    def drop_traces(self):
        self.calls.append(("drop_traces",))


def _sim_pair(seed, tmp_path):
    a = Sim(ref, random.Random(seed), tmp_path / "w")
    b = Sim(repro, random.Random(seed), tmp_path / "w")
    return a, b


def test_reproduce_matches_reference_on_simulated_suites(tmp_path):
    rng = random.Random(42)
    statuses = {}
    for seed in range(250):
        a, b = _sim_pair(seed, tmp_path)
        target = rng.choice(a.collected + ["t.py::not_collected"])
        kw = dict(seeds=rng.randint(-1, 6), confirm=rng.choice([0, 1, 2, 3]), max_runs=rng.choice([0, 1, 3, 6, 40, 400]),
                  known_fail=rng.choice([None, "", "fixed", "2", "9"]),
                  known_pass=rng.choice([None, [], ["1", "1", "fixed"]]),
                  collected=rng.choice([None, list(a.collected)]))
        out_a = tmp_path / "out"
        ra = _exc(ref.reproduce, a, target, out_dir=out_a if seed % 2 else None, **kw)
        files_a = _files(out_a)
        shutil.rmtree(out_a, ignore_errors=True)
        rb = _exc(repro.reproduce, b, target, out_dir=out_a if seed % 2 else None, **kw)
        files_b = _files(out_a)
        shutil.rmtree(out_a, ignore_errors=True)
        assert (_mask(ra[0]), ra[1]) == (_mask(rb[0]), rb[1]), (seed, kw)
        assert a.calls == b.calls, seed
        assert files_a == files_b, seed
        key = ra[1][0] if ra[1] else ra[0]["status"]
        statuses[key] = statuses.get(key, 0) + 1
    # every path was taken
    for s in ("reproduced", "replay-unstable", "not-found", "not-minimised", "not-collected", "OutOfRuns", "IndexError"):
        assert statuses.get(s), statuses


def _files(d: Path) -> dict:
    """Relative path -> content (bundle.json, explore.json and the traces' headers with their times masked)."""
    out = {}
    if not d.exists():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_file():
            text = p.read_text()
            if p.name in ("bundle.json", "explore.json"):
                text = _mask(json.loads(text))
            elif p.name.endswith(".trace.jsonl") and text.startswith("{"):
                text = [_mask(json.loads(line)) for line in text.splitlines()]
            out[str(p.relative_to(d))] = text
    return out


def _explore(mod, sim, out, **kw):
    return mod.explore(sim, out_dir=out, **kw)


def test_explore_matches_reference_on_simulated_suites(tmp_path):
    rng = random.Random(4242)
    for seed in range(60):
        a, b = _sim_pair(1000 + seed, tmp_path)
        kw = dict(budget_s=600, max_seeds=rng.randint(0, 6), confirm=rng.choice([1, 2]),
                  targets=rng.choice([None, set(), set(rng.sample(a.collected, 1)), {"t.py::other"}]),
                  repro=rng.random() < 0.85, max_runs=rng.choice([3, 50]), fallback_seeds=rng.randint(0, 4))
        out = tmp_path / "ex"
        ra = _exc(_explore, ref, a, out, **kw)
        fa = _files(out)
        shutil.rmtree(out, ignore_errors=True)
        rb = _exc(_explore, repro, b, out, **kw)
        fb = _files(out)
        shutil.rmtree(out, ignore_errors=True)
        assert (_mask(ra[0]), ra[1]) == (_mask(rb[0]), rb[1]), (seed, kw)
        assert a.calls == b.calls
        assert fa == fb
        if ra[0] is not None:
            assert _print(ref.main_explore, ra[0]) == _print(repro.main_explore, ra[0])


def _print(main_explore, summary):
    """main_explore's output for a given summary (explore stubbed)."""
    return _printed(lambda: _print_summary(main_explore, summary))


def _print_summary(main_explore, summary):
    mod = sys.modules[main_explore.__module__]
    saved = mod.explore
    mod.explore = lambda runner, **kw: summary
    try:
        args = SimpleNamespace(out="/nonexistent", python=sys.executable, pytest_args=[], timeout=1, targets=None,
                               budget=1, max_seeds=1, confirm=1, no_repro=False, max_runs=1)
        main_explore(args)
    finally:
        mod.explore = saved


def _printed(fn) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()


def test_explore_budget_skips_like_reference(tmp_path):
    """A budget spent during the seed runs: the flaky tests are skipped (not reproduced)."""

    class Slow(Sim):
        def run(self, config, order, tag):
            time.sleep(0.3)
            return super().run(config, order, tag)

    for mod in (ref, repro):
        found = None
        for seed in range(200):  # a suite with a flaky test
            s = Slow(mod, random.Random(seed), tmp_path / "w")
            if any(s.pollutes.values()) and not s.always and not s.weird:
                found = seed
                break
        s = Slow(mod, random.Random(found), tmp_path / "w")
        summary = mod.explore(s, budget_s=0.45, max_seeds=5, out_dir=tmp_path / mod.__name__)
        assert summary["seeds"] == 2
        assert summary["not_reproduced_budget"] == summary["flaky_failing"]
        assert summary["bundles"] == []
    assert _mask(json.loads((tmp_path / ref.__name__ / "explore.json").read_text())) == \
        _mask(json.loads((tmp_path / repro.__name__ / "explore.json").read_text()))


def _bundles(rng):
    out = []
    for i in range(300):
        b = {"test": rng.choice(["t::a", "t::é", 3]), "status": rng.choice(["reproduced", "replay-unstable",
                                                                            "not-found", "not-minimised"])}
        if rng.random() < 0.9:
            b.update(config=rng.choice(["fixed", "3", 7]), prefix_length=rng.randint(1, 9), minimal_length=2,
                     polluters=rng.choice([[], ["t::p"], ["t::p", "t::q"], None]),
                     setters=rng.choice([[], ["t::s"], None]), kind=rng.choice(["order", "fails-alone", "brittle"]),
                     replay={"runs": 3, "fails": rng.randint(0, 3), "identical_fingerprint": rng.random() < 0.5},
                     divergence=rng.choice([None, {}, {"reason": "time", "description": "event #2: x"},
                                            {"reason": None, "description": ""},
                                            {"reason": "fs", "description": "d", "event_b": {"s": "fs", "at": "a:1"}}]))
            if rng.random() < 0.5:
                b["command"] = rng.choice(["", "pytest --det --det-order=x"])
        if rng.random() < 0.8:
            b["runs"] = rng.randint(0, 40)
        if rng.random() < 0.8:
            b["seconds"] = rng.choice([0.0, 1.25, 12.3, 1e-05, 1e17])
        out.append(b)
    return out


def test_print_bundle_matches_reference():
    for b in _bundles(random.Random(5)):
        assert _exc(_printed, lambda: repro._print_bundle(b)) == _exc(_printed, lambda: ref._print_bundle(b)), b


def test_explore_families_and_text_match_reference():
    rng = random.Random(6)
    bundles = _bundles(rng)
    ok = 0
    for k in range(40):
        bs = [b for b in rng.sample(bundles, rng.randint(0, 8)) if isinstance(b["test"], str)]
        s = {"seeds": rng.randint(0, 9), "seconds": 1.5, "flaky_failing": ["a"] * rng.randint(0, 3),
             "always_failing": [], "bundles": bs, "families_by_divergence": {"x": []}, "families_by_polluter": {}}
        got, want = _exc(_print, repro.main_explore, s), _exc(_print, ref.main_explore, s)
        assert got == want
        ok += want[1] is None
    assert ok


# ---------------------------------------------------------------------------------------------------------------------
# end to end: real pytest runs on the projects of tests/test_repro.py

from test_repro import ORDER_FIRST, PROJECT  # noqa: E402


def _real_runner(pytester, mod, log):
    class Logged(mod.Runner):
        def run(self, config, order, tag):
            log.append(("run", config, None if order is None else list(order), tag))
            return super().run(config, order, tag)

        def order_of(self, config):
            log.append(("order_of", config))
            return super().order_of(config)

    return Logged(cwd=Path(pytester.path), workdir=Path(pytester.path) / ".work", pytest_args=["-p", "no:randomly"],
                  timeout=300)


def _both(pytester, fn):
    """Run fn(module, runner) for the reference then the Rust path in the same directories; returns the masked
    results, the runner calls and the files written (bundles, explore.json)."""
    out = []
    for mod in (ref, repro):
        for d in ("bundles", ".work"):
            shutil.rmtree(Path(pytester.path) / d, ignore_errors=True)
        log = []
        runner = _real_runner(pytester, mod, log)
        t0 = time.perf_counter()
        res = fn(mod, runner)
        wall = time.perf_counter() - t0
        out.append((_mask(res), log, _files(Path(pytester.path) / "bundles"), wall, runner.seconds))
    return out


@pytest.mark.parametrize("target,seeds", [("test_p.py::test_victim", 5), ("test_p.py::test_brittle", 20),
                                          ("test_p.py::test_a", 2)])
def test_reproduce_end_to_end_matches_reference(pytester, target, seeds):
    pytester.makepyfile(test_p=PROJECT)
    pytester.makeini("[pytest]\n")
    out = Path(pytester.path) / "bundles"
    a, b = _both(pytester, lambda mod, r: mod.reproduce(r, target, seeds=seeds, confirm=2, out_dir=out))
    assert a[0] == b[0]
    assert a[1] == b[1]
    assert a[2] == b[2]
    if a[0]["status"] == "reproduced":
        assert set(a[2]) >= {f"{repro._slug(target)}/bundle.json", f"{repro._slug(target)}/order.txt",
                             f"{repro._slug(target)}/fail.trace.jsonl"}
        printed = [_printed(lambda: m._print_bundle(json.loads((out / repro._slug(target) / "bundle.json").read_text())))
                   for m in (ref, repro)]
        assert printed[0] == printed[1]


def test_standalone_brittle_end_to_end_matches_reference(pytester):
    pytester.makepyfile(test_q=ORDER_FIRST)
    pytester.makeini("[pytest]\n")
    a, b = _both(pytester, lambda mod, r: mod.reproduce(r, "test_q.py::test_needs_flag", seeds=20, confirm=2))
    assert a[:3] == b[:3]
    assert a[0]["kind"] == "brittle" and a[0]["divergence"]


def test_explore_and_replay_end_to_end_match_reference(pytester, monkeypatch):
    pytester.makepyfile(test_p=PROJECT)
    pytester.makeini("[pytest]\n")
    out = Path(pytester.path) / "bundles"
    a, b = _both(pytester, lambda mod, r: mod.explore(r, budget_s=600, max_seeds=4, out_dir=out, confirm=2))
    assert a[0] == b[0]
    assert a[1] == b[1]
    assert a[2] == b[2]
    assert a[0]["bundles"] and a[0]["families_by_polluter"]
    # replay of a bundle the Rust path wrote
    monkeypatch.chdir(pytester.path)
    bundle = Path(b[0]["bundles"][0]["bundle"])
    assert ref.replay(bundle, 2) == repro.replay(bundle, 2)
    assert repro.replay(bundle, 1)["matches_bundle"]


def test_divergence_on_real_traces_matches_reference(pytester):
    pytester.makepyfile(test_p=PROJECT)
    pytester.makeini("[pytest]\n")
    runner = repro.Runner(cwd=Path(pytester.path), workdir=Path(pytester.path) / ".work",
                          pytest_args=["-p", "no:randomly"], timeout=300)
    ids = runner.order_of("fixed")
    runs = [runner.run("fixed", None, "full"), runner.run("fixed", ["test_p.py::test_victim"], "alone"),
            runner.run("fixed", ["test_p.py::test_setter", "test_p.py::test_brittle"], "setter"),
            runner.run("3", None, "seed3")]
    bad = Path(pytester.path) / "bad.jsonl"
    bad.write_text("{not json\n")
    broken = repro.Run("fixed", [], {}, {}, {}, 0.0, 0, str(bad))
    missing = repro.Run("fixed", [], {}, {}, {}, 0.0, 0, str(Path(pytester.path) / "nope.jsonl"))
    seen = 0
    for p in runs + [broken, missing, None]:
        for f in runs + [broken, missing]:
            for nid in ids + ["x::y"]:
                got, want = repro._divergence(p, f, nid), ref._divergence(p, f, nid)
                assert got == want, (p and p.trace, f.trace, nid)
                assert json.dumps(got) == json.dumps(want)  # key order included
                seen += bool(got and got.get("description"))
    assert seen  # some real diverging events were compared


def test_timings_repro_is_dominated_by_pytest(pytester, capsys):
    """The move is for the architecture: the wall time of repro is the pytest subprocesses'."""
    pytester.makepyfile(test_p=PROJECT)
    pytester.makeini("[pytest]\n")
    out = Path(pytester.path) / "bundles"
    a, b = _both(pytester, lambda mod, r: mod.reproduce(r, "test_p.py::test_victim", seeds=5, confirm=3, out_dir=out))
    for name, (_, log, _, wall, sub) in zip(("python", "rust"), (a, b)):
        with capsys.disabled():
            print(f"\nrepro {name}: wall {wall:.3f} s, pytest subprocesses {sub:.3f} s ({100 * sub / wall:.1f} %), "
                  f"{sum(1 for c in log if c[0] == 'run')} runs")
        assert sub / wall > 0.9
