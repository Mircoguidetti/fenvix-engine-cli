"""Point 1: fixed, recorded order; reproducible shuffle with --det-seed."""

MODULES = {
    f"test_m{m}": "\n".join(
        [f"def test_f{t}(): pass" for t in range(4)]
        + ["class TestK:"] + [f"    def test_k{t}(self): pass" for t in range(3)]
    )
    for m in range(3)
}


def executed(trace):
    header, tests, _ = trace
    return [t["nodeid"] for t in sorted(tests.values(), key=lambda t: t["index"])]


def test_order_is_fixed_and_recorded(pytester, run_det):
    pytester.makepyfile(**MODULES)
    r1, t1 = run_det()
    r1.assert_outcomes(passed=21)
    r2, t2 = run_det()
    assert executed(t1) == executed(t2) == t1[0]["order"]
    # Fixed order = pytest's collection order.
    assert executed(t1)[0] == "test_m0.py::test_f0"
    assert t1[2]["order_digest"] == t2[2]["order_digest"]


def test_seed_shuffles_reproducibly(pytester, run_det):
    pytester.makepyfile(**MODULES)
    _, a = run_det("--det-seed=11")
    _, b = run_det("--det-seed=11")
    _, c = run_det("--det-seed=12")
    _, fixed = run_det()
    assert executed(a) == executed(b)
    assert executed(a) != executed(c)
    assert sorted(executed(a)) == sorted(executed(fixed))
    assert executed(a) != executed(fixed)
    assert a[0]["meta"]["seed"] == 11 and a[0]["meta"]["shuffle"]
    # modules stay contiguous (module fixtures are not rebuilt)
    mods = [n.split("::")[0] for n in executed(a)]
    assert len([m for i, m in enumerate(mods) if i == 0 or mods[i - 1] != m]) == 3


def test_other_plugins_cannot_reorder(pytester, run_det):
    pytester.makepyfile(**MODULES)
    pytester.makeconftest(
        """
        def pytest_collection_modifyitems(items):
            items.reverse()
        """
    )
    _, t = run_det()
    assert executed(t)[0] == "test_m0.py::test_f0"


def test_deselection_is_respected(pytester, run_det):
    pytester.makepyfile(**MODULES)
    r, t = run_det("-k", "test_k1")
    r.assert_outcomes(passed=3)
    assert executed(t) == [f"test_m{m}.py::TestK::test_k1" for m in range(3)]
