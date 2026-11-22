const loaded = require(process.argv[2] + '/node/src/loaded.js');
const root = process.argv[3];
for (let i = 0; i < 3; i++) {
  const t = process.hrtime.bigint();
  const r = loaded.depsInput(root + '/.detjs/run-0');
  console.log(`${root.split('/').pop()} run ${i}: ${(Number(process.hrtime.bigint() - t) / 1e6).toFixed(0)} ms -> ${r}`);
}
