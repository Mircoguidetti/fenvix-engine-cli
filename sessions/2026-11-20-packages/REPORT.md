PARTIAL — packages, per-platform builds, the version guard and the CI matrix are done and tested in CI; not done: nothing is published (TestPyPI upload needs the trusted publisher the founder must configure first; npm is `--dry-run` as asked), and the gaps listed as OPEN in section 3.

# Rows F-10 (install), F-09 (platforms), PY-01 (Python versions), JS-01 (Node versions)

Session 2026-11-20, branch `claude/packages` (from `claude/release-1` @ 7d5a552), PR #2 into `claude/release-1`.
Numbers are MEASURED (with run id or command), ESTIMATED (with derivation), DECLARED (with source) or UNKNOWN.

## 1. Per row: what is now true, what is not, evidence

### F-10 install — PARTIAL

True now:
- **PyPI package `fenvix`** (`pyproject.toml`): wheels `cp312-abi3` for `manylinux_2_28_x86_64`,
  `manylinux_2_28_aarch64`, `macosx_11_0_arm64`, plus an sdist; `Requires-Python >=3.12`; `pytest>=8.1`; extra
  `fenvix[xdist]` (pytest-xdist>=3.7); LICENSE shipped (`dist-info/licenses/LICENSE`); project URLs, classifiers,
  its own README (`python/README.md`). Provides the pytest plugin (entry point `detpy = detpy.plugin`), the runners
  (`python -m detpy ...`), and the console scripts `fenvix` (`detpy/fenvix_cli.py`: `--version`, `version`,
  `doctor`, `python`, `python-runner`, `node`, `verify`, `detect`, `go`, `jvm`) and `detpy`.
  The import package stays `detpy` (the go-live scope names `python -m detpy`); the distribution is never `detpy`.
- **npm package `fenvix`** (built by `release/npm/pack.py` from `node/`): bins `fenvix` and `detjs`, `main`
  `src/index.js` (exists now), `files`, `engines.node >=22`, `os`, `cpu`, and one optionalDependency per platform:
  **`@fenvix/linux-x64-gnu`, `@fenvix/linux-arm64-gnu`, `@fenvix/darwin-arm64`** (each with `os`/`cpu`/`libc`,
  holding `fenvix.<triple>.node`). The loader (`node/src/native.js`, `node/src/platform.js`) finds the addon in
  that package; on musl, glibc < 2.28, Windows or macOS Intel it stops with one sentence naming the supported
  platforms. `fenvix --version` / `-v`, `--help` exit 0; an unknown runner is named; a user error of the shell is
  printed without a JavaScript stack.
- **Versioning**: one version (`Cargo.toml [workspace.package]`) for every crate, the wheel (maturin dynamic
  version), `detpy/_version.py`, `node/package.json` and the npm packages; `release/version.py` checks and sets it;
  CI fails when they differ. `CHANGELOG.md` (Keep a Changelog). Git tag `v<version>`.
- **Release workflow** `.github/workflows/release.yml`: tag `vX.Y.Z` (refused if it differs from
  `release/version.py` or CHANGELOG has no section) → builds and tests everything through `packages.yml`
  (`workflow_call`) → TestPyPI upload with `pypa/gh-action-pypi-publish` through **trusted publishing (OIDC,
  `id-token: write`, environment `testpypi`)** → npm publish of the platform packages then `fenvix`, `--dry-run`
  unless the repository variable `FENVIX_PUBLISH_NPM=true` (then `--provenance`, OIDC) → real PyPI only when
  `FENVIX_PUBLISH_PYPI=true` → GitHub Release with the changelog section and all artifacts.
  `workflow_dispatch` with a pre-release version (e.g. `0.1.0-rc.3`) uploads that pre-release to TestPyPI. No token
  or password exists in the repository or in its secrets.
