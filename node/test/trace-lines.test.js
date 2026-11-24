'use strict';
// P0 big trace: src/trace-lines.js, the one streaming line reader every trace reader of detjs uses (a 1.2 GB trace
// does not fit in one JavaScript string). Real files in a temporary directory; chunks are 1 MiB, so the border cases
// use files of a few MiB.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { forEachLine, firstLine, readLineAt, copyRange, CHUNK, MAX_LINE } = require('../src/trace-lines');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-lines-'));
const file = (name, data) => { const p = path.join(dir, name); fs.writeFileSync(p, data); return p; };
const collect = (p, opts) => { const out = []; forEachLine(p, (line, n, off, len) => out.push({ line, n, off, len }), opts); return out; };

/** What forEachLine must give for `buf`: split on "\n" bytes, one "\r" stripped, no line after a final "\n". */
function expected(buf) {
  const out = [];
  let a = 0;
  let n = 0;
  for (;;) {
    const nl = buf.indexOf(0x0a, a);
    const end = nl < 0 ? buf.length : nl;
    if (nl < 0 && a === buf.length) break;
    let e = end;
    if (e > a && buf[e - 1] === 0x0d) e--;
    out.push({ line: buf.toString('utf8', a, e), n: n++, off: a, len: end - a });
    if (nl < 0) break;
    a = nl + 1;
  }
  return out;
}

test('protects=lines and byte offsets across 1 MiB chunk borders; fails_when=a line that spans two chunks is split, merged with its neighbour, or located at the wrong offset; no_claim=files above a few MiB (the >600 MiB tests cover that)', () => {
  const parts = [];
  // lengths around the chunk size, including a "\n" exactly at the last byte of a chunk and a line of 2.5 chunks
  for (const len of [10, CHUNK - 11 - 1, 0, 5, CHUNK, 3, Math.floor(CHUNK * 2.5), 7]) parts.push('x'.repeat(len));
  const buf = Buffer.from(`${parts.join('\n')}\n`);
  assert.equal(buf.indexOf(0x0a, 11), CHUNK - 1, 'a newline is the last byte of the first chunk');
  const p = file('border.txt', buf);
  const got = collect(p);
  assert.deepEqual(got.map((g) => ({ ...g, line: g.line.length })), expected(buf).map((g) => ({ ...g, line: g.line.length })));
  for (const g of got) assert.equal(buf.toString('utf8', g.off, g.off + g.len).length, g.line.length);
});

test('protects=a multibyte UTF-8 character that straddles a chunk border is decoded whole; fails_when=the reader decodes per chunk (U+FFFD replacement characters); no_claim=invalid UTF-8 in a trace', () => {
  const pre = 'a'.repeat(CHUNK - 1); // the 3-byte euro sign starts at the last byte of the first chunk
  const buf = Buffer.from(`${pre}€b\nü€\n`);
  assert.equal(buf[CHUNK - 1], 0xe2);
  const got = collect(file('multibyte.txt', buf));
  assert.equal(got.length, 2);
  assert.equal(got[0].line, `${pre}€b`);
  assert.ok(!got[0].line.includes('�'));
  assert.equal(got[1].line, 'ü€');
  assert.equal(got[1].off, CHUNK - 1 + 3 + 1 + 1);
});

test('protects=CRLF lines lose exactly one "\\r" in the text but keep it in the byte length; fails_when=a "\\r" reaches a JSON consumer or the raw length used for a byte copy drops it; no_claim=lone "\\r" line breaks (not a line end)', () => {
  const buf = Buffer.from('{"a":1}\r\n\r\nx\r\r\nlast\r');
  const got = collect(file('crlf.txt', buf));
  assert.deepEqual(got, expected(buf));
  assert.deepEqual(got.map((g) => g.line), ['{"a":1}', '', 'x\r', 'last']);
  assert.deepEqual(got.map((g) => g.len), [8, 1, 3, 5]);
  assert.equal(firstLine(file('crlf1.txt', buf)), '{"a":1}');
});

