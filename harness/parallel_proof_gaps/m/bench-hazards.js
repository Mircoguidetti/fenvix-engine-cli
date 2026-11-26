const [eng, dump] = process.argv.slice(2);
const { hazards } = require(eng + '/node/src/parallel.js');
const d = JSON.parse(require('fs').readFileSync(dump, 'utf8'));
const markers = new Map(d.markers); const laneOf = new Map(d.laneOf);
let keys = 0; for (const [, m] of markers) for (const v of Object.values(m.footprint || {})) keys += Array.isArray(v) ? v.length : 0;
const ts = []; let h;
for (let i = 0; i < 25; i++) { const t0 = process.hrtime.bigint(); h = hazards(markers, laneOf); ts.push(Number(process.hrtime.bigint() - t0) / 1e6); }
ts.sort((a, b) => a - b);
console.log(JSON.stringify({ engine: eng, dump: require('path').basename(dump), files: markers.size, footprint_keys: keys, hazards: h.length, median_ms: ts[12].toFixed(2), min_ms: ts[0].toFixed(2), max_ms: ts[24].toFixed(2) }));
