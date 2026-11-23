'use strict';
// One streaming line reader for traces (P0 big trace).
//
// A trace of a large suite is over 1 GB; V8 refuses a string above ~512 MiB (ERR_STRING_TOO_LONG), so reading a
// trace with fs.readFileSync(p, 'utf8') fails exactly on the suites whose results matter most -- and every reader
// that caught the error returned "nothing", which ended runs green with failed tests in the trace. These functions
// never build a string of the whole file: they read 1 MiB chunks into a Buffer, split on the byte 0x0A (never on
// decoded text, so a multibyte UTF-8 character across a chunk border is never cut) and decode one whole line at a
// time. Memory: one chunk plus one line.
//
// A read error is thrown, never caught here. A line longer than MAX_LINE throws an Error with
// code DETJS_TRACE_LINE_TOO_LONG: the caller decides (fail closed), nothing is skipped silently.
const fs = require('node:fs');

const CHUNK = 1 << 20;
const MAX_LINE = 256 * (1 << 20);

function tooLong(path, lineNo, n) {
  const e = new Error(`detjs: line ${lineNo + 1} of the trace ${path} is longer than ${MAX_LINE} bytes (${n}+)`);
  e.code = 'DETJS_TRACE_LINE_TOO_LONG';
  return e;
}

/**
 * Call fn(line, lineNo, byteOffset, byteLength) for every line of the file. `line` is the decoded text without its
 * "\n" and without one trailing "\r"; lineNo counts from 0; byteOffset and byteLength locate the raw line in the file
 * (a "\r" included, the "\n" excluded). The empty piece after a final "\n" is not a line; a last line without "\n"
 * is. `opts.maxLine` overrides the limit (tests).
 */
function forEachLine(path, fn, opts = {}) {
  const max = opts.maxLine || MAX_LINE;
  const fd = fs.openSync(path, 'r');
  try {
    const chunk = Buffer.allocUnsafe(CHUNK);
    let pending = []; // pieces of the current line (Buffers), when it spans chunks
    let pendingLen = 0;
    let lineStart = 0; // byte offset of the current line in the file
    let pos = 0; // byte offset of chunk[0] in the file
    let lineNo = 0;
    const emit = (buf, a, b) => {
      const length = b - a;
      let end = b;
      if (end > a && buf[end - 1] === 0x0d) end--;
      fn(buf.toString('utf8', a, end), lineNo, lineStart, length);
      lineNo++;
    };
    for (;;) {
      const n = fs.readSync(fd, chunk, 0, CHUNK, null);
      if (n === 0) break;
      let a = 0;
      for (;;) {
        const nl = chunk.indexOf(0x0a, a);
        if (nl < 0 || nl >= n) break;
        if (pendingLen) {
          if (pendingLen + (nl - a) > max) throw tooLong(path, lineNo, pendingLen + (nl - a));
          pending.push(chunk.subarray(a, nl));
          const whole = Buffer.concat(pending, pendingLen + (nl - a));
          pending = [];
          pendingLen = 0;
          emit(whole, 0, whole.length);
        } else {
          if (nl - a > max) throw tooLong(path, lineNo, nl - a);
          emit(chunk, a, nl);
        }
        a = nl + 1;
        lineStart = pos + a;
      }
      if (a < n) {
        if (pendingLen + (n - a) > max) throw tooLong(path, lineNo, pendingLen + (n - a));
        pending.push(Buffer.from(chunk.subarray(a, n))); // copied: the chunk buffer is reused
        pendingLen += n - a;
      }
      pos += n;
    }
    if (pendingLen) {
      const whole = Buffer.concat(pending, pendingLen);
      emit(whole, 0, whole.length);
    }
  } finally {
    fs.closeSync(fd);
  }
}

/** The first line of the file (without "\n" and one "\r"), reading only up to the first "\n"; '' for an empty file. */
function firstLine(path, opts = {}) {
  const max = opts.maxLine || MAX_LINE;
  const fd = fs.openSync(path, 'r');
  try {
    const chunk = Buffer.allocUnsafe(CHUNK);
    const parts = [];
    let len = 0;
    for (;;) {
      const n = fs.readSync(fd, chunk, 0, CHUNK, null);
      if (n === 0) break;
      const nl = chunk.indexOf(0x0a);
      const end = nl >= 0 && nl < n ? nl : n;
      if (len + end > max) throw tooLong(path, 0, len + end);
      parts.push(Buffer.from(chunk.subarray(0, end)));
      len += end;
      if (end < n) break;
    }
    let buf = Buffer.concat(parts, len);
    if (buf.length && buf[buf.length - 1] === 0x0d) buf = buf.subarray(0, buf.length - 1);
    return buf.toString('utf8');
  } finally {
    fs.closeSync(fd);
  }
}

/** The raw bytes of one line by offset and length (forEachLine's byteOffset, byteLength), as a Buffer. */
function readLineBytes(fd, offset, length) {
  const buf = Buffer.allocUnsafe(length);
  let got = 0;
  while (got < length) {
    const n = fs.readSync(fd, buf, got, length - got, offset + got);
    if (n === 0) throw new Error(`detjs: trace ended at byte ${offset + got} inside a line (${offset}+${length})`);
    got += n;
  }
  return buf;
}

/** One line's text by offset and length (forEachLine's byteOffset, byteLength). */
function readLineAt(fd, offset, length) {
  return readLineBytes(fd, offset, length).toString('utf8');
}

/** Copy the bytes start..EOF of srcPath to the open descriptor dstFd, in 1 MiB chunks. Returns the bytes copied. */
function copyRange(srcPath, start, dstFd) {
  const fd = fs.openSync(srcPath, 'r');
  try {
    const chunk = Buffer.allocUnsafe(CHUNK);
    let pos = start;
    let total = 0;
    for (;;) {
      const n = fs.readSync(fd, chunk, 0, CHUNK, pos);
      if (n === 0) break;
      let off = 0;
      while (off < n) off += fs.writeSync(dstFd, chunk, off, n - off);
      pos += n;
      total += n;
    }
    return total;
  } finally {
    fs.closeSync(fd);
  }
}

module.exports = { forEachLine, firstLine, readLineAt, readLineBytes, copyRange, MAX_LINE, CHUNK };
