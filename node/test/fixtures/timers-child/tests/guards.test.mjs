// Guards of P2 (the outer test times this file): after a test started a child process, only its short timers run at
// real pace. (1) a long virtual sleep in that test stays virtual; (2) the next test's short timers stay virtual;
// (3) and (4) the asynchronous spawn and the Worker paths pace like spawnSync (test (b) uses spawnSync).
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

test('async spawn: a poll loop for a file a detached helper writes passes (the asynchronous child path paces too)', async () => {
  const { spawn } = await import('node:child_process');
  const fs = await import('node:fs');
  const os = await import('node:os');
  const path = await import('node:path');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'det-child-async-'));
  const marker = path.join(dir, 'marker.txt');
  const helper = `setTimeout(() => require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'close'), 300);`;
  const launcher = `require('node:child_process').spawn(process.execPath, ['-e', ${JSON.stringify(helper)}], { detached: true, stdio: 'ignore' }).unref();`;
  await new Promise((r) => spawn(process.execPath, ['-e', launcher], { stdio: 'ignore' }).on('exit', r));
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    if (fs.existsSync(marker)) break;
    await sleep(20);
  }
  expect(fs.readFileSync(marker, 'utf8')).toBe('close');
});

test('worker: a poll loop for a file the worker writes later passes (the Worker path paces too)', async () => {
  const { Worker } = await import('node:worker_threads');
  const fs = await import('node:fs');
  const os = await import('node:os');
  const path = await import('node:path');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'det-child-worker-'));
  const marker = path.join(dir, 'marker.txt');
  const w = new Worker(`const t0 = Date.now(); while (Date.now() - t0 < 300) {} require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'close');`, { eval: true });
  w.unref();
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    if (fs.existsSync(marker)) break;
    await sleep(20);
  }
  expect(fs.readFileSync(marker, 'utf8')).toBe('close');
});