test('protects=a last line without "\\n" is a line, and the empty piece after a final "\\n" is not; fails_when=a crashed producer\'s last record is dropped or an extra empty line is reported; no_claim=whether that last line is valid JSON', () => {
  assert.deepEqual(collect(file('nonl.txt', 'a\nb')).map((g) => g.line), ['a', 'b']);
  assert.deepEqual(collect(file('nl.txt', 'a\nb\n')).map((g) => g.line), ['a', 'b']);
  assert.deepEqual(collect(file('only-nl.txt', '\n')).map((g) => g.line), ['']);
  assert.equal(firstLine(file('nonl1.txt', 'head')), 'head');
});

test('protects=an empty file has no lines and an empty first line; fails_when=an empty trace yields a phantom line; no_claim=what callers conclude from an empty trace (no header: unreadable)', () => {
  const p = file('empty.txt', '');
  assert.deepEqual(collect(p), []);
  assert.equal(firstLine(p), '');
});

test('protects=a read error is thrown to the caller; fails_when=the reader swallows it and reports "no lines" (the original false green); no_claim=every errno', () => {
  const sub = path.join(dir, 'a-directory');
  fs.mkdirSync(sub, { recursive: true });
  assert.throws(() => forEachLine(sub, () => {}), (e) => e.code === 'EISDIR');
  assert.throws(() => forEachLine(path.join(dir, 'absent.txt'), () => {}), (e) => e.code === 'ENOENT');
  assert.throws(() => firstLine(sub), (e) => e.code === 'EISDIR');
});

test('protects=a line over the limit throws DETJS_TRACE_LINE_TOO_LONG, within a chunk and across chunks; fails_when=an oversized line is skipped, truncated or read anyway; no_claim=the default 256 MiB value (tested with a lowered limit)', () => {
  assert.equal(MAX_LINE, 256 * 1024 * 1024);
  const small = file('long.txt', `ok\n${'y'.repeat(200)}\nok\n`);
  const seen = [];
  assert.throws(() => forEachLine(small, (l) => seen.push(l), { maxLine: 100 }), (e) => e.code === 'DETJS_TRACE_LINE_TOO_LONG' && /line 2 /.test(e.message));
  assert.deepEqual(seen, ['ok']);
  const spanning = file('long2.txt', `${'z'.repeat(CHUNK + 50)}\n`);
  assert.throws(() => forEachLine(spanning, () => {}, { maxLine: CHUNK }), (e) => e.code === 'DETJS_TRACE_LINE_TOO_LONG');
  assert.throws(() => firstLine(spanning, { maxLine: CHUNK }), (e) => e.code === 'DETJS_TRACE_LINE_TOO_LONG');
  // at the limit: read
  assert.equal(collect(spanning, { maxLine: CHUNK + 50 }).length, 1);
});

test('protects=readLineAt returns the text of the line forEachLine located; fails_when=offset or length are off by one (a neighbouring byte or a cut character); no_claim=lines changed after they were located', () => {
  const buf = Buffer.from(`h\r\n${'p'.repeat(CHUNK)}é\nlast€`);
  const p = file('at.txt', buf);
  const got = collect(p);
  const fd = fs.openSync(p, 'r');
  try {
    assert.deepEqual(got.map((g) => readLineAt(fd, g.off, g.len)), ['h\r', `${'p'.repeat(CHUNK)}é`, 'last€']);
  } finally { fs.closeSync(fd); }
});

test('protects=copyRange copies bytes start..EOF exactly, across chunks; fails_when=bytes are lost, duplicated or re-encoded at a chunk border; no_claim=copying a file that grows during the copy', () => {
  const crypto = require('node:crypto');
  const buf = crypto.randomBytes(CHUNK * 2 + 123);
  const p = file('copy.bin', buf);
  for (const start of [0, 7, CHUNK, buf.length]) {
    const out = path.join(dir, `copy-${start}.bin`);
    const fd = fs.openSync(out, 'w');
    fs.writeSync(fd, 'HEAD');
    const n = copyRange(p, start, fd);
    fs.closeSync(fd);
    assert.equal(n, buf.length - start);
    assert.ok(fs.readFileSync(out).equals(Buffer.concat([Buffer.from('HEAD'), buf.subarray(start)])), `start ${start}`);
  }
});

test.after(() => fs.rmSync(dir, { recursive: true, force: true }));
