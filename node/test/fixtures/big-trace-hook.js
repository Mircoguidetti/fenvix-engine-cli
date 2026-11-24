'use strict';
// Fault injection for test/big-trace.test.js, loaded with NODE_OPTIONS=--require <this file> into every process of a
// detjs run. BIG_TRACE_HOOK selects the fault; nothing is changed when it is unset.
//
//   rename        fs.renameSync throws for paths containing `.status-` (the stamp of meta.status: src/session.js
//                 stampStatus), in every process. Tests run as root, so a read-only directory cannot do it.
//   wrapper-read  fs.openSync(BIG_TRACE_TARGET, 'r') throws EIO in the hazard re-run wrapper only (the passes carry
//                 DETJS_HAZARD_RERUN=1): pass 1 writes its trace, the wrapper cannot read it back.
//   part-read     fs.openSync(<a trace part>, 'r') throws EIO (paths containing `/parts/`), outside --det-isolate children:
//                 session.finish cannot read a part's ids (partIds).
//   trace-read    fs.openSync(<path ending /.detjs/trace.jsonl>, 'r') throws EIO, outside --det-isolate children: the
//                 merged trace cannot be read back (stampStatus returns null).
//   merge-skip    native.mergeTraces is given its first part with a line that is not JSON appended, so the real merge
//                 (crates/detpy-core/src/trace.rs concat_traces) cannot read that part and reports it in `skipped`;
//                 only in a process that is not a --det-isolate child (DETJS_ISOLATE_CHILD) and has parts to merge.
const fs = require('node:fs');

const mode = process.env.BIG_TRACE_HOOK;

if (mode === 'rename') {
  const orig = fs.renameSync;
  fs.renameSync = function renameSync(a, b) {
    if (String(a).includes('.status-')) {
      const e = new Error(`injected rename failure: ${a}`);
      e.code = 'EIO';
      throw e;
    }
    return orig.call(this, a, b);
  };
}

if (mode === 'wrapper-read' && process.env.DETJS_HAZARD_RERUN !== '1') {
  const target = process.env.BIG_TRACE_TARGET;
  const orig = fs.openSync;
  fs.openSync = function openSync(p, flags, ...rest) {
    if (String(p) === target && (flags === undefined || flags === 'r')) {
      const e = new Error(`injected read error: ${p}`);
      e.code = 'EIO';
      throw e;
    }
    return orig.call(this, p, flags, ...rest);
  };
}

if (mode === 'merge-skip' && process.env.DETJS_ISOLATE_CHILD !== '1') {
  const Module = require('node:module');
  const origLoad = Module._load;
  Module._load = function load(...args) {
    const out = origLoad.apply(this, args);
    if (out && typeof out.mergeTraces === 'function' && !out.__bigTraceWrapped) {
      const real = out.mergeTraces;
      out.mergeTraces = function mergeTraces(parts, ...rest) {
        if (parts && parts.length) fs.appendFileSync(parts[0], '{"type":"test", not json\n');
        return real.call(this, parts, ...rest);
      };
      out.__bigTraceWrapped = true;
    }
    return out;
  };
}

if ((mode === 'part-read' || mode === 'trace-read') && process.env.DETJS_ISOLATE_CHILD !== '1') {
  const orig = fs.openSync;
  const hit = mode === 'part-read' ? (p) => p.includes('/parts/') : (p) => p.endsWith('/.detjs/trace.jsonl');
  fs.openSync = function openSync(p, flags, ...rest) {
    if (hit(String(p)) && (flags === undefined || flags === 'r')) {
      const e = new Error(`injected read error: ${p}`);
      e.code = 'EIO';
      throw e;
    }
    return orig.call(this, p, flags, ...rest);
  };
}
