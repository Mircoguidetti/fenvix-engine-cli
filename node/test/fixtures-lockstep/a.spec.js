const { test, expect } = require('@playwright/test');
test('lockstep fixture', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.locator('#ticks')).toContainText('tick');
  const r = await request.post('/bump');
  expect(await r.text()).toContain('bumped');
  await page.click('#go');
  await expect(page.locator('#out')).toContainText('done');
  await page.waitForTimeout(100);
  const t = await page.locator('#frames').textContent();
  expect(t.length).toBeGreaterThan(0);
});
