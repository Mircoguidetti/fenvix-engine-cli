"""Sanity tests of the pricing model. Run: python3 -m pytest -q pricing/test_model.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model as m  # noqa: E402


def test_vendor_prices_as_read():
    assert m.GH["linux4"] == 0.012 and m.BS["linux4"] == 0.008
    assert m.BS_FREE_CREDIT == 12.0                      # 3,000 minutes at $0.004
    assert abs(m.ANTITHESIS["monthly"] / m.ANTITHESIS["included_core_hours"] - 1.2496) < 1e-3


def test_blacksmith_is_never_dearer_than_github_for_the_same_minutes():
    for p in m.SHAPES.values():
        assert m.blacksmith_cost(p) < m.github_cost(p)
        assert m.blacksmith_cost(p, speedup=2, free=True) <= m.blacksmith_cost(p)


def test_our_minutes_fall_with_skip_and_rise_with_capture():
    p = m.SHAPES["large Python monorepo"]
    assert m.our_minutes(p, skip=0.9) < m.our_minutes(p, skip=0.5) < m.our_minutes(p, skip=0.0)
    assert m.our_minutes(p, capture=1.1) < m.our_minutes(p, capture=1.47)
    # with nothing skipped and no overhead we spend the customer's minutes plus the fixed minute
    q = dict(p, skip=0.0, capture=1.0)
    assert abs(m.our_minutes(q) - (m.baseline_minutes(q) + m.FIXED_MIN)) < 1.0


def test_price_and_margin_identity():
    for infra in m.INFRAS:
        for name, p in m.SHAPES.items():
            e = m.evaluate(name, p, infra)
            assert abs(e["price_list"] - 0.7 * e["bs_list"]) < 1e-9
            if e["price_list"] > 0:
                assert abs(e["margin_list"] - (1 - e["cost"] / e["price_list"])) < 1e-9
            assert abs(e["floor"] * (1 - m.HEALTHY_MARGIN) - e["cost"]) < 1e-9


def test_every_plan_unit_is_30_percent_below_blacksmith_list():
    for name, cap, price, over in m.PLANS[1:]:
        assert price / cap <= m.UNIT_CEILING_LIST + 1e-9
        assert over <= m.UNIT_CEILING_LIST + 1e-9
    units = [cap for _, cap, _, _ in m.PLANS[1:]]
    per_unit = [price / cap for _, cap, price, _ in m.PLANS[1:]]
    assert units == sorted(units) and per_unit == sorted(per_unit, reverse=True)


def test_plan_for_picks_the_cheapest():
    assert m.plan_for(100)[0] == "Starter"
    for u in (2_600, 9_000, 12_000, 45_000, 250_000):
        label, total = m.plan_for(u)
        for name, cap, price, over in m.PLANS[1:]:
            assert total <= price + max(0, u - cap) * over + 1e-9


def test_tables_and_json_are_regenerated(tmp_path):
    md, res = m.build()
    here = Path(m.__file__).resolve().parent / "data"
    assert (here / "tables.md").read_text() == md
    assert json.loads((here / "results.json").read_text())["rates"] == json.loads(json.dumps(res["rates"]))
