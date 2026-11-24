'use strict';
// `detjs verify`: what the traces' headers and orders say about a divergence, added to the core's comparison
// (crates/detpy-core/src/verify.rs, `native.verify`).
//
// * Settings (audit G-1482): traces recorded with a different seed, controls, epoch, tick, timers, network mode, time
//   zone, locale, runner, Node or detjs are compared, but the report says so first: such a difference explains
//   divergences by itself (a different seed gives different random values). The header's `meta` is read; when it
//   carries the run inputs (`meta.inputs`, written by node/src/session.js on the verifier branch) they are compared
//   too, by name.
// * Order (audit G-1483): for a diverging test, the tests that ran before it in one run and not in the other, or
//   before it in both with different results, are named. In-process state left by an earlier test (a global, a
//   module variable) is not an observed source, so an order-dependent failure shows identical events and another
//   outcome: its candidate polluters are the tests that ran before it in the failing run only.
// * Reuse (audit G-1402): a test the cache reused has no events, only the fingerprint and outcome recorded with the
//   reused result (`meta.reused_tests`): it is compared by fingerprint, and a difference is named as a reused result
//   that differs from a fresh run.
const fs = require('node:fs');

// settings that change what a run observes (order of report)
const SETTINGS = [
  ['runner', 'runner'], ['runner_version', 'runner version'], ['node', 'node'], ['runtime_version', 'runtime version'],
  ['detjs', 'detjs'], ['platform', 'platform'], ['seed', 'seed'], ['shuffle', 'shuffle'], ['controls', 'controls'],
  ['epoch_ns', 'epoch'], ['tick_ns', 'tick'], ['tick_adapt', 'tick adaptation'], ['timers', 'timers'],
  ['network', 'network mode'], ['urandom_controlled', 'OS entropy control'], ['tz', 'time zone'], ['locale', 'locale'],
  ['pinned', 'pinned time zone/locale'], ['isolation', 'isolation'], ['cli_args', 'runner arguments'],
];

function readTrace(p) {
  const out = { header: null, tests: [] };
  const STOP = {};
  // streamed (P0 big trace); reading stops at the first line that is not JSON, and an unreadable trace explains
  // nothing (this text decides no exit code)
  try {
    require('./trace-lines').forEachLine(p, (line) => {
      if (!line) return;
      let o;
      try { o = JSON.parse(line); } catch { throw STOP; }
      if (o.type === 'header') out.header = o;
      else if (o.type === 'test') out.tests.push({ nodeid: o.nodeid, outcome: o.outcome, fingerprint: o.fingerprint, index: o.index });
    });
  } catch (e) { if (e !== STOP) return { header: null, tests: [] }; }
  out.tests.sort((a, b) => a.index - b.index);
  return out;
}

const show = (v) => (v === undefined ? '<none>' : typeof v === 'string' ? v : JSON.stringify(v));

/** Settings that differ between run 0 and each other run: [{run, name, a, b}]. */
function settingDifferences(traces) {
  const out = [];
  const m0 = (traces[0].header && traces[0].header.meta) || {};
  for (let r = 1; r < traces.length; r++) {
    const m = (traces[r].header && traces[r].header.meta) || {};
    for (const [k, name] of SETTINGS) {
      if (!(k in m0) && !(k in m)) continue;
      if (JSON.stringify(m0[k]) !== JSON.stringify(m[k])) out.push({ run: r, name, key: k, a: show(m0[k]), b: show(m[k]) });
    }
    const i0 = m0.inputs && typeof m0.inputs === 'object' ? m0.inputs : null;
    const i1 = m.inputs && typeof m.inputs === 'object' ? m.inputs : null;
    if (i0 && i1) {
      const keys = [...new Set([...Object.keys(i0), ...Object.keys(i1)])].sort();
      for (const k of keys) {
        if (i0[k] === i1[k]) continue;
        if (SETTINGS.some(([, n]) => n === k)) continue;
        out.push({ run: r, name: `input ${k}`, key: `inputs.${k}`, a: show(i0[k]), b: show(i1[k]) });
      }
    }
  }
  return out;
}

/** For a diverging test: what ran before it in run a and not in run b (and the reverse), and what differs before it. */
function predecessors(ta, tb, id) {
  const before = (t) => {
    const i = t.tests.findIndex((x) => x.nodeid === id);
    return i < 0 ? [] : t.tests.slice(0, i);
  };
  const pa = before(ta);
  const pb = before(tb);
  const inB = new Map(pb.map((x) => [x.nodeid, x]));
  const inA = new Map(pa.map((x) => [x.nodeid, x]));
  const file = id.split('::', 1)[0];
  const sameFileFirst = (list) => [...list].sort((x, y) => (x.nodeid.split('::', 1)[0] === file ? 0 : 1) - (y.nodeid.split('::', 1)[0] === file ? 0 : 1));
  return {
    onlyA: sameFileFirst(pa.filter((x) => !inB.has(x.nodeid))),
    onlyB: sameFileFirst(pb.filter((x) => !inA.has(x.nodeid))),
    changed: sameFileFirst(pa.filter((x) => inB.has(x.nodeid) && inB.get(x.nodeid).fingerprint !== x.fingerprint)),
  };
}

