'use strict';
// A throwaway self-signed certificate for the local TLS replay server (audit G-2165): generated in memory once per
// process (EC P-256 key, ECDSA-SHA256 signature), never written to disk and never shipped. Only replayed TLS sockets
// skip certificate verification (src/network.js); no other connection trusts this certificate.
const nodeCrypto = require('node:crypto');

function len(n) {
  if (n < 0x80) return Buffer.from([n]);
  const bytes = [];
  while (n > 0) { bytes.unshift(n & 0xff); n >>= 8; }
  return Buffer.from([0x80 | bytes.length, ...bytes]);
}
const tlv = (tag, body) => Buffer.concat([Buffer.from([tag]), len(body.length), body]);
const seq = (...items) => tlv(0x30, Buffer.concat(items));
const set = (...items) => tlv(0x31, Buffer.concat(items));
function int(buf) {
  let b = buf;
  while (b.length > 1 && b[0] === 0 && b[1] < 0x80) b = b.subarray(1);
  if (b[0] & 0x80) b = Buffer.concat([Buffer.from([0]), b]);
  return tlv(0x02, b);
}
function oid(text) {
  const p = text.split('.').map(Number);
  const out = [40 * p[0] + p[1]];
  for (const v of p.slice(2)) {
    const enc = [v & 0x7f];
    let x = v >>> 7;
    while (x > 0) { enc.unshift((x & 0x7f) | 0x80); x >>>= 7; }
    out.push(...enc);
  }
  return tlv(0x06, Buffer.from(out));
}
const utf8 = (s) => tlv(0x0c, Buffer.from(s, 'utf8'));
const utcTime = (s) => tlv(0x17, Buffer.from(s, 'latin1'));

const ECDSA_SHA256 = seq(oid('1.2.840.10045.4.3.2'));

/** UTCTime (YYMMDDHHMMSSZ, years 1950-2049) of a Date. */
function utcTimeOf(d) {
  const t = new Date(d);
  if (Number.isNaN(t.getTime())) throw new Error(`selfcert: not a date: ${d}`);
  const y = t.getUTCFullYear();
  if (y < 1950 || y > 2049) throw new Error(`selfcert: ${t.toISOString()} is outside 1950-2049 (UTCTime)`);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(y % 100)}${p(t.getUTCMonth() + 1)}${p(t.getUTCDate())}${p(t.getUTCHours())}${p(t.getUTCMinutes())}${p(t.getUTCSeconds())}Z`;
}

/**
 * { key, cert } PEM strings of a new self-signed certificate for `commonName`. `validity` (optional):
 * { notBefore, notAfter } as Dates (or anything `new Date` takes); default 2000-01-01 to 2049-12-31.
 */
function generate(commonName = 'detjs network replay (throwaway)', validity = null) {
  const from = validity && validity.notBefore !== undefined ? utcTimeOf(validity.notBefore) : '000101000000Z';
  const to = validity && validity.notAfter !== undefined ? utcTimeOf(validity.notAfter) : '491231235959Z';
  const { privateKey, publicKey } = nodeCrypto.generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  const name = seq(set(seq(oid('2.5.4.3'), utf8(commonName))));
  const spki = publicKey.export({ type: 'spki', format: 'der' });
  // serial: from the public key (no draw from the generators the test may be using)
  const serial = nodeCrypto.createHash('sha256').update(spki).digest().subarray(0, 16);
  serial[0] &= 0x7f;
  const tbs = seq(
    tlv(0xa0, int(Buffer.from([2]))), // v3
    int(serial),
    ECDSA_SHA256,
    name,
    seq(utcTime(from), utcTime(to)),
    name,
    spki,
  );
  const sig = nodeCrypto.sign('sha256', tbs, privateKey);
  const der = seq(tbs, ECDSA_SHA256, tlv(0x03, Buffer.concat([Buffer.from([0]), sig])));
  const b64 = der.toString('base64').replace(/(.{64})/g, '$1\n').replace(/\n$/, '');
  return {
    key: privateKey.export({ type: 'pkcs8', format: 'pem' }),
    cert: `-----BEGIN CERTIFICATE-----\n${b64}\n-----END CERTIFICATE-----\n`,
  };
}

let CACHED = null;
/** The certificate of this process' replay server (generated on first use, outside the trace and the cache capture). */
function replayCert() {
  if (CACHED) return CACHED;
  let cap = null;
  try { cap = require('./cache/capture').CAPTURE; } catch { /* no cache */ }
  const { STATE } = require('./state');
  if (cap) cap.busy++;
  try {
    CACHED = STATE.quiet(() => generate());
  } finally {
    if (cap) cap.busy--;
  }
  return CACHED;
}

module.exports = { generate, replayCert };
