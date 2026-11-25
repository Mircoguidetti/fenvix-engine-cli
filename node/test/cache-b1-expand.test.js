'use strict';
// Cache measurement B, B1 review (adversarial finding 6): the shared-cache push expands a store entry's data and env
// exactly as the Rust store loads them (Data deserialize, resolve_grouped, Store::load), never more permissively.
//
// protects=  a pushed entry document never lists fewer dependencies than the local store entry: an entry whose data
//            or env is missing, not a list, a mix of pairs and addresses, holds a pair that is not two strings, or
//            names a chunk or group the store file lacks is not pushed (expandEntry returns null), as Rust rejects
//            or drops it; a well-formed entry expands to the same pairs in the same order.
// fails_when= expandEntry returns an entry (for example with data: []) for any of those malformed inputs, or a
//            well-formed grouped / chunk / pair-listed entry does not expand to its pairs.
// no_claim=  the service's handling of documents pushed by earlier engine builds, or Python's push.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { expandEntry } = require('../src/cache/remote');

const store = { chunks: { aa01: [['/p/a', 'f:1'], ['/p/b', 'f:2']], bb02: [['HOME', 'd:3']] }, groups: { g01: ['aa01'], g02: ['bb02'] } };

test('a well-formed entry expands to its pairs (groups, chunk addresses, pairs)', () => {
  assert.deepEqual(expandEntry({ data: ['g01'], env: ['g02'], config: 'c' }, store),
    { data: [['/p/a', 'f:1'], ['/p/b', 'f:2']], env: [['HOME', 'd:3']], config: 'c' });
  assert.deepEqual(expandEntry({ data: ['aa01'], env: [] }, store).data, [['/p/a', 'f:1'], ['/p/b', 'f:2']]);
  assert.deepEqual(expandEntry({ data: [['/p/c', 'f:9']], env: [['X', '-']] }, store),
    { data: [['/p/c', 'f:9']], env: [['X', '-']] });
});

test('a torn entry (an address the store file lacks) is not pushed', () => {
  assert.equal(expandEntry({ data: ['g99'], env: [] }, store), null);
  assert.equal(expandEntry({ data: ['cc03'], env: [] }, store), null);
  assert.equal(expandEntry({ data: ['g01'], env: [] }, { chunks: {}, groups: { g01: ['aa01'] } }), null);
});

test('a mixed list of pairs and addresses is not pushed', () => {
  assert.equal(expandEntry({ data: [['/p/a', 'f:1'], 'aa01'], env: [] }, store), null);
});

test('a missing or non-list data or env is not pushed (Rust: no serde default on Entry.data / Entry.env)', () => {
  assert.equal(expandEntry({ env: [] }, store), null);
  assert.equal(expandEntry({ data: [] }, store), null);
  assert.equal(expandEntry({ data: null, env: [] }, store), null);
  assert.equal(expandEntry({ data: 'g01', env: [] }, store), null);
  assert.equal(expandEntry({ data: [], env: {} }, store), null);
});

test('a pair that is not two strings is not pushed (Rust: Item::Pair(Str, Str))', () => {
  assert.equal(expandEntry({ data: [['/p/a']], env: [] }, store), null);
  assert.equal(expandEntry({ data: [['/p/a', 'f:1', 'x']], env: [] }, store), null);
  assert.equal(expandEntry({ data: [['/p/a', 1]], env: [] }, store), null);
  assert.equal(expandEntry({ data: ['bad1'], env: [] }, { chunks: { bad1: [['/p/a', null]] }, groups: {} }), null);
});
