// The next file of the same process: the earlier file's call stopped counting when this file opened, so its 100 s of
// sleep stay virtual (the outer test checks the run's wall time).
const { test } = require('uvu');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('100 s of virtual sleep in the next file', async () => {
  for (let i = 0; i < 20; i++) await sleep(5000);
});

test.run();
