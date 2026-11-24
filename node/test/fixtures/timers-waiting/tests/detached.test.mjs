// Shape of codex-multi-auth b9886168 test/codex-bin-wrapper.test.ts:1744 ("forwards an explicit loopback upstream"):
// a spawnSync'd process starts a detached helper and exits; the test polls (setTimeout 20 ms) for a file the helper
// writes 300 ms later. The test process holds no handle to the helper.
import { test, expect } from 'vitest';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('polls for a file a detached helper writes', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'det-detached-'));
  const marker = path.join(dir, 'marker.txt');
  const helper = `setTimeout(() => require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'close'), 300);`;
  const launcher = `require('node:child_process').spawn(process.execPath, ['-e', ${JSON.stringify(helper)}], { detached: true, stdio: 'ignore' }).unref();`;
  expect(spawnSync(process.execPath, ['-e', launcher]).status).toBe(0);
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    if (fs.existsSync(marker)) break;
    await sleep(20);
  }
  expect(fs.readFileSync(marker, 'utf8')).toBe('close');
});
