// One cache per process: tests in a file share it.
const store = new Map();
module.exports = { set: (k, v) => store.set(k, v), get: (k) => store.get(k), size: () => store.size };
