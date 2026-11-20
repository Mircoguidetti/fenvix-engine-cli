"""``fenvix repro / explore / replay`` for Vitest and Jest (``detpy.fenvix_js``, row F-02 for Node).

Synthetic suites per runner: an order-dependent test (a polluter in another describe block of the same file leaves
module state behind), a seed-dependent test (Math.random under the seed) and a test whose outcome comes from a child
process (a source Level 0 does not control). Needs node, the built detjs (``cd node && npm ci && node
scripts/build.js``) and its dev dependencies (vitest, jest); skipped otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from detpy import fenvix_js
from detpy import repro as _repro

ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / "node"
TMP = NODE / "test" / ".tmp" / "pytest-fenvix-js"  # under node/: the fixtures resolve vitest and jest from node/node_modules


def _ready() -> str | None:
    if shutil.which("node") is None:
        return "node is not installed"
    if not list(NODE.glob("detjs.*.node")):
        return "detjs native core not built (cd node && node scripts/build.js)"
    for dep in ("vitest", "jest", "@playwright/test"):
        if not (NODE / "node_modules" / dep).is_dir():
            return "node dev dependencies not installed (cd node && npm ci)"
    return None


pytestmark = pytest.mark.skipif(_ready() is not None, reason=_ready() or "")

SUITE = {
    "vitest": {
        "config": ("vitest.config.mjs", "export default { test: { include: ['tests/**/*.test.mjs'] } };\n"),
        "ext": ".test.mjs",
        "head": "import { test, expect, describe } from 'vitest';\nimport { execSync } from 'node:child_process';\n",
    },
    "jest": {
        "config": ("jest.config.js", "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n"),
        "ext": ".test.js",
        "head": "const { execSync } = require('node:child_process');\n",
    },
    "playwright": {
        "config": ("playwright.config.ts", "import { defineConfig } from '@playwright/test';\n"
                   "export default defineConfig({ testDir: './tests', reporter: 'list' });\n"),
        "ext": ".spec.ts",
        "head": "import { test, expect } from '@playwright/test';\nimport { execSync } from 'node:child_process';\n"
                "const describe = test.describe;\n",
    },
}

ORDER_FILE = """const cache = new Map();
test('victim', () => { expect(cache.size).toBe(0); });
test('f1', () => {});
describe('g', () => {
  test('f2', () => {});
  test('polluter', () => { cache.set('k', 1); });
  test('f3', () => {});
});
test('f4', () => {});
"""
OTHER_FILE = """test('dice', () => { expect(Math.random()).toBeLessThan(0.3); });
test('child', () => {
  const v = Number(execSync('node -e "process.stdout.write(String(Math.random()))"').toString());
  expect(v).toBeLessThan(0.5);
});
test('steady', () => { expect(1).toBe(1); });
"""


def make_project(runner: str, name: str) -> Path:
    d = TMP / runner / name
    shutil.rmtree(d, ignore_errors=True)
    (d / "tests").mkdir(parents=True)
    s = SUITE[runner]
    (d / "package.json").write_text(json.dumps({"name": f"fx-{name}", "private": True, "devDependencies": {runner: "*"}}))
    (d / s["config"][0]).write_text(s["config"][1])
    (d / "tests" / f"a{s['ext']}").write_text(s["head"] + ORDER_FILE)
    (d / "tests" / f"b{s['ext']}").write_text(s["head"] + OTHER_FILE)
    return d


def ns(test: str, out: Path, **kw) -> SimpleNamespace:
    base = dict(test=test, seeds=10, seed=None, confirm=10, max_runs=200, timeout=300, out=str(out), python=sys.executable,
                runner_args=[], json=False)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("FENVIX_DETJS", f"node {NODE / 'bin' / 'detjs.js'}")
    for k in ("CI", "GITHUB_ACTIONS", "DETJS", "NODE_OPTIONS"):
        monkeypatch.delenv(k, raising=False)


RUNNERS = ["vitest", "jest", "playwright"]


def _chromium() -> str | None:
    p = subprocess.run(["node", "-e", "const fs=require('fs');const e=require('playwright-core').chromium.executablePath();"
                        "process.stdout.write(fs.existsSync(e)?'':'Chromium not installed: '+e)"],
                       cwd=NODE, capture_output=True, text=True)
    return (p.stdout or p.stderr).strip() or None


@pytest.mark.parametrize("runner", RUNNERS)
def test_order_dependent_test_is_reproduced_with_its_polluter(runner, env, monkeypatch):
    d = make_project(runner, "order")
    monkeypatch.chdir(d)
    a = fenvix_js.ADAPTERS[runner]
    assert a.available() is None
    ext = SUITE[runner]["ext"]
    victim = f"tests/a{ext}::victim"
    b = a.repro(ns(victim, d / "out"))
    assert b["status"] == "reproduced", b
    assert b["runner"] == runner
    assert b["kind"] == "order"
    assert b["polluters"] == [f"tests/a{ext}::g::polluter"]
    assert b["order"] == [f"tests/a{ext}::g::polluter", victim]
    assert b["replay"]["fails"] == 10 and b["replay"]["runs"] == 10
    assert b["replay"]["identical_fingerprint"] is True and len(b["replay"]["fingerprints"]) == 1
    assert b["exception"][1] == "call" and b["exception"][3].startswith(f"tests/a{ext}:")
    text = fenvix_js.render_repro(b, d / "out")
    assert "REPRODUCED: failed 10/10 replays with one fingerprint" in text
    assert f"cause:   test order: it fails when run after tests/a{ext}::g::polluter" in text
    bundle = d / "out" / _repro._slug(victim)
    saved = json.loads((bundle / "bundle.json").read_text())
    assert saved["runner"] == runner and saved["command"].startswith(f"detjs {runner}")
    assert "--det-order=" in saved["command"] and "pytest_args" not in saved
    assert saved["replay_command"].endswith(str(bundle))
    assert (bundle / "order.txt").read_text().splitlines() == b["order"]
    # the bundle's own runner replays it 10/10 with the bundle's fingerprint
    res = a.replay(bundle, 10)
    assert res == {"test": victim, "runs": 10, "fails": 10, "identical_fingerprint": True, "matches_bundle": True}
    # replay picks the runner from the bundle, whatever adapter is asked
    other = fenvix_js.ADAPTERS["jest" if runner != "jest" else "vitest"]
    assert other.replay(bundle, 2)["fails"] == 2


@pytest.mark.parametrize("runner", RUNNERS)
def test_seed_dependent_test_is_reproduced_and_named_seed(runner, env, monkeypatch):
    d = make_project(runner, "seed")
    monkeypatch.chdir(d)
    test = f"tests/b{SUITE[runner]['ext']}::dice"
    b = fenvix_js.ADAPTERS[runner].repro(ns(test, d / "out"))
    assert b["status"] == "reproduced", b
    assert b["kind"] == "fails-alone"
    assert b["order"] == [test]
    assert b["replay"] == {**b["replay"], "fails": 10, "runs": 10, "identical_fingerprint": True}
    assert fenvix_js.cause_of(b).startswith("seed: it fails alone under ")
    # the bundle names a seed (or the fixed order) under which the draw fails, and another passes
    res = fenvix_js.ADAPTERS[runner].replay(d / "out" / _repro._slug(test), 10)
    assert res["fails"] == 10 and res["identical_fingerprint"] and res["matches_bundle"]


@pytest.mark.parametrize("runner", RUNNERS)
def test_uncontrolled_source_is_not_reproducible_and_named(runner, env, monkeypatch):
    d = make_project(runner, "child")
    monkeypatch.chdir(d)
    test = f"tests/b{SUITE[runner]['ext']}::child"
    # the child draws a real random number: half the runs fail; a seed found failing first, then 10 replays
    b = fenvix_js.ADAPTERS[runner].repro(ns(test, d / "out", seeds=30, confirm=10))
    assert b["status"] == "replay-unstable", b  # 10/10 by chance: 2**-10
    assert len(b["uncontrolled"]) == 1 and b["uncontrolled"][0].startswith("child (execSync node -e"), b["uncontrolled"]
    assert b["kind"] == "uncontrolled" and b["polluters"] == [] and b["setters"] == []
    text = fenvix_js.render_repro(b, d / "out")
    assert "NOT REPRODUCIBLE under fenvix" in text
    assert f"the test uses a source this release does not control: {b['uncontrolled'][0]}" in text
    assert f"cause:   uncontrolled source: the test used {b['uncontrolled'][0]}" in text


@pytest.mark.parametrize("runner", RUNNERS)
def test_not_collected_and_detect(runner, env, monkeypatch):
    d = make_project(runner, "misc")
    monkeypatch.chdir(d)
    a = fenvix_js.ADAPTERS[runner]
    b = a.repro(ns(f"tests/a{SUITE[runner]['ext']}::nope", d / "out"))
    assert b["status"] == "not-collected" and b["runner"] == runner
    assert a.detect(d) and not any(o.detect(d) for n, o in fenvix_js.ADAPTERS.items() if n != runner)
    assert a.owns(f"tests/a{SUITE[runner]['ext']}::victim")
    assert not a.owns("tests/test_x.py::test_y")
    # the driver's runner: collection gives the order of a run of the same configuration
    r = fenvix_js.DetjsRunner(cwd=d, workdir=d / "w", runner=runner)
    for config in ("fixed", "3"):
        col = r.collect(config)
        run = r.run(config, None, f"full-{config}")
        assert col == run.order and len(col) == 9


def test_standalone_command_line(env, monkeypatch, capsys):
    d = make_project("vitest", "cli")
    monkeypatch.chdir(d)
    code = fenvix_js.main(["repro", "tests/a.test.mjs::victim", "--seeds", "10", "--confirm", "3", "--out", "o", "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith("fenvix repro: tests/a.test.mjs::victim\n  status:  REPRODUCED: failed 3/3 replays")
    bundle = d / "o" / _repro._slug("tests/a.test.mjs::victim")
    assert fenvix_js.main(["replay", str(bundle), "--runs", "2"]) == 0
    assert "REPRODUCED: failed 2/2 runs" in capsys.readouterr().out
    # explore: seeds within a budget, the flaky ones bundled
    code = fenvix_js.main(["explore", "--budget", "5", "--max-seeds", "4", "--out", "e", "--confirm", "2", "--runner", "vitest"])
    out = capsys.readouterr().out
    assert code == 0, out
    s = json.loads((d / "e" / "explore.json").read_text())
    assert s["runner"] == "vitest"
    assert "tests/a.test.mjs::victim" in s["flaky_failing"]
    vb = [b for b in s["bundles"] if b["test"] == "tests/a.test.mjs::victim"][0]
    assert vb["status"] == "reproduced" and vb["polluters"] == ["tests/a.test.mjs::g::polluter"]
    assert vb["runner"] == "vitest" and vb["command"].startswith("detjs vitest run --det")


def test_register_replaces_the_planned_adapters():
    adapters = {"pytest": object(), "vitest": object(), "jest": object(), "playwright": object()}
    fenvix_js.register(adapters)
    assert isinstance(adapters["vitest"], fenvix_js.VitestAdapter)
    assert isinstance(adapters["jest"], fenvix_js.JestAdapter)
    assert isinstance(adapters["playwright"], fenvix_js.PlaywrightAdapter)
    assert adapters["pytest"] is not None and not isinstance(adapters["pytest"], fenvix_js.DetjsAdapter)


def test_playwright_browser_test_order_dependent_is_reproduced(env, monkeypatch):
    """A Playwright test that opens a page in Chromium and fails after a polluter: REPRODUCED, polluter named, the
    bundle replays 10/10 with one fingerprint (audit G-0406, G-0455)."""
    why = _chromium()
    if why:
        pytest.skip(why)
    d = make_project("playwright", "browser")
    (d / "tests" / "c.spec.ts").write_text(SUITE["playwright"]["head"] + """const seen: string[] = [];