- **Names** (MEASURED 2026-11-20 with curl against the registries): PyPI `fenvix` free (`pypi.org/pypi/fenvix/json`
  → 404), TestPyPI `fenvix` free (404), npm `fenvix` free (`registry.npmjs.org/fenvix` → 404), npm scope
  **`@fenvix` free** (`registry.npmjs.org/-/user/fenvix/package` → 404 "Scope not found"; control
  `sindresorhus` → 200; `registry.npmjs.org/-/org/fenvix/package` → 404, control `babel` → 200). PyPI `detpy` is
  taken by an unrelated project (→ 200, G-0170): never used.
- **Install test in CI** (`packages.yml`, job `install`, 3 platforms × 3 (Python, Node) pairs): no checkout;
  only the built wheels, the npm tarballs and `install_test.py` are downloaded. It installs `fenvix` from a local
  PEP 503 index (with `data-requires-python`, as PyPI serves it), checks `fenvix --version` and `fenvix doctor`,
  runs `pytest --det` twice on a small real Python project (itsdangerous 2.2.0; traces verified identical by
  `fenvix verify`) and `--det-cache` twice (reuse > 0, no outcome differs), installs the npm tarballs into a small
  real Vitest project (ufo v1.6.1, Vitest 3), runs `npx fenvix --version`, `npx fenvix vitest run --det` twice
  (traces verified) and `--det-cache` twice (reuse > 0); on CPython 3.11 pip refuses with
  "Requires-Python >=3.12" and a copy forced into 3.11 refuses `pytest --det` and `python -m detpy` (exit 4).

Not true / missing:
- **Nothing is published.** TestPyPI upload was not run: it needs the pending trusted publisher on test.pypi.org,
  which only the founder can create (section 4). `npm publish --dry-run` runs in CI for every package (job
  `packages`). The real registries were not touched, as instructed.
