'use strict';
// P2 C4: hazards() of two engines on captured lane markers (tools/keep_lanes.js): identical output, and the time.
// Usage: node bench_hazards.js REF_ENGINE NEW_ENGINE CAPTURE_DIR... [--reps N]
//   REF_ENGINE / NEW_ENGINE: checkouts (their node/src/parallel.js is loaded); CAPTURE_DIR: <out>/<pid>-<n>/ with the
//   marker files (*.json) and plan.json of one run. Prints one line per capture; exit 1 when any output differs.
const fs = require('node:fs');
const path = require('node:path');

const args = process.argv.slice(2);
let reps = 5;
const ri = args.indexOf('--reps');
if (ri >= 0) { reps = Number(args[ri + 1]); args.splice(ri, 2); }
const [refEng, newEng, ...caps] = args;
const ref = require(path.resolve(refEng, 'node/src/parallel.js')).hazards;
const neu = require(path.resolve(newEng, 'node/src/parallel.js')).hazards;

function load(dir) {
  const markers = new Map();
  for (const n of fs.readdirSync(dir).filter((x) => x.endsWith('.json') && x !== 'plan.json').sort()) {
    try { const m = JSON.parse(fs.readFileSync(path.join(dir, n), 'utf8')); markers.set(m.label, m); } catch { /* truncated */ }
  }
  const plan = JSON.parse(fs.readFileSync(path.join(dir, 'plan.json'), 'utf8'));
  return { markers, laneOf: new Map(Object.entries(plan.laneOf)) };
}

function time(fn, markers, laneOf) {
  let best = Infinity; let out;
  for (let i = 0; i < reps; i++) {
    const t0 = process.hrtime.bigint();
    out = fn(markers, laneOf);
    best = Math.min(best, Number(process.hrtime.bigint() - t0) / 1e6);
  }
  return { best, out };
}

let bad = 0;
for (const c of caps) {
  if (!fs.existsSync(path.join(c, 'plan.json'))) continue;
  const { markers, laneOf } = load(c);
  const a = time(ref, markers, laneOf);
  const b = time(neu, markers, laneOf);
  const same = JSON.stringify(a.out) === JSON.stringify(b.out);
  if (!same) bad++;
  let w = 0; let r = 0; let l = 0;
  for (const m of markers.values()) if (m.footprint) { w += m.footprint.w.length; r += m.footprint.r.length; l += m.footprint.l.length; }
  console.log(`${c}: files ${markers.size}, footprint w ${w} r ${r} l ${l}, hazards ${a.out.length}, ref ${a.best.toFixed(1)} ms, new ${b.best.toFixed(1)} ms, identical ${same}`);
}
process.exit(bad ? 1 : 0);
