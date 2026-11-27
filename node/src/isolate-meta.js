'use strict';
// The trace header of a --det-isolate run, merged from the headers of its per-test sessions (spec "false greens on
// release-1", Phase B). Before, the final header was the FIRST session's: a later session's signals were dropped
// (a read outside any test, a sensor that could not start), and the run could be green without proof.
//
// Every key a per-test session header's `meta` can carry has a rule below (the list and the reasons:
// harness/release1_false_greens/isolate-meta-keys.md). A key without a rule makes the merge fail closed: the run
// declares no sensor (`provable` deleted, `provable_absent` set), so the verifier and the runner report it NOT
// PROVEN, never green. Pure: no file system, no process.

/** Keys of the run's configuration: every session got them from the same outer run, so they must be equal. */
const EQUAL = new Set([
  'cassette_max_age_days', 'controls', 'detjs', 'entropy', 'env_reads_recorded', 'epoch', 'epoch_ns',
  'files_outside_scope', 'inputs', 'isolate', 'locale', 'network', 'node', 'order_seed', 'pinned', 'platform',
  'pool', 'projects', 'runner', 'runner_version', 'runtime', 'runtime_version', 'seed', 'shuffle',
  'tick_adapt', 'tick_ns', 'timers', 'tz', 'urandom_controlled',
]);
/** Run-wide signals: lists, the union over the sessions (deduplicated, in order of first appearance). */
const UNION = new Set(['not_proven_outside_tests', 'env_read_outside_tests', 'files_read_outside_tests', 'notes']);
/** Written by src/isolate.js itself for the whole run (or per session and meaningless for the run): not merged. */
const OWN = new Set(['files', 'isolation', 'isolate_tests', 'reused_tests', 'status', 'cli_args']);
/** Signals of the sensor: their own rule (provable below). */
const SENSOR = new Set(['provable', 'provable_absent']);
/** Other keys with their own rule (mergeSessionMeta). */
const OTHER = new Set(['parallel', 'serial', 'cassette_oldest_days', 'unordered_parts', 'inputs_error', 'hazard_rerun']);

const CACHE_REUSE = 'cache-reuse/1';
/** The core's list (crates/detpy-core/src/provable.rs required_controls); an unknown answer requires everything. */
function defaultRequired(sensor) {
  try { return require('./native').provableRequiredControls(sensor); } catch { return ['<the engine could not name the required controls>']; }
}

/** JSON with sorted object keys: the identity used for "equal" and for deduplicating list entries. */
function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(',')}]`;
  if (v && typeof v === 'object') return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}`;
  return JSON.stringify(v === undefined ? null : v);
}

/**
 * The final meta of a --det-isolate run.
 *   metas      the `meta` of every per-test session that wrote a trace, in run order (a session that wrote none is
 *              already a `missing` test that fails the run: src/isolate.js)
 *   labels     a name for each session (its first test id), for the reasons
 *   cliArgs    the outer run's arguments
 * Returns {meta, failClosed: [reason...]}: when failClosed is not empty, `meta` declares no sensor.
 */
