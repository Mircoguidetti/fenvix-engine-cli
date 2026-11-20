# fenvix

fenvix makes CI test runs deterministic: every flaky test becomes a reproducible defect with a replay command,
nightly exploration finds hidden bugs, and a test is skipped only when its result would provably be the same
(skip with proof).

This package is the Node side: the runner shells for Vitest, Jest, Mocha, node:test, AVA, tap, uvu, Jasmine, Bun
and Deno, and the `fenvix` command (also installed as `detjs`). The Python side is the PyPI package `fenvix`.

## Install

```bash
npm install --save-dev fenvix     # Node 22, 24, 26 on Linux x64 / arm64 (glibc 2.28+) and macOS arm64
npx fenvix --version
```

The native core comes in one optional package per platform (`@fenvix/linux-x64-gnu`, `@fenvix/linux-arm64-gnu`,
`@fenvix/darwin-arm64`); npm installs only the one for your machine. Do not install with `--omit=optional`.

## Use

```bash
npx fenvix vitest run --det                    # fixed order, seeds, virtual clock, closed network
npx fenvix jest --det --det-seed=3             # reproducible shuffle
npx fenvix vitest run --det --det-cache=.fenvix-cache   # skip with proof
npx fenvix verify run1.jsonl .detjs/trace.jsonl
npx fenvix --det-help                          # every option
```

Changelog: CHANGELOG.md in the source repository.