- The names are free but **not reserved** until the founder registers them (G-0522, G-1439).
- G-0217 (the hosted runner's `runner/bootstrap.sh` installs no Node engine), G-0733 (upgrade path of stores),
  G-0734 / G-1440 (configuration file), G-1441 / G-1442 (Vitest plugin / Jest preset instead of a wrapper),
  G-2177 / G-2194 (no `.gitignore` inside `.detjs/` / `.detpy/`), G-1543 (pytest 10 deprecation in
  `--det-isolate`), G-1544 (strace absence not named) are open (section 3).

### F-09 platforms — PARTIAL

True now:
- Built and tested in CI on **Linux x86_64 (ubuntu-latest), Linux arm64 (ubuntu-24.04-arm), macOS arm64
  (macos-15)**: Rust core tests, wheel, napi addon, platform-floor check, full Python suites (3.12/3.13/3.14) and
  full detjs suites (Node 22/24/26) on arm64 and macOS (`packages.yml` jobs `python`, `node`); Linux x86_64 full
  suites stay in `release-1.yml`.
- **glibc floor 2.28** (manylinux_2_28): wheels built with `maturin --zig --compatibility manylinux_2_28`, the addon
  with `cargo zigbuild --target <arch>-unknown-linux-gnu.2.28`; `release/check_floor.py` fails CI if any native file
  needs a glibc symbol newer than 2.28 or a macOS deployment target newer than 11.0. MEASURED locally:
  `_core.abi3.so` and `fenvix.linux-x64-gnu.node` max `GLIBC_2.28`; the previous build method
  (`cargo build`, ubuntu 24.04) gives `GLIBC_2.34` and is flagged BAD by the same check.
- **Hard-coded Linux x86_64 removed**: `release/install-image.sh` picks the addon of the machine
  (`detjs.<platform>-<arch>.node` or `fenvix.<triple>.node`) and installs Go/JVM parts only when present (G-0478,
  G-0496); `jvm/build.sh` takes `.so` or `.dylib` (G-0497); `node/src/native.js` resolves the platform package;
  a test (`test_no_hard_coded_linux_x64_in_install_paths`) keeps it so.
- **macOS observation family** (G-0155, G-0156, G-0157, G-0158; the rule "observe, key, or refuse"):
  new `crates/detpy-core/src/host.rs` gives, per OS, the loaded images (`/proc/self/maps` on Linux, dyld on macOS),
  the CPU features (sysctl `machdep.cpu.brand_string` + `hw.optional.*` on macOS) and whether child processes are
  alive (`/proc/self/task/*/children` on Linux, `proc_listchildpids` on macOS); `None` where unknown. Used by:
  the Python per-test native-library scan (`capture.rs scan_maps_impl`) and the distribution scan (`distid.py`),
  which used to read an empty string on macOS; the virtual clock's child check (unknown now counts as alive);
  the Node runtime identity (`runtime-id.js`: dyld images, macOS CPU features, OS release+build); the Python
  runtime identity on macOS keys the OS release, the kernel build and the CPU features in the slot where Linux keys
  the glibc version (`_proof.runtime_identity`). Internet sockets opened by C code on macOS are seen through
  `/dev/fd` + `getsockname` (`sysmon.rs`), where the Linux path reads `/proc/self/net`.

Not true / missing:
- G-1501 (no child-process following on macOS: such tests are not reused there — conservative, documented),
  G-1500 (ASLR cannot be switched off on macOS), G-1502 (`--det-isolate` falls back on macOS), G-1503 (a Linux bundle
  replayed on macOS: UNKNOWN), G-0723 (ELF/glibc identity suites skip on macOS), G-1492 / G-1575 (ASLR silently on
  under Docker's seccomp), G-2195 (WSL2: UNKNOWN, never run) are open.
- The task named `macos-14`; on this account every `macos-14` job is cancelled in the queue the second it is
  created (MEASURED: run 44719938170, job 136232796724, created and completed 10:31:21–22, no runner; the audit saw
  the same in runs 44700422692 and 44703540913). The jobs run on `macos-15` (Apple silicon, the label the audit's
  working macOS probe used).

### PY-01 Python versions — see section 2 for the CI result

True now:
- CPython 3.12, 3.13, 3.14 are the supported set: wheel ABI `abi3-py312` (`crates/detpy-py/Cargo.toml`),
  `Requires-Python >=3.12`, classifiers 3.12–3.14; full suites on 3.12/3.13/3.14 on Linux x86_64 (`release-1.yml`,
  now with the optional runners installed so that the Django, nose2, ward, zope and pytest-django suites run instead
  of being skipped: G-0010; MEASURED locally: those 6 files 143 passed, 1 skipped in 165 s on 3.13), Linux arm64
  and macOS arm64 (`packages.yml`), and the install test on each.
- **Below 3.12, refused, never a crash** (G-0547, G-0556 and their family): at install, pip on 3.11 answers
  "Ignored the following versions that require a different python version: 0.1.0 Requires-Python >=3.12"
  (MEASURED locally against a PEP 503 index, and in CI job `install`); at start, `detpy/_support.py` decides before
  the native core is imported: `pytest --det` (also via `PYTEST_ADDOPTS`, `--det-isolate`, `--det-cache`, `-n`),
  `python -m detpy <runner>`, the `detpy` and `fenvix` commands print
  "fenvix: fenvix needs CPython 3.12 or newer; this is Python 3.11 (...). Supported: CPython 3.12, 3.13, 3.14 on
  Linux x86_64/arm64 (glibc 2.28+) and macOS arm64." and exit 4; a plain `pytest` without `--det` runs unchanged.
  MEASURED locally on a real CPython 3.11.x venv with the wheel's files copied in (rc 4, no traceback) and by
  `tests/test_packaging.py`. Free-threaded builds and PyPy get the same treatment.

### JS-01 Node versions — see section 2 for the CI result

True now: `engines.node >=22`; detjs suites on Node 22/24/26 on Linux x86_64 (`release-1.yml`), Linux arm64 and
macOS arm64 (`packages.yml`); install test with Node 22, 24, 26 on each platform. Node ≤ 20 is out of scope:
not tested, `engines` warns.

## 2. CI evidence

(filled in below from the runs of the final head)

## 3. Every audit gap of these rows

Legend: FIXED (regression test) · REFUSED (now an explicit message; the platform/version is out of scope) ·
OUT (out of the go-live scope, not worked on) · OPEN (in scope, not done) · FOUNDER (needs an account action) ·
OTHER ROW (belongs to another row's area; not changed here).

| gap | status | evidence / regression test |
|---|---|---|
| G-0010 optional runners not installed in the gate | FIXED | release-1.yml installs django, pytest-django, nose2, ward, zope.testrunner, hypothesis, numpy, time-machine, pytest-benchmark, freezegun, pytest-asyncio, pytest-mock, pytest-cov; the suites run instead of skipping |
| G-0155 macOS: dlopen'ed libraries not inputs | FIXED | `host::loaded_images` (dyld) in `capture.rs` and `distid.py`; `test_packaging.py::test_host_loaded_images_and_children_observed` (runs on macOS in `python` job), `host::tests::loaded_images_sees_this_process_libc_on_supported_os` |
| G-0156 macOS runtime identity without native libraries | FIXED | macOS keys OS release + kernel build + CPU features (`_proof.py`); loaded images per test (G-0155) |
| G-0157 Node identity off Linux: no libraries, ISA `unknown` | FIXED | `runtime-id.js` uses `loadedImages()` and `cpuFeatures()`; node `cache.test.js` 45/45 MEASURED locally; macOS suites in CI |
| G-0158 macOS sockets / children via /proc | FIXED | `/dev/fd`+getsockname (`sysmon.rs`), `proc_listchildpids` (`host.rs`, clock); `test_children_alive_seen_by_virtual_clock`, `host::tests::children_alive_is_known_on_supported_os` |
| G-0170 foreign PyPI `detpy` replaces the engine | FIXED | distribution `fenvix`; `fenvix doctor` names any other distribution writing `detpy/`; `test_foreign_detpy_distribution_reported`, `test_install_metadata_refuses_old_python_and_names_fenvix` |
| G-0171 `--det-isolate` broken on pytest 7.0–8.0 | FIXED | `pytest>=8.1`; `test_pytest_floor_excludes_versions_that_break_det` |
| G-0205, G-0242, G-0561 default branch is a Block 2 tip | FOUNDER | section 4 (repository settings not changed, as instructed) |
| G-0217 runner bootstrap installs no Node engine | OPEN | hosted runner image path (`runner/bootstrap.sh`) not changed |
| G-0240 detjs addon only linux-x64 | FIXED | three `@fenvix/<platform>` packages built in `packages.yml` `build`; `test_no_hard_coded_linux_x64_in_install_paths` |
| G-0241, G-0251, G-0417, G-0523, G-0249, G-0254 no release channel / not installable | FIXED (built, tested) + FOUNDER (publish) | `packages.yml`, `release.yml`; install test in CI |
| G-0243 public docs say "steps added at launch" | OTHER ROW | another repository (docs site); `docs/INSTALL.md` written here |
| G-0247, G-0439, G-0440, G-0468, G-0736 detjs private / no npm package / no npx | FIXED (dry-run) + FOUNDER | npm `fenvix` built and `npm publish --dry-run` in CI; `npx fenvix` in install test |
| G-0248, G-0521 `pip install detpy` gets the foreign project | FIXED | package is `fenvix`; README/INSTALL warn; doctor check |
| G-0250, G-0524, G-1488 wheel tagged `linux_x86_64` | FIXED | manylinux_2_28 tags; `twine check --strict` in CI; release-1's internal gate wheel keeps `--compatibility linux` (never published) |
| G-0255, G-0416, G-0492, G-1504 macOS never built or tested | FIXED | `packages.yml` on macos-15: build, full Python and Node suites, install test |
| G-0413, G-0738 plugin only in the image's Python / not in tox envs | FIXED | `pip install fenvix` in any environment; `docs/INSTALL.md` "In tox, nox, ..." |
| G-0414, G-0552, G-1133 cache needs 3.12 | REFUSED | 3.9–3.11 are not supported: refused at install and start |
| G-0415, G-0472, G-0526 Linux arm64 not a gate / no wheel | FIXED | aarch64 wheel and addon built; full suites and install test on ubuntu-24.04-arm |
| G-0441, G-0442, G-0443, G-0473, G-0477 no per-platform addon packages, arm64, macOS | FIXED | `@fenvix/linux-x64-gnu`, `linux-arm64-gnu`, `darwin-arm64` |
| G-0444, G-0528, G-0256 Windows | OUT / REFUSED | loader message "win32 is not supported" |
| G-0445, G-0525, G-0482..G-0487 musl / Alpine | OUT / REFUSED | Node loader: "Linux without glibc (musl, e.g. Alpine) is not supported"; no musllinux wheel (pip finds none) |
| G-0446, G-0479, G-0481, G-0488, G-0489 glibc ≥ 2.34 required | FIXED | floor 2.28; `release/check_floor.py` in CI on every native file; glibc < 2.28 gets a Node message |
| G-0480, G-0490, G-0491 fenvix-skip / fenvix-go / JNI glibc | OUT | JVM and Go |
| G-0474, G-0475, G-0476, G-0493, G-0494, G-0495 Go/JVM on arm64/macOS | OUT | (jvm/build.sh no longer fails on macOS: G-0497) |
| G-0478, G-0496 install-image.sh hard-codes `detjs.linux-x64.node` | FIXED | machine's addon chosen; `test_no_hard_coded_linux_x64_in_install_paths` |
| G-0497 jvm/build.sh hard-codes `.so` | FIXED (build only) | `.so` or `.dylib`; JVM itself out of scope, not run |
| G-0522, G-1439 names unregistered | FOUNDER | free on 2026-11-20 (section 1); section 4 |
| G-0527 no macOS wheel | FIXED | `macosx_11_0_arm64` wheel |
| G-0529 pytest 7.0–7.2 cache INTERNALERROR | FIXED | `pytest>=8.1`; `test_pytest_floor_excludes_versions_that_break_det` |
| G-0530 xdist < 3.7 INTERNALERROR | FIXED | usage error naming the version; extra `fenvix[xdist]`; `test_old_xdist_refused_with_usage_error` |
| G-0547, G-0548, G-0550, G-0551, G-0556, G-0470, G-2219 `pytest --det` crashes on 3.9/3.10 | FIXED (refused) | `test_unsupported_interpreter_pytest_det_refused_with_message_not_crash[3.11]`, `test_unsupported_interpreter_other_det_options_refused[*]`, `test_unsupported_interpreter_det_from_addopts_refused`; CI install test on a real 3.11 |
| G-0549, G-0471 `python -m detpy` crash on 3.9 | FIXED (refused) | `test_unsupported_interpreter_commands_refused[*]` |
| G-0553, G-0555, G-0557, G-1576 free-threaded | REFUSED | not in the scope's list; `test_unsupported_interpreter_pytest_det_refused_with_message_not_crash[free-threaded]` |
| G-0554 PyPy | OUT / REFUSED | `[pypy]` case of the same test |
| G-0692, G-1336, G-1443 gate tests Node 22 only, Linux x64 only | FIXED | Node 22/24/26 × Linux x64 / arm64 / macOS arm64 |
| G-2188 Node 16 | OUT | |
| G-2189 supported Node versions stated nowhere | FIXED | `engines`, `docs/INSTALL.md`, node README |
| G-0694 gate tests only the latest pytest | OPEN | pytest 8.1 (the floor) is not run in CI |
| G-0695, G-1574 Python 3.14 never run | FIXED | 3.12/3.13/3.14 in release-1 and packages |
| G-0723 Linux-only identity suites skipped off Linux | OPEN | still skipped on macOS (ELF/glibc specific); macOS identity covered by the host tests only |
| G-0730 README is detpy-only | FIXED (install part) | README "Install" section; full rewrite not done |
| G-0731 install-image.sh is an image builder | OPEN (partly fixed) | any OS/arch now; still needs a checkout, no checksum, no uninstall mode |
| G-0732, G-2193 no version discipline | FIXED | `release/version.py`, CHANGELOG, tags; `test_one_version_everywhere`, `test_fenvix_command_version_and_doctor` |
| G-0733 upgrade path of stores | OPEN | |
| G-0737 import name `detpy` collides | OPEN (detected) | the collision itself remains (import name kept: `python -m detpy` is in scope); `fenvix doctor` reports it |
| G-0766, G-0767 requirements / containers docs | FIXED | `docs/INSTALL.md` |
| G-1490 install-image needs | FIXED (docs) | `docs/INSTALL.md` |
| G-1492, G-1575 ASLR silently on under seccomp | OPEN | documented only |
| G-1497, G-1498 cc / strace needed at run time | OPEN (documented) | `docs/INSTALL.md`; nothing bundled |
| G-1500, G-1501, G-1502 macOS ASLR / children / isolate | OPEN (documented, conservative) | children: tests that start processes are not reused on macOS |
| G-1503 Linux bundle replayed on macOS | OPEN | UNKNOWN |
| G-1505 Mocha and node:test suites fail on macOS | see section 2 | |
| G-1506 one cache test fails on macOS | see section 2 | |
| G-1543 pytest 10 deprecation in --det-isolate | OPEN | |
| G-1544 missing strace not named | OPEN | |
| G-1884 uninstall / leftovers | FIXED (docs) | `docs/INSTALL.md` "Uninstall" |
| G-2171 `main` points to a missing file | FIXED | `node/src/index.js` |
| G-2172 no engines/os/cpu/files | FIXED | generated package.json; `npm publish --dry-run` lists 58 files, no tests (MEASURED locally) |
| G-2173, G-2174, G-2175, G-2176 detjs --help/--version/unknown runner/stack traces | FIXED | `node/bin/detjs.js` (no dedicated regression test file; exercised by `npx fenvix --version` in the install test) |
| G-2177, G-2194 no .gitignore in state dirs | OPEN | |
| G-2195 WSL2 | OPEN | UNKNOWN, never run |
| G-2212 no licence file | FIXED | `LICENSE`, `license-files`; `test_install_metadata_refuses_old_python_and_names_fenvix` |
| G-2213 metadata | FIXED | pyproject metadata, `twine check --strict` |
| G-0410 Vitest < 1.4, G-1440, G-1441, G-1442 | OTHER ROW | Node runner rows |
| G-0153, G-0154 service containers blocked | OTHER ROW | network control |
| G-1493, G-1494, G-1495 containers (Go pid, gVisor, DinD) | OUT / OTHER ROW | |

## 4. Per il fondatore (passi da fare a mano)

Nessun pacchetto è stato pubblicato. TestPyPI non si usa (decisione del coordinatore): i pacchetti si validano con
`twine check --strict`, `npm publish --dry-run` e il test di installazione pulita in CI; le pre-release vanno su
PyPI vero come `X.Y.ZrcN`.

**PyPI** (il trusted publisher "pending" è già configurato: progetto `fenvix`, owner `Mircoguidetti`, repository
`fenvix-engine-cli`, workflow `release.yml`, environment `pypi`; questi nomi non vanno cambiati).
1. GitHub → Settings → Environments → crea l'ambiente **`pypi`** (se non c'è già); consigliato: "Required
   reviewers" = te, così ogni pubblicazione aspetta la tua approvazione.
2. Dopo il merge del PR, crea il tag sul commit di merge: `git tag v0.1.0 <commit> && git push origin v0.1.0`.
   Il workflow `release` ricostruisce e ritesta tutto e pubblica `fenvix 0.1.0` su PyPI senza alcun token (OIDC).
   Il primo upload trasforma il publisher "pending" in quello definitivo del progetto.
3. Pre-release: Actions → release → "Run workflow" con versione `0.1.0-rc.1` → su PyPI diventa `0.1.0rc1`
   (`pip install --pre fenvix`). Il pulsante compare solo se `release.yml` è sul branch di default (punto 9).

**npm** (scope `@fenvix` e nome `fenvix` liberi il 2026-11-20).
4. Crea un account su **npmjs.com** con 2FA attiva (meglio una passkey o un'app TOTP).
5. Crea l'organizzazione gratuita **`fenvix`**: avatar → "Add Organization" → nome `fenvix`, piano gratuito
   (solo pacchetti pubblici). Così lo scope `@fenvix` è tuo e nessun altro può pubblicare `@fenvix/...`.
6. **Primo rilascio**: npm permette di configurare il trusted publisher solo nelle impostazioni di un pacchetto che
   esiste già; se al momento sul sito trovi l'opzione per configurarlo prima della prima pubblicazione, usala e salta
   questo punto. Altrimenti la prima pubblicazione la fai tu, una volta, dal tuo computer, **senza nessun token nel
   repository**:
   - scarica dall'esecuzione del workflow `release` del tag (o di `packages` sul PR) l'artefatto `npm-tarballs`
     e scompattalo;
   - `npm login` (apre il browser e usa la tua 2FA; la sessione resta solo nel `~/.npmrc` del tuo computer);
   - pubblica prima i tre pacchetti nativi, poi quello principale:
     `npm publish fenvix-linux-x64-gnu-0.1.0.tgz --access public`,
     `npm publish fenvix-linux-arm64-gnu-0.1.0.tgz --access public`,
     `npm publish fenvix-darwin-arm64-0.1.0.tgz --access public`,
     `npm publish fenvix-0.1.0.tgz --access public`;
   - `npm logout`.
   Non serve creare token. Se preferisci non pubblicare dal tuo computer: crea un "granular access token" con
   scadenza di 1 giorno, permesso "Read and write" solo sui pacchetti/sull'org `fenvix`, usalo solo nel terminale
   (`NPM_TOKEN=... npm publish ...` con un `.npmrc` temporaneo fuori dal repository) e revocalo subito dopo; non
   va mai messo nei secrets di GitHub né in un file del repository.
7. Per ognuno dei 4 pacchetti (`fenvix`, `@fenvix/linux-x64-gnu`, `@fenvix/linux-arm64-gnu`, `@fenvix/darwin-arm64`):
   npmjs.com → pacchetto → Settings → **Trusted Publisher** → GitHub Actions: organization/user `Mircoguidetti`,
   repository `fenvix-engine-cli`, workflow filename `release.yml`, environment `npm`. Nella stessa pagina scegli
   "Require two-factor authentication and disallow tokens", così da quel momento si pubblica solo dalla CI.
8. GitHub → Settings → Environments → crea l'ambiente **`npm`**; poi Settings → Secrets and variables → Actions →
   Variables → `FENVIX_PUBLISH_NPM` = `true`. Dai tag successivi il workflow pubblica i 4 pacchetti con provenance;
   finché la variabile non c'è, npm resta `--dry-run`.

**Repository**
9. **Branch di default** (G-0561): oggi è `claude/gracious-rubin-eyswxd`, una punta del Block 2 (solo Python, 3.034
   commit dietro `claude/release-1`). Chi clona o apre il repository vede il motore vecchio; i workflow pianificati
   (`schedule`) e il pulsante "Run workflow" funzionano solo dal branch di default. Consiglio: dopo il merge di
   questo PR crea **`main`** da `claude/release-1`, impostalo come default (Settings → General → Default branch),
   proteggilo (PR obbligatoria, CI `release-1` e `packages` verdi) e crea lì i tag di rilascio; finché `main` non
   esiste, imposta come default `claude/release-1`.
10. **Licenza**: `LICENSE` è MIT con titolare "fenvix" (segnaposto): sostituiscilo con il tuo nome o quello della
    società prima del primo rilascio.
11. **macOS**: su questo account i job `macos-14` vengono annullati in coda; la CI usa `macos-15` (Apple silicon).
