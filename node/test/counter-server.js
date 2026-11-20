'use strict';
// A stand-in for an external service whose answer changes on every request: HTTP, HTTPS and HTTP/2 over TLS (ALPN
// h2, HTTP/1.1 also accepted). The certificate is generated per start (src/selfcert.js): no key is shipped.
const http = require('node:http');
const https = require('node:https');
const http2 = require('node:http2');

let count = 0;
const handler = (req, res) => { count++; res.end(`response #${count}`); };
const cert = require('../src/selfcert').generate('counter.detjs.test');
const h = http.createServer(handler).listen(0, '127.0.0.1', ready);
const s = https.createServer(cert, handler).listen(0, '127.0.0.1', ready);
const h2 = http2.createSecureServer({ ...cert, allowHTTP1: true }, handler).listen(0, '127.0.0.1', ready);
let n = 0;
function ready() {
  if (++n === 3) process.stdout.write(JSON.stringify({ http: h.address().port, https: s.address().port, h2: h2.address().port }) + '\n');
}
