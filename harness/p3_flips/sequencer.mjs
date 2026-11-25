// P3 harness only (never part of a customer repository): a Vitest sequencer for the plain order condition.
//   P3_ORDER=<file>    one test file path per line (relative to the project root): the files run in that order;
//                      files the run has that the list does not name are an error (the run must be invalid, not
//                      silently reordered). Unset: Vitest's own default order (BaseSequencer.sort).
//   P3_APPLIED=<file>  the order this sequencer applied, one relative path per line, written on every run.
// Control and condition use this same sequencer and the same harness config; only P3_ORDER differs.
import fs from 'node:fs';
import path from 'node:path';
import { BaseSequencer } from 'vitest/node';

export default class P3Sequencer extends BaseSequencer {
  async sort(files) {
    let sorted;
    const root = this.ctx.config.root;
    const rel = (spec) => path.relative(root, Array.isArray(spec) ? spec[1] : (spec.moduleId ?? spec.filepath ?? spec));
    if (process.env.P3_ORDER) {
      const want = fs.readFileSync(process.env.P3_ORDER, 'utf8').split('\n').map((l) => l.trim()).filter(Boolean);
      const pos = new Map(want.map((f, i) => [f, i]));
      const missing = files.filter((s) => !pos.has(rel(s)).valueOf()).map(rel);
      if (missing.length) throw new Error(`P3Sequencer: files not in P3_ORDER: ${missing.join(', ')}`);
      sorted = [...files].sort((a, b) => pos.get(rel(a)) - pos.get(rel(b)));
    } else {
      sorted = await super.sort(files);
    }
    if (process.env.P3_APPLIED) fs.writeFileSync(process.env.P3_APPLIED, sorted.map(rel).join('\n') + '\n');
    return sorted;
  }
}
