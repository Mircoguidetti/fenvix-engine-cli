'use strict';
// Reuse decided per group of files that share one process one after the other (audit G-1475, G-0402).
//
// Vitest `isolate: false` runs a project's files in one worker without resetting its module cache and globals, and a
// custom Jest runner (jest-light-runner in band) imports every file into the same process: a file's result may then
// depend on the state the files before it left. Such files form a group (every file of those projects, in execution
// order). The rule (the carried-set rule):
//
//   * the group itself is an input of each of its files: the ordered list of the group's files is part of their
//     projects' configuration digest (`key`), so a run that selects other files, or orders them otherwise, reuses none;
//   * a group is reused all together or run all together: if one of its files cannot be reused, the files that could
//     be reused run as well (their receipts say why), so that no file ever runs after a different set of files than
//     the one it was recorded after.
//
// With every file's own inputs unchanged (each file's own check) and the same files in the same order, every file of
// the group runs as it did when recorded; when any of that differs, the whole group runs.
const { stable } = require('./proof');

/** The group's identity: ordered list of `project|fileId` keys. */
function groupPart(keys) {
  return stable(keys.slice());
}

/**
 * After `pc.decide(files)`: undo the reuse of every file of `group` (keys) unless every file of the group is reused.
 * `skip` is the set decide() returned (mutated). Returns the number of files demoted.
 */
function demote(pc, group, skip) {
  if (!group.length) return 0;
  const all = group.every((k) => pc.reusedFiles.has(k));
  if (all) return 0;
  const missing = group.filter((k) => !pc.reusedFiles.has(k));
  const why = `group: ${missing.length} other file(s) of the same process group must run (${missing.slice(0, 3).join(', ')}${missing.length > 3 ? ', ...' : ''}); state is carried between these files, so they run together`;
  let n = 0;
  for (const k of group) {
    const r = pc.reusedFiles.get(k);
    if (!r) continue;
    pc.reusedFiles.delete(k);
    skip.delete(k);
    const mid = pc.idOf(r.fileId, r.project);
    pc.hits.delete(mid);
    for (const t of r.tests || []) pc.hits.delete(pc.testKey(t, r.project));
    pc.misses.set(mid, why);
    n++;
  }
  return n;
}

module.exports = { groupPart, demote };
