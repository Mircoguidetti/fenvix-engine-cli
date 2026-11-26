'use strict';
// P2 C2: a free worker slot goes to a file whose lane is free (Vitest 4+, main process).
//
// Vitest's pool (Vitest 4 and later: `class Pool`, `run()` pushes `{ task, resolver, method }` onto `this.queue`,
// `schedule()` starts `this.queue.shift()` whenever a slot is free) starts the files in the order the sequencer
// returned: the plan's dispatch order (planned start times). When a file runs longer than its recorded cost, the
// next file of its lane is still started in the next free slot and waits inside its worker for its lane predecessor
// (src/parallel.js `enter()`), holding the slot; with every slot held this way the run goes one file at a time.
//
// This gives that queue a lane-aware `shift()`: the first queued file whose lane predecessor has finished (or that
// has none), else the first queued file (the old choice, when no queued file can start: every one of them belongs to
// a lane that is busy). Only when every queued task is isolated (a fresh process per file): with isolate=false the
// order decides which files share a process, and Vitest's own order is kept. Nothing else changes: the plan, the lanes, each lane's order and lane exclusivity (enter()
// still waits for the predecessor), the files each process runs (one file per task), and which files run.
// "Finished" is the predecessor's `.done` marker (written by the worker in `leave()` before it reports the file
// finished, or by the main process when Vitest reports the file final), the same marker `enter()` waits for.
//
// The pool is private to Vitest's createPool(); its queue is found on its first push (a one-shot hook on
// Array.prototype.push, removed as soon as the queue is found, or by `uninstall()` when the run did not use such a
// pool: older Vitest versions keep their own order).

function isPoolItem(x) {
  return x !== null && typeof x === 'object' && typeof x.method === 'string' && x.resolver && x.task
    && x.task.context && Array.isArray(x.task.context.files);
}

/**
 * @param {{ plan: () => ({ lanes: string[][] } | null), keyOf: Map<string, string>, finished: (label: string) => boolean }} o
 *   plan: the run's plan, read when the first file is picked (the sequencer makes it inside ctx.start())
 * @returns {{ uninstall: () => void, stats: { picked: number, reordered: number, fallback: number, adopted: boolean } }}
 */
function install({ plan, keyOf, finished }) {
  let pred = null;
  const preds = () => {
    if (pred === null) {
      const p = plan();
      if (!p) return null;
      pred = new Map();
      p.lanes.forEach((l) => l.forEach((k, j) => pred.set(k, j ? l[j - 1] : null)));
    }
    return pred;
  };
  const done = new Set();
  const stats = { picked: 0, reordered: 0, fallback: 0, adopted: false };
  const isDone = (k) => {
    if (done.has(k)) return true;
    const d = finished(k);
    if (d) done.add(k);
    return d;
  };
  const ready = (item, pred) => {
    const f = item.task.context.files[0];
    const key = f && keyOf.get(f.filepath);
    if (!key || !pred.has(key)) return true; // not in the plan: as before
    const p = pred.get(key);
    return p === null || isDone(p);
  };
  function laneShift() {
    if (this.length === 0) return undefined;
    const pr = preds();
    if (pr === null) return Array.prototype.shift.call(this); // no plan (one lane): as before
    // isolate=false: Vitest reuses a runner for the next queued task of the same kind, so the order decides which
    // files share a process (their in-process predecessors): keep Vitest's own order there
    if (this.some((it) => it.task.isolate === false)) return Array.prototype.shift.call(this);
    stats.picked++;
    for (let i = 0; i < this.length; i++) {
      if (ready(this[i], pr)) {
        if (i === 0) return Array.prototype.shift.call(this);
        stats.reordered++;
        return this.splice(i, 1)[0];
      }
    }
    stats.fallback++;
    return Array.prototype.shift.call(this);
  }
  const realPush = Array.prototype.push;
  let hooked = true;
  const uninstall = () => {
    if (hooked && Array.prototype.push === hookPush) Array.prototype.push = realPush; // eslint-disable-line no-extend-native
    hooked = false;
  };
  function hookPush(...items) {
    if (items.length === 1 && isPoolItem(items[0]) && !Object.prototype.hasOwnProperty.call(this, 'shift')) {
      Object.defineProperty(this, 'shift', { value: laneShift, configurable: true, writable: true, enumerable: false });
      stats.adopted = true;
      uninstall();
    }
    return realPush.apply(this, items);
  }
  Array.prototype.push = hookPush; // eslint-disable-line no-extend-native
  return { uninstall, stats };
}

module.exports = { install, isPoolItem };
