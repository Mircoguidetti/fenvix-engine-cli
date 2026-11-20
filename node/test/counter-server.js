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
// WebSocket echo (one small masked client frame per message): "echo #<count> <payload>"
h.on('upgrade', (req, sock) => {
  const acc = require('node:crypto').createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  sock.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${acc}\r\n\r\n`);
  sock.on('data', (d) => {
    if ((d[0] & 0x0f) === 8) { sock.end(Buffer.from([0x88, 0])); return; }
    const len = d[1] & 0x7f;
    const mask = d.subarray(2, 6);
    const text = Buffer.from(d.subarray(6, 6 + len)).map((b, i) => b ^ mask[i % 4]).toString();
    count++;
    const out = Buffer.from(`echo #${count} ${text}`);
    sock.write(Buffer.concat([Buffer.from([0x81, out.length]), out]));
  });
  sock.on('error', () => {});
});
const s = https.createServer(cert, handler).listen(0, '127.0.0.1', ready);
const h2 = http2.createSecureServer({ ...cert, allowHTTP1: true }, handler).listen(0, '127.0.0.1', ready);
let n = 0;
function ready() {
  if (++n === 3) process.stdout.write(JSON.stringify({ http: h.address().port, https: s.address().port, h2: h2.address().port }) + '\n');
}
