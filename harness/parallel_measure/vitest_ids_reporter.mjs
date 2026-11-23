// Harness reporter for plain Vitest runs (no engine): per test its project, file, ancestor titles, title and state,
// so that plain ids can be written the way detjs writes them (`<file>@@<project>::<ancestors>::<title>` in a named
// project, node/src/vitest/shell.js `qualified`). Vitest's own JSON reporter does not say the project.
// Output: the path in $PM_IDS_OUT (one JSON file). Works with the reporter API of Vitest 3-5 (onTestRunEnd with test
// modules, or onFinished with files on older versions).
import fs from 'node:fs';

const STATE = { pass: 'passed', fail: 'failed', skip: 'skipped', todo: 'skipped', run: 'pending', queued: 'pending' };

function collect(files) {
  const out = [];
  const walk = (task, ancestors, file, project) => {
    if (task.type === 'test' || task.type === 'custom') {
      out.push({ file, project, ancestors, title: task.name, status: STATE[task.result?.state || task.mode] || 'skipped',
        errors: (task.result?.errors || []).map((e) => String(e.stack || e.message).slice(0, 2000)) });
      return;
    }
    for (const t of task.tasks || []) walk(t, task.type === 'suite' && task !== task.file ? [...ancestors, task.name] : ancestors, file, project);
  };
  for (const f of files) {
    const project = f.projectName || (f.file && f.file.projectName) || '';
    for (const t of f.tasks || []) walk(t, [], f.filepath, project);
  }
  return out;
}

export default class IdsReporter {
  written = false;
  write(files) {
    if (this.written || !process.env.PM_IDS_OUT) return;
    this.written = true;
    fs.writeFileSync(process.env.PM_IDS_OUT, JSON.stringify({ format: 'pm-vitest-ids', tests: collect(files) }));
  }
  onTestRunEnd(testModules) {
    this.write(testModules.map((m) => m.task));
  }
  onFinished(files) {
    this.write(files || []);
  }
}
