'use strict';
// Socket faults planned by the seed (round 4, item 4). Filled in with the network layer; until then no fault
// is applied to browser requests (applyBrowser returns false).
function applyBrowser() { return false; }
module.exports = { applyBrowser };