test('theme', async ({ page }) => {
  await page.setContent('<p id="t">' + (seen.length ? 'dark' : 'light') + '</p>');
  await expect(page.locator('#t')).toHaveText('light');
});
test('f5', async () => {});
test('sets-dark', async ({ page }) => { await page.setContent('<b>x</b>'); seen.push('dark'); });
""")
    monkeypatch.chdir(d)
    a = fenvix_js.ADAPTERS["playwright"]
    assert a.available() is None
    b = a.repro(ns("tests/c.spec.ts::theme", d / "out", confirm=10))
    assert b["status"] == "reproduced", b
    assert b["polluters"] == ["tests/c.spec.ts::sets-dark"]
    assert b["order"] == ["tests/c.spec.ts::sets-dark", "tests/c.spec.ts::theme"]
    assert b["replay"]["fails"] == 10 and b["replay"]["identical_fingerprint"]
    assert b["command"].startswith("detjs playwright test --det ")
    res = a.replay(d / "out" / _repro._slug("tests/c.spec.ts::theme"), 10)
    assert res["fails"] == 10 and res["identical_fingerprint"] and res["matches_bundle"]


def test_detjs_repro_subcommands_run_the_driver(env, monkeypatch):
    """`detjs repro|replay` (audit G-0420, G-0448, G-0449): the same driver and output as fenvix repro / replay."""
    d = make_project("jest", "detjs-cli")
    e = {**os.environ, "FENVIX_PYTHON": sys.executable}
    e.pop("FENVIX_DETJS", None)
    p = subprocess.run(["node", str(NODE / "bin" / "detjs.js"), "repro", "tests/a.test.js::victim", "--seeds", "10",
                        "--confirm", "3", "--out", "o"], cwd=d, env=e, capture_output=True, text=True, timeout=1500)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "status:  REPRODUCED: failed 3/3 replays" in p.stdout
    assert "cause:   test order: it fails when run after tests/a.test.js::g::polluter" in p.stdout
    bundle = d / "o" / _repro._slug("tests/a.test.js::victim")
    p = subprocess.run(["node", str(NODE / "bin" / "detjs.js"), "replay", str(bundle), "--runs", "3"], cwd=d, env=e,
                       capture_output=True, text=True, timeout=1500)
    assert p.returncode == 0 and "REPRODUCED: failed 3/3 runs" in p.stdout, p.stdout + p.stderr


def test_detjs_not_found_is_explained(monkeypatch, tmp_path):
    monkeypatch.setenv("FENVIX_DETJS", str(tmp_path / "no-such-detjs"))
    why = fenvix_js.ADAPTERS["vitest"].available()
    assert why and why.startswith("repro / explore / replay for vitest need detjs: detjs could not start")
