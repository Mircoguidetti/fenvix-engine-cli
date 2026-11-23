// Jest test sequencer for the control arm's pair search: runs the test files in exactly the order given in the
// environment variable CA_ORDER (a JSON list of absolute file paths); files not in the list go last. It extends the
// repository's own @jest/test-sequencer (resolved from the working directory) so that caching/sharding hooks keep
// their default behaviour; only the order changes (no duration or failed-first ordering).
let Base;
try {
  Base = require(require.resolve('@jest/test-sequencer', { paths: [process.cwd()] })).default;
} catch (e) {
  Base = class {
    cacheResults() {}
    shard(tests) { return tests; }
    allFailedTests(tests) { return tests; }
  };
}

class FixedOrderSequencer extends Base {
  sort(tests) {
    const order = JSON.parse(process.env.CA_ORDER || '[]');
    const idx = (t) => { const i = order.indexOf(t.path); return i < 0 ? order.length : i; };
    return [...tests].sort((a, b) => idx(a) - idx(b));
  }
}

module.exports = FixedOrderSequencer;
