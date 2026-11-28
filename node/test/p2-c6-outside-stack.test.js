'use strict';
// P2 C6: the outside-files recorder (src/outside.js byProjectOutside) decides from the stack of the fs call whether the
// module loader made it (MODULE_LOADER on the first frame outside detjs, LOADING anywhere). It read that stack as
// `String(new Error().stack)`: 40 frames formatted through the realm's Error.prepareStackTrace, which a repository's
// source-map support (alakajam: @cspotcode/source-map-support) replaces with a source-mapping formatter that reads map
// files from disk, on every fs call made outside a test (every existsSync of module resolution at import). The
// decision only looks at Node's module loader frames and detjs' own frames, which have no source maps, so the same
// stack formatted from the raw call sites gives the same decision without calling the formatter.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const outside = require('../src/outside');

/** The stack as byProjectOutside read it before C6 (formatted by whatever Error.prepareStackTrace is installed). */
function formatted() {
  const E = Error; const prev = E.stackTraceLimit; E.stackTraceLimit = 40;
  try { return String(new E().stack || ''); } finally { E.stackTraceLimit = prev; }
}

test('stackText(): the same frames as V8\'s own Error().stack when no formatter is installed (C6)', () => {
  // protects= the raw text is V8's default format, frame for frame; fails_when= a frame is formatted differently
  // (a function name, async, new, eval origin); no_claim= the source-mapped case (next test)
  const prev = Error.prepareStackTrace; Error.prepareStackTrace = undefined;
  try {
    const both = () => [formatted(), outside.stackText(40, both)];
    const [a, b] = (function nest() { return both(); })();
    // the formatted stack starts at formatted() itself, then both(); the raw one at both()'s caller: from nest() on
    const la = a.split('\n').slice(3); const lb = b.split('\n').slice(1);
    assert.ok(la.length > 3, a);
    assert.deepEqual(lb.slice(0, la.length - 1), la.slice(0, la.length - 1));
  } finally { Error.prepareStackTrace = prev; }
});

test('stackText(): the module-loader decision is unchanged under a source-mapping formatter, which is not called (C6)', () => {
  // protects= byProjectOutside's MODULE_LOADER / LOADING decision is the same as with the formatted stack; and the
  // realm's formatter (source maps) is no longer run for it; fails_when= a decision differs or the formatter runs
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'p2c6-'));
  let calls = 0;
  const prev = Error.prepareStackTrace;
  // a source-map support stand-in: rewrites the position of frames of files it has a "map" for (the test's module)
  Error.prepareStackTrace = (e, cs) => { calls++; return `${e}\n${cs.map((c) => `    at ${String(c).replace(/p2c6-[^/]+\/mod\.js:\d+:\d+/, 'p2c6-src/mod.ts:7:3')}`).join('\n')}`; };
  const decide = (text) => {
    const lines = text.split('\n').slice(1);
    return {
      // byProjectOutside skips detjs' own frames; here also the helper that formatted the stack (formatted())
      loader: outside.MODULE_LOADER.test(lines.find((l) => !l.includes(path.resolve(__dirname, '../src') + path.sep) && !/formatted \(/.test(l)) || ''),
      loading: outside.LOADING.test(text),
    };
  };
  try {
    // 1. code: a plain call; 2. a module's top level being required (the cjs loader on the stack); 3. a call made from
    // inside a function the module exports, after loading
    global.__p2c6 = { fmt: formatted, raw: () => outside.stackText(40, global.__p2c6.raw) };
    fs.writeFileSync(path.join(dir, 'mod.js'), 'const r = [global.__p2c6.fmt(), global.__p2c6.raw()];\nmodule.exports = { r, later: () => [global.__p2c6.fmt(), global.__p2c6.raw()] };\n');
    const cases = [];
    cases.push([formatted(), outside.stackText(40)]);
    const m = require(path.join(dir, 'mod.js'));
    cases.push(m.r);
    cases.push(m.later());
    let before = calls;
    for (const [f, r] of cases) {
      assert.deepEqual(decide(r), decide(f), `raw:\n${r}\n\nformatted:\n${f}`);
    }
    assert.equal(decide(cases[1][1]).loading, true, 'the require case has the loader on its stack');
    assert.equal(decide(cases[2][1]).loading, false, 'the later call has no loader on its stack');
    before = calls;
    outside.stackText(40);
    assert.equal(calls, before, 'stackText() does not run the installed formatter');
  } finally {
    Error.prepareStackTrace = prev;
    delete global.__p2c6;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
