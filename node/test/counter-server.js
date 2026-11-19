'use strict';
// A stand-in for an external service whose answer changes on every request.
const http = require('node:http');
const https = require('node:https');

let count = 0;
const handler = (req, res) => { count++; res.end(`response #${count}`); };
const h = http.createServer(handler).listen(0, '127.0.0.1', ready);
const s = https.createServer(require('../src/replay-cert'), handler).listen(0, '127.0.0.1', ready);
let n = 0;
function ready() {
  if (++n === 2) process.stdout.write(JSON.stringify({ http: h.address().port, https: s.address().port }) + '\n');
}
