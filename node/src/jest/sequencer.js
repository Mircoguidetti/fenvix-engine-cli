'use strict';
// Jest test sequencer used under --det: files sorted by path relative to the
// root (fixed order) or shuffled with the seed; the executed order is written
// to <run dir>/order.json for the merge of the trace parts.
const path = require('node:path');
const native = require('../native');
const controls = require('../controls');

function baseSequencer() {
  const mod = require(require.resolve('@jest/test-sequencer', { paths: [process.cwd()] }));
  return mod.default || mod;
}

const Base = baseSequencer();

class DetSequencer extends Base {
  sort(tests) {
    const c = controls.cfg();
    const root = process.env.DETJS_ROOT || process.cwd();
    const keyed = tests.map((t) => {
      const fileId = path.relative(root, t.path).split(path.sep).join('/');
      const cfg = t.context && t.context.config;
      const project = cfg && cfg.displayName ? cfg.displayName.name : '';
      return { t, fileId, project, key: project ? `${project}|${fileId}` : fileId };
    });
    keyed.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
    let ordered = keyed;
    if (c.shuffle && c.controls.has('order')) ordered = native.shuffleIndices(keyed.length, c.seed, '').map((i) => keyed[i]);
    if (c.dir) {
      controls.writeJson(path.join(c.dir, 'order.json'),
        ordered.map((k) => ({ fileId: k.fileId, part: controls.partName(k.fileId, k.project) })));
    }
    return ordered.map((k) => k.t);
  }
}

module.exports = DetSequencer;
