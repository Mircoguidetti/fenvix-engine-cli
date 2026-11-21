const { test } = require('@playwright/test');
test('page time vs engine time', async ({ page }) => {
  await page.goto(process.env.PG || '/');
  for (let i = 0; i < 4; i++) {
    await page.waitForTimeout(500);
    const p = await page.evaluate(() => [Date.now(), performance.now()]);
    console.log('engine', Date.now() - Date.parse('2026-01-01T00:00:00Z'), 'page', p[0] - Date.parse('2026-01-01T00:00:00Z'), 'perf', Math.round(p[1]));
  }
});
