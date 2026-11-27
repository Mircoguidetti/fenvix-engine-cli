// Guards of P2 (the outer test times this file): after a test started a child process, only its short timers run at
// real pace. (1) a long virtual sleep in that test stays virtual; (2) the next test's short timers stay virtual.
import { test, expect } from 'vitest';
import { spawnSync } from 'node:child_process';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('a test that started a child process: a 20 s virtual sleep stays virtual', async () => {
  expect(spawnSync(process.execPath, ['-e', '0']).status).toBe(0);
  await sleep(20000);
}, 30000);

test('the next test polls 100 x 100 ms virtually', async () => {
  for (let i = 0; i < 100; i++) await sleep(100);
}, 30000);
