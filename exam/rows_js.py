"""Node rows JS-01 .. JS-09."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import fam
import lib
from lib import Ctx, Skip

DET2 = "two --det runs verify identical (0 divergent, 0 missing) and outcomes equal a plain run's"
CACHE2 = "second --det-cache run reuses >= 50% of passing tests with proof; outcomes equal the plain run's"

VITEST = os.environ.get("EXAM_VITEST", "3")
JEST = os.environ.get("EXAM_JEST", "29")


def _ufo(ctx, pm="npm", vitest=None):
    v = vitest or VITEST
    return fam.js_setup(ctx, "ufo", pm, [f"vitest@{v}"] if pm == "npm" else [f"vitest@{v}"], key=f"ufo-{pm}-v{v}")


def _npm_legacy(ctx, d, extra=None):
    key = f"node:{d}:npm"
    if key in ctx._venvs:
        return
    cmd = ("npm ci --no-audit --no-fund --ignore-scripts" if (d / "package-lock.json").exists() and not extra
           else "npm install --no-audit --no-fund --ignore-scripts --legacy-peer-deps")
    rc, out = ctx.sh("npm-install", cmd, cwd=d, timeout=1800)
    if rc != 0:
        raise Skip(f"npm install failed: {out[-400:]}")
    if extra:
        rc, out = ctx.sh("npm-extra", f"npm install --no-audit --no-fund --ignore-scripts --legacy-peer-deps -D {' '.join(extra)}",
                         cwd=d, timeout=1800)
        if rc != 0:
            raise Skip(f"npm add {extra} failed: {out[-400:]}")
    ctx._venvs[key] = d


def setup(ctx: Ctx, name: str, extra=None, key=None, build=None) -> Path:
    from projects import P
    d = ctx.clone(P[name], name=key or name)
    ctx.need_install()
    _npm_legacy(ctx, d, extra)
    if build and not (d / ".exam-built").exists():
        rc, out = ctx.sh(f"build-{name}", build, cwd=d, timeout=1800)
        if rc != 0:
            raise Skip(f"build failed: {out[-300:]}")
        (d / ".exam-built").write_text("1")
    return d


# runner -> (project, extra devDependencies, args, build, runner key)
PROJ = {
    "ufo": ("ufo", [f"vitest@{VITEST}"], "", None, "vitest"),
    "zustand": ("zustand", [f"vitest@{VITEST}", "jsdom@25"], "tests", None, "vitest"),
    "simple-statistics": ("simple-statistics", [], "--experimental-test-isolation=none test/*.test.js", None, "node-test"),
    "luxon": ("luxon", [f"jest@{JEST}"], "test", None, "jest"),
    "class-validator": ("class-validator", [f"jest@{JEST}", f"ts-jest@{JEST}"], "", None, "jest"),
    "express": ("express", [], "--require test/support/env --check-leaks test/ test/acceptance/", None, "mocha"),
    "p-map": ("p-map", ["ava@6"], "", None, "ava"),
    "minimatch": ("minimatch", [], "", "npm run prepare", "tap"),
    "dequal": ("dequal", [], "-r esm test", "npm run build", "uvu"),
    "jasmine-npm": ("jasmine-npm", ["jasmine@5"], "", None, "jasmine"),
    "elysia": ("elysia", [], "test/core", None, "bun-test"),
    "oak": ("oak", [], "--allow-all", None, "deno-test"),
    "tabbable": ("tabbable", [], "", None, "jest"),
}


def proj(ctx, key) -> tuple:
    name, extra, args, build, runner = PROJ[key]
    if runner == "deno-test":
        from projects import P
        d = ctx.clone(P[name])
        ctx.need_install()
        return d, runner, args
    if runner == "bun-test":
        from projects import P
        d = ctx.clone(P[name])
        ctx.need_install()
        if not (d / "node_modules").exists():
            rc, out = ctx.sh("bun-install", "bun install", cwd=d, timeout=1800)
            if rc != 0:
                raise Skip(f"bun install failed: {out[-300:]}")
        return d, runner, args
    return setup(ctx, name, extra, key=f"{name}-{'-'.join(extra)}", build=build), runner, args


def det2(ctx, cid, key, env=None):
    def fn():
        d, runner, args = proj(ctx, key)
        return fam.js_det2(ctx, d, runner, args, f"{cid}-{key}", env=env)
    ctx.run_check(f"{cid}.{key}", DET2, fn)


def cache2(ctx, cid, key, env=None):
    def fn():
        d, runner, args = proj(ctx, key)
        return fam.js_cache2(ctx, d, runner, args, f"{cid}-{key}", env=env)
    ctx.run_check(f"{cid}.{key}", CACHE2, fn)


def _install_check(ctx, cid):
    def fn():
        ctx.need_install()
        rc, out = ctx.sh("fenvix-version", ["fenvix", "version"])
        line = [x for x in out.splitlines() if x.startswith("detjs")]
        ok = rc == 0 and bool(line) and "unavailable" not in line[0]
        rc2, out2 = ctx.sh("node-version", ["node", "--version"])
        return ok, f"fenvix version: {line}; node {out2.strip()}"
    ctx.run_check(cid, "install succeeds; `fenvix version` prints detjs", fn)


def JS_01(ctx: Ctx):
    _install_check(ctx, "JS-01.install")
    for k in ("simple-statistics", "ufo"):
        det2(ctx, "JS-01.det2", k)
        cache2(ctx, "JS-01.cache2", k)


def JS_02(ctx: Ctx):
    which = os.environ.get("EXAM_VARIANT", f"vitest{VITEST}")
    keys = ("ufo", "zustand") if which.startswith("vitest") else ("luxon", "class-validator")
    for k in keys:
        det2(ctx, f"JS-02.det2.{which}", k)
        cache2(ctx, f"JS-02.cache2.{which}", k)

    def seed(k=keys[0]):
        d, runner, args = proj(ctx, k)
        digs, outs = [], []
        for i in (1, 2):
            rc, out, o = fam.js_run(ctx, d, runner, args, f"seed{i}", True, "--det --det-seed=5")
            m = re.findall(r"order digest ([0-9a-f]+)", out)
            digs.append(m[-1] if m else None)
            outs.append(o)
        return digs[0] is not None and digs[0] == digs[1] and outs[0] == outs[1], f"order digests {digs}; outcomes equal {outs[0] == outs[1]}"
    ctx.run_check(f"JS-02.seed.{which}", "--det --det-seed=5 twice: same order digest, outcomes equal", seed)


def JS_03(ctx: Ctx):
    for k in ("express", "simple-statistics", "p-map", "minimatch", "dequal", "jasmine-npm", "elysia", "oak"):
        runner = PROJ[k][4]
        det2(ctx, f"JS-03.{runner}.det2", k)
        cache2(ctx, f"JS-03.{runner}.cache2", k)


PW_PROBE = """
import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';
test('exam page clock', async ({ page }) => {
  await page.setContent('<html><body>x</body></html>');
  const v = await page.evaluate(() => [Date.now(), Math.random(), new Date().toString(),
                                       Intl.DateTimeFormat().resolvedOptions().timeZone]);
  if (process.env.EXAM_OUT) writeFileSync(process.env.EXAM_OUT, JSON.stringify(v));
  expect(v.length).toBe(4);
});
"""


def _pw(ctx):
    from projects import P
    d = ctx.clone(P["pw-coverage"])
    ctx.need_install()
    _npm_legacy(ctx, d)
    if not (d / ".exam-pw").exists():
        rc, out = ctx.sh("pw-install", "npx playwright install --with-deps chromium", cwd=d, timeout=1800)
        if rc != 0:
            raise Skip(f"playwright install failed: {out[-300:]}")
        (d / ".exam-pw").write_text("1")
    return d


def JS_04(ctx: Ctx):
    def shell():
        ctx.need_install()
        rc, out = ctx.sh("pw-shell", "fenvix node playwright test --help")
        usage = "usage: detjs" in out
        return rc == 0 and not usage, f"rc={rc}; prints detjs usage: {usage}"
    ctx.run_check("JS-04.shell", "`fenvix node playwright test --det` is a shell (not the usage text)", shell)

    def det():
        d = _pw(ctx)
        rc0, out0 = ctx.sh("pw-plain", "npx playwright test --project=Chrome --reporter=line", cwd=d, timeout=1800)
        t = [ctx.work / "pw1.jsonl", ctx.work / "pw2.jsonl"]
        for i in (0, 1):
            ctx.sh(f"pw-det{i}", f"fenvix node playwright test --det --det-trace={t[i]} --project=Chrome --reporter=line", cwd=d, timeout=1800)
        vok, vdesc, _ = lib.verify(ctx, d, {}, t[0], t[1], "pw-verify")
        return vok, f"plain rc={rc0}; verify: {vdesc}"
    ctx.run_check("JS-04.det2", DET2, det)

    def clock():
        d = _pw(ctx)
        lib.write(d / "tests/exam-clock.spec.ts", PW_PROBE)
        vals = []
        for i in (0, 1):
            o = ctx.work / f"pwc{i}.out"
            ctx.sh(f"pw-clock{i}", f"fenvix node playwright test --det --project=Chrome tests/exam-clock.spec.ts", cwd=d,
                   env={"EXAM_OUT": str(o)}, timeout=1800)
            vals.append(o.read_text() if o.exists() else None)
        (d / "tests/exam-clock.spec.ts").unlink(missing_ok=True)
        return vals[0] is not None and vals[0] == vals[1], f"page values {vals}"
    ctx.run_check("JS-04.browser-clock", "page Date.now()/Math.random() equal in two --det runs", clock)


def JS_05(ctx: Ctx):
    for kind, k in (("esm-ava", "p-map"), ("esm-ts-vitest", "ufo"), ("cjs-mocha", "express"), ("ts-jest", "class-validator")):
        det2(ctx, f"JS-05.{kind}.det2", k)
        cache2(ctx, f"JS-05.{kind}.cache2", k)

    def ts_edit():
        d, runner, args = proj(ctx, "class-validator")
        cache = ctx.work / "cv-edit-cache"
        import shutil
        shutil.rmtree(cache, ignore_errors=True)
        fam.js_run(ctx, d, runner, args, "cv-run1", True, f"--det --det-cache={cache}")
        f = d / "src/decorator/common/IsDefined.ts"
        if not f.exists():
            raise Skip("src/decorator/common/IsDefined.ts not found")
        s = f.read_text()
        f.write_text(s.replace("should not be null or undefined", "must not be null or undefined"))
        shutil.rmtree(d / ".detjs", ignore_errors=True)
        rc2, out2, j2 = fam.js_run(ctx, d, runner, args, "cv-run2", True, f"--det --det-cache={cache}")
        o2, n = fam._receipt_outcomes(d, j2)
        rcp, _, plain = fam.js_run(ctx, d, runner, args, "cv-plain", False)
        ctx.reset(d)
        ok, desc = fam.js_cmp({"files": o2}, plain)
        return ok and n > 0, f"edit IsDefined message; run 2 reused {n}; vs plain rerun: {desc}"
    ctx.run_check("JS-05.ts-edit", "EDIT on TypeScript source: dependent files rerun, outcomes equal plain", ts_edit)


JSDOM_TZ = """
import { test } from 'vitest';
import { writeFileSync } from 'node:fs';
test('exam tz locale', () => {
  const v = [new Date(0).toString(), Intl.DateTimeFormat().resolvedOptions().timeZone,
             Intl.DateTimeFormat().resolvedOptions().locale, (1234.5).toLocaleString()];
  if (process.env.EXAM_OUT) writeFileSync(process.env.EXAM_OUT, JSON.stringify(v));
});
"""


def JS_06(ctx: Ctx):
    det2(ctx, "JS-06.jsdom-vitest.det2", "zustand")
    cache2(ctx, "JS-06.jsdom-vitest.cache2", "zustand")
    det2(ctx, "JS-06.jsdom-jest.det2", "tabbable")
    cache2(ctx, "JS-06.jsdom-jest.cache2", "tabbable")

    def hd(kind):
        def fn():
            d = setup(ctx, "zustand", [f"vitest@{VITEST}", "jsdom@25", "happy-dom@17"], key="zustand-happy")
            f = fam.js_det2 if kind == "det2" else fam.js_cache2
            return f(ctx, d, "vitest", "tests --environment happy-dom", f"hd-{kind}")
        return fn
    ctx.run_check("JS-06.happy-dom.det2", DET2, hd("det2"))
    ctx.run_check("JS-06.happy-dom.cache2", CACHE2, hd("cache2"))

    def tz():
        d = setup(ctx, "zustand", [f"vitest@{VITEST}", "jsdom@25"], key=f"zustand-vitest@{VITEST}-jsdom@25")
        r = fam.js_value_probe(ctx, d, "vitest", "tests/exam-tz.test.ts", JSDOM_TZ,
                               [{"TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                                {"TZ": "Asia/Tokyo", "LANG": "de_DE.UTF-8", "LC_ALL": "de_DE.UTF-8"}],
                               args="--environment jsdom")
        v = r["values"]
        return v[0] is not None and v[0] == v[1], f"values {v}; verify {r['verify']}"
    ctx.run_check("JS-06.tz-locale", "jsdom Date/Intl values equal under different TZ/LANG", tz)


WORKER_ID = """
import { test } from 'vitest';
import { writeFileSync, readdirSync, appendFileSync } from 'node:fs';
// concurrency probe: each file announces itself, then waits (real blocking wait, no timers) until another file
// announced itself; a serial run never sees a second announcement while this file runs
test('exam concurrent files', () => {
  const dir = process.env.EXAM_DIR;
  writeFileSync(`${dir}/${process.pid}-${Math.floor(performance.timeOrigin)}-${__filename.length}-${Date.now()}-${Math.random()}`, '');
  const sab = new Int32Array(new SharedArrayBuffer(4));
  let seen = 0;
  for (let i = 0; i < 60; i++) {
    seen = readdirSync(dir).length;
    if (seen >= 2) break;
    Atomics.wait(sab, 0, 0, 50);
  }
  appendFileSync(process.env.EXAM_OUT, `${seen}\\n`);
});
"""


def JS_07(ctx: Ctx):
    def kept():
        d = _ufo(ctx)
        for i in range(4):
            lib.write(d / f"test/exam-w{i}.test.ts", WORKER_ID)
        o = ctx.work / "workers.out"
        o.write_text("")
        dd = ctx.work / "workers.dir"
        import shutil
        shutil.rmtree(dd, ignore_errors=True)
        dd.mkdir()
        rc, out = ctx.sh("par-det", "fenvix node vitest run --det test/exam-w", cwd=d, env={"EXAM_OUT": str(o), "EXAM_DIR": str(dd)})
        seen = [int(x) for x in o.read_text().split() if x.isdigit()]
        for i in range(4):
            (d / f"test/exam-w{i}.test.ts").unlink(missing_ok=True)
        serial = "serial execution" in out
        first = seen[0] if seen else None
        return first is not None and first >= 2, \
            f"files announced while the first file ran: {first} (per file: {seen}); engine says serial: {serial}"
    ctx.run_check("JS-07.kept", "under --det the Vitest run uses >= 2 workers", kept, gaps=["G-1044"])

    def jest_par():
        d, runner, args = proj(ctx, "luxon")
        rc, out = ctx.sh("jest-par", f"fenvix node jest --ci --det -w 2 {args}", cwd=d)
        inband = bool(re.search(r"in ?band|serial|one worker", out, re.I))
        return not inband and rc == 0, f"rc={rc}; engine forces serial/in-band: {inband}"
    ctx.run_check("JS-07.jest-kept", "under --det `jest -w 2` keeps 2 workers", jest_par)
    det2(ctx, "JS-07.det2", "ufo")
    cache2(ctx, "JS-07.cache2", "ufo")


def JS_08(ctx: Ctx):
    pm = os.environ.get("EXAM_VARIANT") or "npm"

    def ufo_pm():
        from projects import P
        d = ctx.clone(P["ufo"], name=f"ufo-pm-{pm}")
        ctx.need_install()
        lib.npm_install(ctx, d, pm if pm != "npm" else "npm", [f"vitest@{VITEST}"] if pm != "npm" else None)
        if pm == "npm":
            _npm_legacy(ctx, d, [f"vitest@{VITEST}"])
        return d

    def d2():
        return fam.js_det2(ctx, ufo_pm(), "vitest", "", f"pm-{pm}-det")
    ctx.run_check(f"JS-08.{pm}.det2", DET2, d2)

    def c2():
        return fam.js_cache2(ctx, ufo_pm(), "vitest", "", f"pm-{pm}-cache")
    ctx.run_check(f"JS-08.{pm}.cache2", CACHE2, c2)


CHILD_JS = """
import { test, expect } from 'vitest';
import { execFileSync } from 'node:child_process';
test('exam child output', () => {
  expect(execFileSync('cat', [process.env.EXAM_F]).toString()).toBe('a');
});
"""

WORKER_JS = """
import { test, expect } from 'vitest';
import { Worker } from 'node:worker_threads';
test('exam worker output', async () => {
  const v = await new Promise((res, rej) => {
    const w = new Worker(`const {parentPort}=require('node:worker_threads');parentPort.postMessage(require('node:fs').readFileSync(${JSON.stringify(process.env.EXAM_F)},'utf8'))`, { eval: true });
    w.on('message', res); w.on('error', rej);
  });
  expect(v).toBe('a');
});
"""

NATIVE_JS = """
import { test, expect } from 'vitest';
import { execFileSync } from 'node:child_process';
test('exam native env read', () => {
  expect(execFileSync('sh', ['-c', 'echo -n $EXAM_X']).toString()).toBe('a');
});
"""


def JS_09(ctx: Ctx):
    f = ctx.work / "exam-jf.txt"

    def mk(rel, body, env1, env2, between):
        def fn():
            d = _ufo(ctx)
            f.write_text("a")
            return fam.js_cache_probe(ctx, d, "vitest", rel, body, env1, env2, between)
        return fn
    flip = lambda d: f.write_text("b")
    e = {"EXAM_F": str(f)}
    ctx.run_check("JS-09.child", "a test reading a child process's output is not reused after the input changed",
                  mk("test/exam-child.test.ts", CHILD_JS, e, e, flip))
    ctx.run_check("JS-09.worker", "a worker_threads read that changed is not reused",
                  mk("test/exam-worker.test.ts", WORKER_JS, e, e, flip), gaps=["G-0152"])
    ctx.run_check("JS-09.native", "an env read in a child that changed is not reused",
                  mk("test/exam-native.test.ts", NATIVE_JS, {"EXAM_X": "a"}, {"EXAM_X": "b"}, None), gaps=["G-0124"])
