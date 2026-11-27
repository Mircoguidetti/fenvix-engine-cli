import { test, expect } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// A cross-lane hazard on purpose (proof to the customer, B3): a.test.js and the other file both write the same temp
// path. Neither reads or asserts the other file's data, so no test fails in either order; with 2 lanes each file gets
// its own lane, the engine sees the shared path, and the file pair runs again in one lane (proof.rerun_one_lane > 0).
const shared = path.join(os.tmpdir(), 'fenvix-hazard-fixture.txt');

test('a writes the shared file', () => { fs.writeFileSync(shared, 'a1'); expect(1 + 1).toBe(2); });
test('a writes it again', () => { fs.writeFileSync(shared, 'a2'); expect('a'.length).toBe(1); });