const names = (list) => list.slice(0, 10).map((x) => `${x.nodeid} (${x.outcome})`).join(', ') + (list.length > 10 ? `, ... ${list.length - 10} more` : '');

/** {lines (before the core's text), notes: nodeid -> [lines], json: extra report fields}. */
function explain(paths, rep) {
  const traces = paths.map(readTrace);
  const diffs = settingDifferences(traces);
  const head = [];
  if (diffs.length) {
    head.push('detjs verify: WARNING: the traces were recorded with different settings; a difference below may come from them, not from the code:');
    for (const d of diffs.slice(0, 40)) head.push(`  run 0 vs ${d.run}: ${d.name}: ${d.a} vs ${d.b}`);
  }
  const reusedIn = traces.map((t) => new Set(((t.header && t.header.meta && t.header.meta.reused_tests) || [])));
  reusedIn.forEach((s, r) => {
    if (s.size) head.push(`detjs verify: run ${r}: ${s.size} test(s) reused from the cache (compared by the fingerprint recorded with the reused result)`);
  });
  const notes = {};
  const order = {};
  for (const t of rep.tests || []) {
    if (t.status !== 'diverged' || !t.divergence) continue;
    const a = t.divergence.run_a ?? 0;
    const b = t.divergence.run_b ?? 1;
    const lines = [];
    const reusedSide = [a, b].filter((r) => reusedIn[r] && reusedIn[r].has(t.nodeid));
    if (reusedSide.length) {
      lines.push(`    reused: the result reused from the cache in run ${reusedSide.join(' and ')} differs from run ${[a, b].find((r) => !reusedSide.includes(r)) ?? b}'s (recorded fingerprint vs fresh): a wrong reuse or a test that is not deterministic`);
    }
    if (traces[a] && traces[b]) {
      const p = predecessors(traces[a], traces[b], t.nodeid);
      if (p.onlyA.length || p.onlyB.length || p.changed.length) {
        order[t.nodeid] = { run_a: a, run_b: b, only_before_in_a: p.onlyA.map((x) => x.nodeid), only_before_in_b: p.onlyB.map((x) => x.nodeid), different_before: p.changed.map((x) => x.nodeid) };
        const failing = t.outcomes ? t.outcomes.findIndex((o) => o !== 'passed' && o !== 'skipped' && o !== 'todo') : -1;
        if (t.divergence.reason === 'outcome-only' && failing >= 0 && (failing === a || failing === b)) {
          const other = failing === a ? b : a;
          const suspects = failing === a ? p.onlyA : p.onlyB;
          const changed = p.changed;
          if (suspects.length || changed.length) {
            lines.push(`    order-dependent: it fails in run ${failing} and passes in run ${other} with identical observed events; `
              + `state left in the process by an earlier test is not observed. Candidates (ran before it in run ${failing} only): ${suspects.length ? names(suspects) : 'none'}`
              + `${changed.length ? `; ran before it in both with different results: ${names(changed)}` : ''}`);
          }
        } else if (t.outcome_stable === false) {
          if (p.onlyA.length) lines.push(`    before it only in run ${a}: ${names(p.onlyA)}`);
          if (p.onlyB.length) lines.push(`    before it only in run ${b}: ${names(p.onlyB)}`);
          if (p.changed.length) lines.push(`    before it in both, different results: ${names(p.changed)}`);
        }
      }
    }
    if (lines.length) notes[t.nodeid] = lines;
  }
  return {
    head,
    notes,
    json: {
      setting_differences: diffs,
      reused_tests: reusedIn.map((s) => [...s]),
      order_explanations: order,
    },
  };
}

/** The core's text with the explanation inserted: settings first, each test's notes under its own lines. */
function annotate(text, ex) {
  const out = [];
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    out.push(lines[i]);
    if (ex.head.length && i > 0 && lines[i].startsWith('  run ') && !(lines[i + 1] || '').startsWith('  run ')) out.push(...ex.head);
    const m = /^NOT-COVERED (.+?) {2}\[/.exec(lines[i]);
    if (m && ex.notes[m[1]]) {
      while (i + 1 < lines.length && lines[i + 1].startsWith('    ')) out.push(lines[++i]);
      out.push(...ex.notes[m[1]]);
    }
  }
  return out.join('\n');
}

module.exports = { explain, annotate, settingDifferences, readTrace };
