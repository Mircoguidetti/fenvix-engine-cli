#!/usr/bin/env python3
"""B1 acceptance criterion 2 / gate rev 3 note 10: each fault-injection test is shown red when its channel's
contributions to the key are removed. Every mutation is applied in a scratch worktree (never committed), the
channel's test file runs there (Vitest and Jest), and the result is printed and written to
harness/cache_b/data/mutations-<engine12>.json. Expected: every mutated run fails (a hit after the change), and the
unmutated scratch tree passes.

  mutations.py [--only a,b,...]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))

# channel -> (test file, [(file, old, new), ...]); every contribution of the channel to the key is removed
MUTATIONS = {
    'a': ('cache-fault-repo-file.test.js', [
        # a content read of a project file by a test process is not recorded
        ('node/src/cache/capture.js',
         "      this.add(['data', this.key(abs), this.dep(kind, abs)], global);\n    } finally {",
         "      if (w === 'root' && kind === 'f') return; // MUTATION a\n      this.add(['data', this.key(abs), this.dep(kind, abs)], global);\n    } finally {"),
    ]),
    'b': ('cache-fault-env.test.js', [
        # no environment read is recorded
        ('node/src/cache/capture.js',
         "  env(name) {\n",
         "  env(name) {\n    return; // MUTATION b\n"),
    ]),
    'c': ('cache-fault-outside.test.js', [
        # a read outside the project is not recorded
        ('node/src/cache/capture.js',
         "      this.add(['data', this.key(abs), this.dep(kind, abs)], global);\n    } finally {",
         "      if (w === 'outside') return; // MUTATION c\n      this.add(['data', this.key(abs), this.dep(kind, abs)], global);\n    } finally {"),
    ]),
    'd': ('cache-fault-node-modules.test.js', [
        # the runtime identity's installed-package part (module files under node_modules are 'skip' in the capture,
        # so the packages part is their only contribution) and the lockfiles part
        ('node/src/cache/runtime-id.js',
         "  parts.packages = tree.truncated ? `truncated-${process.pid}-${Date.now()}` : tree.digest;",
         "  parts.packages = 'MUTATION d';"),
        ('node/src/cache/runtime-id.js',
         "  parts.lockfiles = d(lists.lockfiles);",
         "  parts.lockfiles = 'MUTATION d';"),
    ]),
    'e': ('cache-fault-config.test.js', [
        # every configuration digest (configuration files, resolved runner configuration, options) and the
        # start-up reads of project files (the configuration module read by the main process)
        ('node/src/cache/proof.js',
         "      this.configDigest = digest(keys.map((k) => [k, this.configParts[k]]));",
         "      this.configDigest = 'MUTATION-e'; // MUTATION e"),
        ('node/src/cache/proof.js',
         "        this.projectConfig.set(name, digest(['project', global, this.configParts[k]]));",
         "        void global; // MUTATION e"),
        ('node/src/cache/capture.js',
         "          this.add(['data', this.key(abs), d, 'infra'], true);",
         "          void d; // MUTATION e"),
        ('node/src/cache/proof.js',
         "    const s = CAPTURE.startup;\n    return s.length ? digest(s) : '';",
         "    return ''; // MUTATION e"),
        # the configuration module is also keyed as code where the runner loads it (Jest in band: inside a file's context;
        # Jest's "code: jest.config.js (content)")
        ('node/src/cache/capture.js',
         "      this.add(['code', this.rel(f), d], this.isGlobal);",
         "      if (!(/^(jest|vite|vitest)\\.config\\./.test(path.basename(f)))) this.add(['code', this.rel(f), d], this.isGlobal); // MUTATION e"),
    ]),
    'f': ('cache-fault-clock.test.js', [
        # a clock read is not recorded (the epoch is keyed only for tests that read the clock)
        ('node/src/cache/capture.js',
         "    if (source === 'time') this.add(['clock'], false);",
         "    if (source === 'time') { /* MUTATION f */ }"),
    ]),
}


def run(cmd, cwd, timeout=3600):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return 'timeout', f'{e.stdout or ""}{e.stderr or ""}'
    return p.returncode, p.stdout + p.stderr


def tap(out):
    p = f = None
    for line in out.splitlines():
        if line.startswith('# pass '):
            p = int(line.split()[-1])
        if line.startswith('# fail '):
            f = int(line.split()[-1])
    return p, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--scratch', default='/home/runner/work/mutation-scratch')
    o = ap.parse_args()
    head = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    only = [x for x in o.only.split(',') if x] or list(MUTATIONS)
    # the native addon is copied from this checkout: the result names its digest, and the Rust sources must be the
    # commit's (the addon is built from them)
    if subprocess.run(['git', '-C', REPO, 'status', '--porcelain', '--', 'crates', 'node/src'], capture_output=True, text=True).stdout.strip():
        sys.exit('crates/ or node/src has uncommitted changes: the results would not describe HEAD')
    addon = os.path.join(REPO, 'node', 'detjs.linux-x64.node')
    results = {'engine_commit': head, 'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'addon_sha256': hashlib.sha256(open(addon, 'rb').read()).hexdigest(), 'channels': {}}
    for ch in [None, *only]:
        sc = o.scratch
        subprocess.run(['git', '-C', REPO, 'worktree', 'remove', '--force', sc], capture_output=True)
        shutil.rmtree(sc, ignore_errors=True)
        subprocess.run(['git', '-C', REPO, 'worktree', 'add', '-q', '--detach', sc, head], check=True, capture_output=True)
        os.symlink(os.path.join(REPO, 'node', 'node_modules'), os.path.join(sc, 'node', 'node_modules'))
        shutil.copy(os.path.join(REPO, 'node', 'detjs.linux-x64.node'), os.path.join(sc, 'node'))
        if ch is None:
            files = sorted(f for f in os.listdir(os.path.join(sc, 'node', 'test')) if f.startswith('cache-fault-') and f.endswith('.test.js'))
            edits = []
        else:
            files, edits = [MUTATIONS[ch][0]], MUTATIONS[ch][1]
        for rel, old, new in edits:
            p = os.path.join(sc, rel)
            text = open(p).read()
            if text.count(old) != 1:
                sys.exit(f'mutation {ch}: anchor not found exactly once in {rel}: {old!r}')
            open(p, 'w').write(text.replace(old, new))
        rc, out = run(['node', '--test', '--test-concurrency=1', *[f'test/{f}' for f in files]], os.path.join(sc, 'node'))
        p, f = tap(out)
        key = 'unmutated' if ch is None else ch
        diff = subprocess.run(['git', '-C', sc, 'diff', '--stat'], capture_output=True, text=True).stdout.strip()
        results['channels'][key] = {'tests': files, 'exit': rc, 'pass': p, 'fail': f, 'diff': diff,
                                    'expected': 'pass' if ch is None else 'fail',
                                    'as_expected': (rc == 0 and f == 0) if ch is None else (rc not in (0, 'timeout') and (f or 0) > 0)}
        print(f"{key}: exit {rc} pass {p} fail {f} -> {'as expected' if results['channels'][key]['as_expected'] else 'NOT AS EXPECTED'}", flush=True)
        subprocess.run(['git', '-C', REPO, 'worktree', 'remove', '--force', sc], capture_output=True)
    out = os.path.join(HERE, 'data', f'mutations-{head[:12]}.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as fh:
        json.dump(results, fh, indent=1)
    print(out)


if __name__ == '__main__':
    main()