function mergeSessionMeta(metas, labels = [], cliArgs = null, requiredControls = defaultRequired) {
  const name = (i) => labels[i] || `session ${i + 1}`;
  const meta = {};
  const failClosed = [];
  const keys = [];
  for (const m of metas) for (const k of Object.keys(m || {})) if (!keys.includes(k)) keys.push(k);
  for (const k of keys) {
    const has = metas.map((m) => Object.prototype.hasOwnProperty.call(m || {}, k));
    const vals = metas.map((m) => (m || {})[k]);
    if (EQUAL.has(k)) {
      const first = vals[has.indexOf(true)];
      const odd = metas.map((_, i) => i).filter((i) => !has[i] || canon(vals[i]) !== canon(first));
      if (odd.length) failClosed.push(`the per-test sessions differ in ${k} (${odd.map(name).join(', ')})`);
      else meta[k] = first;
    } else if (UNION.has(k)) {
      const seen = new Set();
      const out = [];
      for (const v of vals) {
        if (v === undefined) continue;
        if (!Array.isArray(v)) { failClosed.push(`${k} is not a list in a per-test session`); continue; }
        for (const x of v) { const c = canon(x); if (!seen.has(c)) { seen.add(c); out.push(x); } }
      }
      meta[k] = out;
    } else if (OWN.has(k) || SENSOR.has(k) || OTHER.has(k)) {
      // set below or by src/isolate.js
    } else {
      failClosed.push(`the per-test sessions' header carries ${k}, which the --det-isolate merge has no rule for`);
    }
  }

  // parallel: the per-test sessions run one after another (src/isolate.js, groups.forEach), one file each, so the
  // run as a whole had no parallel lanes. A session's own plan, placement and timing describe that one session only
  // and are not the run's (its lanes timing would be read as the run's). A session that reports a conflict between
  // lanes or carried state is not what a one-file session can produce: fail closed.
  for (let i = 0; i < metas.length; i++) {
    const p = (metas[i] || {}).parallel;
    if (p === undefined) continue;
    if (!p || typeof p !== 'object' || Array.isArray(p)) { failClosed.push(`${name(i)}: meta.parallel is not an object`); continue; }
    // absent or an empty list is nothing; anything else, a truthy non-list included, is not what a one-file session
    // writes (/review adversarial: `{}` has no .length)
    const some = (x) => x !== undefined && x !== null && !(Array.isArray(x) && x.length === 0);
    const placementBad = p.placement !== undefined && p.placement !== null
      && (typeof p.placement !== 'object' || Array.isArray(p.placement) || some(p.placement.deviations));
    if (some(p.hazards) || some(p.carried) || placementBad) {
      failClosed.push(`${name(i)}: its session reported cross-worker hazards, carried state or placement deviations`);
    }
  }
  meta.parallel = { workers: 1, isolate: true };
  // serial: each session's own (a session with a lane plan says false, a fully reused one, with no plan, true); the
  // run's sessions ran one after another
  if (keys.includes('serial')) meta.serial = true;

  // hazard_rerun: a one-lane re-run inside a one-file session (cannot happen: no hazards); its accounting would be
  // that session's only: fail closed
  for (let i = 0; i < metas.length; i++) {
    if ((metas[i] || {}).hazard_rerun !== undefined) failClosed.push(`${name(i)}: its session ran a one-lane re-run (hazard_rerun)`);
  }
  // the oldest cassette any session replayed (days), null when no session used one
  const ages = metas.map((m) => (m || {}).cassette_oldest_days).filter((v) => typeof v === 'number');
  if (keys.includes('cassette_oldest_days')) meta.cassette_oldest_days = ages.length ? Math.max(...ages) : null;
  if (keys.includes('unordered_parts')) meta.unordered_parts = metas.reduce((n, m) => n + (Number((m || {}).unordered_parts) || 0), 0);
  // an inputs error in any session: the run's inputs are incomplete
  const errs = metas.map((m) => (m || {}).inputs_error).filter((v) => v !== undefined);
  if (errs.length) meta.inputs_error = errs.length > 1 ? `${errs[0]} (+${errs.length - 1} more sessions)` : errs[0];
  if (cliArgs) meta.cli_args = cliArgs;

  // provable: kept only when every session declared one and the declarations agree. A session whose tests all came
  // from the cache ran no test and declares `cache-reuse/1` (src/session.js provableField); it agrees with the
  // running sessions' sensor only when it carries the same contract, accounting table and runtime key, every
  // session had the controls both sensors require on (the core's list: native provableRequiredControls), and the
  // session really reused its tests (founder decision 2026-11-25, Phase B). A run whose sessions are all
  // `cache-reuse/1` keeps it.
  const absent = metas.map((m, i) => ({ i, r: (m || {}).provable_absent })).filter((x) => x.r !== undefined);
  const decl = (i) => (metas[i] || {}).provable;
  const without = metas.map((m, i) => i).filter((i) => decl(i) === undefined || decl(i) === null || typeof decl(i) !== 'object');
  const reuseIdx = metas.map((m, i) => i).filter((i) => !without.includes(i) && decl(i).sensor === CACHE_REUSE);
  const runIdx = metas.map((m, i) => i).filter((i) => !without.includes(i) && decl(i).sensor !== CACHE_REUSE);
  let chosen;
  let why;
  if (absent.length) {
    why = `${absent[0].r}${absent.length > 1 ? ` (+${absent.length - 1} more sessions)` : ''}`;
  } else if (!metas.length) {
    why = 'no per-test session wrote a trace';
  } else if (without.length) {
    why = `no sensor declared by ${without.map(name).join(', ')}`;
  } else {
    const ref = runIdx.length ? runIdx[0] : reuseIdx[0];
    const differ = (runIdx.length ? runIdx : reuseIdx).filter((i) => canon(decl(i)) !== canon(decl(ref)));
    if (differ.length) {
      why = `the per-test sessions declared different sensors (${differ.map(name).join(', ')} differ from ${name(ref)})`;
    } else if (runIdx.length && reuseIdx.length) {
      const same = (i) => ['contract', 'surface', 'runtime'].every((k) => canon(decl(i)[k]) === canon(decl(ref)[k]));
      const bad = reuseIdx.filter((i) => !same(i));
      const notReused = reuseIdx.filter((i) => !((metas[i] || {}).reused_tests || []).length);
      let need;
      try {
        need = [...new Set([...requiredControls(CACHE_REUSE), ...requiredControls(decl(ref).sensor)])];
      } catch (e) {
        need = [`<the required controls could not be named: ${e && e.message}>`]; // no session has it on: fails closed
      }
      const off = metas.map((m, i) => i).filter((i) => {
        const on = Array.isArray((metas[i] || {}).controls) ? metas[i].controls : [];
        return need.some((c) => !on.includes(c));
      });
      if (bad.length) why = `${bad.map(name).join(', ')}: cache-reuse/1 with another contract, accounting table or runtime key than ${name(ref)}'s sensor`;
      else if (notReused.length) why = `${notReused.map(name).join(', ')}: declared cache-reuse/1 and reused no test`;
      else if (off.length) why = `${off.map(name).join(', ')}: a control the sensors require was off (required: ${need.join(', ')})`;
      else chosen = decl(ref);
    } else {
      chosen = decl(ref);
    }
  }
  if (why !== undefined) meta.provable_absent = why;
  if (failClosed.length && meta.provable_absent === undefined) meta.provable_absent = `--det-isolate: ${failClosed[0]}${failClosed.length > 1 ? ` (+${failClosed.length - 1} more)` : ''}`;
  if (meta.provable_absent === undefined) meta.provable = chosen;
  return { meta, failClosed };
}

module.exports = { mergeSessionMeta, EQUAL, UNION, OWN, SENSOR, OTHER };
