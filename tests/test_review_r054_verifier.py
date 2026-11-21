"""Review R-054, round 2 on PR #12 (claude/verifier-cli @ 4a30ac4, code 94f41d5). Every test here FAILS on 4a30ac4.

Run: python -m pytest -q -p no:randomly tests/test_review_r054_verifier.py
(the Node test needs the addon at node/detjs.linux-x64.node and `npm ci` in node/, as the CI node job does)

- N1 (d917b43, F-01/F-03): the Node header now says `env_reads_recorded`, but a read made outside a test body (module
  scope of the test file, a beforeAll/before hook, a dependency read at import) is no event (controls.js returns while
  STATE.testId is null). Two runs where such a variable differs are "IDENTICAL ... ran with the same inputs", exit 0.
  Before d917b43 they were input-differs (every test counted as reading every variable).
- N2 (pre-existing, Python, same class): a module-level `os.environ.get` in a test file is no event either
  (envobs.py returns while STATE.nodeid is None): IDENTICAL, exit 0, with the variable differing.
- N3 (R3 class, F-02): `@pytest.mark.xfail(run=False)` (a quarantine whose body never runs) replays as
  "REPRODUCED: failed 2/2 runs", exit 0: repro.rs is_fail is `contains("failed")`, and "xfailed" contains it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PY = sys.executable
ROOT = Path(__file__).resolve().parent.parent


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DETPY_", "PYTEST_", "EXAM_"))}
    env.update(extra)
    return env


def _write(root: Path, files: dict) -> None:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))


def _fenvix(cwd: Path, *args, env=None, timeout=900) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "detpy.fenvix", *args], cwd=cwd, capture_output=True, text=True,
                          env=env or _env(), timeout=timeout)


NODE_SCRIPT = r"""
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { fixture, crun, show } = require(process.argv[2] + '/test/runner-helpers.js');
const native = require(process.argv[2] + '/src/native');
const VT = "import { test, beforeAll } from 'vitest';\n";
const NT = "import { test, before } from 'node:test';\n";
const CASES = {
  module: (imp) => imp + "const V = process.env.EXAM_V;\ntest('t', () => { globalThis.__v = V; });\n",
  hook: (imp, h) => imp + `let V;\n${h}(() => { V = process.env.EXAM_V; });\ntest('t', () => { globalThis.__v = V; });\n`,
  depimport: (imp) => imp + "import { V } from 'examlib';\ntest('t', () => { globalThis.__v = V; });\n",
};
const res = {};
for (const runner of ['node-test', 'vitest']) {
  for (const [name, body] of Object.entries(CASES)) {
    const files = {
      'tests/e.test.mjs': body(runner === 'vitest' ? VT : NT, runner === 'vitest' ? 'beforeAll' : 'before'),
      'node_modules/examlib/package.json': JSON.stringify({ name: 'examlib', main: 'index.js' }),
      'node_modules/examlib/index.js': 'exports.V = process.env.EXAM_V;\n',
    };
    if (runner === 'vitest') files['vitest.config.mjs'] = "export default { test: { include: ['tests/**/*.test.mjs'] } };\n";
    const dir = fixture('r054', `${runner}-${name}`, files);
    const traces = ['1', '2'].map((v) => {
      const r = crun(runner, dir, runner === 'vitest' ? ['run'] : [], { cache: false, env: { TZ: 'UTC', EXAM_V: v } });
      if (r.status !== 0) throw new Error(show(r));
      const dst = path.join(dir, `t${v}.jsonl`);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), dst);
      return dst;
    });
    res[`${runner}:${name}`] = JSON.parse(native.verify(traces)).tests[0].status;
  }
}
console.log(JSON.stringify(res));
"""


def test_n1_node_env_read_outside_the_test_body_is_never_identical(tmp_path):
    node = shutil.which("node")
    addon = ROOT / "node" / "detjs.linux-x64.node"
    if node is None or not addon.exists() or not (ROOT / "node" / "node_modules" / "vitest").exists():
        pytest.skip("node, the addon or node/node_modules missing")
    script = tmp_path / "n1.js"
    script.write_text(NODE_SCRIPT)
    p = subprocess.run([node, str(script), str(ROOT / "node")], cwd=ROOT / "node", capture_output=True, text=True,
                       env=_env(), timeout=1200)
    assert p.returncode == 0, p.stdout + p.stderr
    res = json.loads(p.stdout.strip().splitlines()[-1])
    wrong = {k: v for k, v in res.items() if v == "stable"}
    # EXAM_V was read by every test's code (module scope, hook, a dependency at import) and differs: never identical
    assert not wrong, f"IDENTICAL although a variable the test read differs: {wrong}"


def test_n2_python_module_level_env_read_is_never_identical(tmp_path):
    _write(tmp_path, {"tests/test_mod.py": """\
        import os
        V = os.environ.get("EXAM_V")
        def test_mod():
            assert V is not None
        """})
    traces = []
    for v in ("1", "2"):
        t = tmp_path / f"t{v}.jsonl"
        r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--det",
                            f"--det-trace={t}", "tests/test_mod.py"], cwd=tmp_path, capture_output=True, text=True,
                           env=_env(EXAM_V=v), timeout=300)
        assert "1 passed" in r.stdout, r.stdout + r.stderr
        traces.append(str(t))
    r = _fenvix(tmp_path, "verify", *traces)
    assert "IDENTICAL" not in r.stdout, f"exit {r.returncode}:\n{r.stdout}"


def test_n3_replay_of_an_xfail_run_false_target_is_not_reproduced(tmp_path):
    proj = tmp_path / "proj"
    _write(proj, {
        "tests/__init__.py": "",
        "tests/state.py": "FLAG = {}\n",
        "tests/test_a.py": "from tests.state import FLAG\ndef test_polluter():\n    FLAG['x'] = 1\n",
        "tests/test_b.py": "from tests.state import FLAG\ndef test_victim():\n    assert 'x' not in FLAG\n",
    })
    r = _fenvix(proj, "repro", "tests/test_b.py::test_victim", "--seeds", "2", "--confirm", "2",
                "--out", str(tmp_path / "rep"))
    assert r.returncode == 0, r.stdout + r.stderr
    bundle = next((tmp_path / "rep").glob("test_victim-*"))
    # quarantined with xfail(run=False): the body never runs
    (proj / "tests/test_b.py").write_text("import pytest\n@pytest.mark.xfail(run=False, reason='quarantined')\n"
                                         "def test_victim():\n    raise SystemExit('never runs')\n")
    r = _fenvix(proj, "replay", str(bundle), "--runs", "2")
    assert "REPRODUCED: failed" not in r.stdout.replace("NOT REPRODUCED", "") and r.returncode == 2, \
        f"exit {r.returncode}:\n{r.stdout}{r.stderr}"

