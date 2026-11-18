// The cache audit's choice, for shells without the Rust core at hand (detjs before its napi binding exposes
// detpy_core::audit). Same rule as crates/detpy-core/src/audit.rs `chosen`; tests/test_cache_audit.py checks that the
// two agree on 3,000 ids. Node standard library only.
//
//   import { chosen } from "./chosen.mjs";
//   chosen(seed, testId, share)  // true: run this reusable result fresh and compare
import { createHash } from "node:crypto";

function part(s) {
  const b = Buffer.from(s, "utf8");
  const len = Buffer.alloc(8);
  len.writeBigUInt64LE(BigInt(b.length));
  return Buffer.concat([len, b]);
}

/** The 53-bit draw of `testId` under `seed`. */
export function draw(seed, testId) {
  const h = createHash("sha256").update(Buffer.concat([part("fenvix-audit-1"), part(seed), part(testId)])).digest();
  return Number(h.readBigUInt64BE(0) >> 11n);
}

export function chosen(seed, testId, share) {
  if (!(share > 0)) return false;
  if (share >= 1) return true;
  return draw(seed, testId) < share * 2 ** 53;
}

if (process.argv[2] === "--check") {
  // stdin: JSON [[seed, id, share], ...] -> stdout: JSON [bool, ...]
  let raw = "";
  process.stdin.on("data", (c) => (raw += c));
  process.stdin.on("end", () => process.stdout.write(JSON.stringify(JSON.parse(raw).map(([s, t, x]) => chosen(s, t, x)))));
}
