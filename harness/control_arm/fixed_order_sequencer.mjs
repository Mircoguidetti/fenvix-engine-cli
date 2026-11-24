// Vitest sequencer for the control arm's pair search: runs the test files in exactly the order given in the
// environment variable CA_ORDER (a JSON list of absolute file paths); files not in the list go last. No shuffle, no
// duration or failed-first ordering. Accepts Vitest's TestSpecification (moduleId) and the older [project, file]
// tuple form.
export default class FixedOrderSequencer {
  constructor(ctx) { this.ctx = ctx; }
  async shard(files) { return files; }
  async sort(files) {
    const order = JSON.parse(process.env.CA_ORDER || '[]');
    const key = (f) => (f && f.moduleId) || (Array.isArray(f) ? f[1] : f && f.filepath);
    const idx = (f) => { const i = order.indexOf(key(f)); return i < 0 ? order.length : i; };
    return [...files].sort((a, b) => idx(a) - idx(b));
  }
}
