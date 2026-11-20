'use strict';
// One encoding for the strings detjs hands to the Rust core (test ids, capture items, receipts' node ids).
//
// A JavaScript string may hold an unpaired surrogate (a test named with '\ud800', found on yaml's test suite): napi
// turns it into U+FFFD, so two different ids would collapse into one, and serde_json refuses the JSON escape of it
// (`lone leading surrogate`), so the cache recorded nothing for the whole session. `wire` maps every string to a
// well-formed one, injectively: an unpaired surrogate becomes U+FFFF followed by its four hex digits, a U+FFFF of the
// original is doubled; every other string (all well-formed ones without U+FFFF) is unchanged. Applied once, where a
// raw string crosses to Rust (src/state.js beginTest, src/cache/proof.js recordAll).

function wire(s) {
  if (typeof s !== 'string') return s;
  if (s.isWellFormed() && !s.includes('￿')) return s;
  let out = '';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c === 0xFFFF) { out += '￿￿'; continue; }
    if (c >= 0xD800 && c <= 0xDBFF && i + 1 < s.length) {
      const d = s.charCodeAt(i + 1);
      if (d >= 0xDC00 && d <= 0xDFFF) { out += s[i] + s[i + 1]; i += 1; continue; }
    }
    if (c >= 0xD800 && c <= 0xDFFF) { out += `￿${c.toString(16)}`; continue; }
    out += s[i];
  }
  return out;
}

/** JSON of `v` with every string (keys too) wired. */
function wireJson(v) {
  return JSON.stringify(v, function replacer(k, x) {
    if (typeof x === 'string') return wire(x);
    if (x && typeof x === 'object' && !Array.isArray(x)) {
      let bad = false;
      for (const key of Object.keys(x)) if (wire(key) !== key) { bad = true; break; }
      if (bad) { const o = {}; for (const key of Object.keys(x)) o[wire(key)] = x[key]; return o; }
    }
    return x;
  });
}

module.exports = { wire, wireJson };
