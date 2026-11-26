// A test that starts a tool of the project by its bare name, as ironcurtain's MCP tests start
// `mcp-server-filesystem`: under npx / npm scripts node_modules/.bin is on PATH.
import { test, expect } from 'vitest';
import { execFileSync } from 'node:child_process';

test('a project bin is found by its bare name', () => {
  expect(execFileSync('detjs-fixture-tool', { encoding: 'utf8' }).trim()).toBe('tool ran');
});
