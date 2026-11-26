'use strict';
// P2 C4 data capture (harness only; not part of the engine): loaded with NODE_OPTIONS=--require, it copies a run's
// lane markers (<root>/.detjs/run-<pid>/lanes) to $P2_KEEP_LANES/<pid>-<n>/ right before the engine removes the run
// directory at the end of the run (session.js). Nothing else is changed; without P2_KEEP_LANES it does nothing.
const fs = require('node:fs');
const path = require('node:path');
const out = process.env.P2_KEEP_LANES;
if (out) {
  const real = fs.rmSync;
  let n = 0;
  fs.rmSync = function rmSync(p, ...rest) {
    try {
      const s = String(p);
      if (/[\\/]\.detjs[\\/]run-\d+$/.test(s) && fs.existsSync(path.join(s, 'lanes'))) {
        const dest = path.join(out, `${process.pid}-${n++}`);
        fs.cpSync(path.join(s, 'lanes'), dest, { recursive: true });
        if (fs.existsSync(path.join(s, 'plan.json'))) fs.copyFileSync(path.join(s, 'plan.json'), path.join(dest, 'plan.json'));
      }
    } catch { /* capture is best effort */ }
    return real.call(this, p, ...rest);
  };
}
