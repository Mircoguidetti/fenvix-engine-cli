FIX 1

# R-002 re-check 2: loopback-proxy guard (fenvix-engine-cli `claude/loving-maxwell-58mv2w` @ e939c1b)

I am the reviewer. I worked in two detached sparse worktrees: `rc2-new` at e939c1b (it contains aac1b11) and `rc2-old` at dbb3bbe. I pushed nothing, and I removed both worktrees at the end. `<scratch>` = `/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad`. New files are in `<scratch>/review-R-002c/`.

Labels: **MEASURED** = measured by me. **DECLARED** = taken from the delivery's files.

## Summary

| check | result |
|---|---|
| My R-002b tests (`review-R-002b/test_r002b_go_proxy.py`) on e939c1b | **2 passed** (MEASURED) |
| The same tests on dbb3bbe (control) | **2 failed** (MEASURED) |
| `harness/skip_study2/tests/` on e939c1b | **17 passed** (MEASURED; DECLARED: 17 of 17) |
| Variant: lowercase `https_proxy` only | passes on e939c1b, fails on dbb3bbe |
| Variant: `ALL_PROXY` only (a unit that runs curl) | passes on e939c1b, fails on dbb3bbe |
| Variant: `NO_PROXY` that exempts loopback | passes on e939c1b, fails on dbb3bbe |
| Variant: proxy named `localhost` | passes on e939c1b, fails on dbb3bbe |
| **Variant: proxy named by another hostname that maps to loopback** | **fails on e939c1b** (proven error 1) |
| REPORT v3.1: Go `strict` labelled "no proof" | **Done.** Every Go `strict` row in §2, §3 and the `aggregate.py --md v3` output now reads "go test cache + config (no proof)". §1 explains why (MEASURED). |
| REPORT v3.1: Home Assistant rerun-everything commits | **Correct** (MEASURED from the raw shards, details below) |
| REPORT v3.1: saleor marked stale | **Done.** The headline row and §2 are marked. The snapshot (29 transitions, `closure` 0% / 13%, 56 (0, 0), 25/29) matches `aggregate.py --md r5` exactly (MEASURED). |
| REPORT v3.1: withdrawn v2 claim | **Done in the text.** One cosmetic leftover (see the notes). |
| REPORT v3.1: exposure upper bound | **Reproduced.** Units with a connect but no external one, from `results/v3/walk`: HA 119/776, prometheus 26/90, terraform 10/125, docusaurus 1/202, vue-core 0/185 (MEASURED). These equal the report's numbers. |

## Proven error

### 1. A proxy named by a hostname other than `localhost` that resolves to loopback is not recognised

**Cause.** `strace_deps.proxy_endpoints()` handles two cases only: an IP literal and the exact name `localhost`. It drops every other name with the comment "a named non-local host: its connect is already external". That comment is wrong when the name resolves to loopback through `/etc/hosts`. Some examples:
- Debian and Ubuntu map the machine's own hostname to 127.0.1.1 by default;
- `localhost.localdomain` and `ip6-localhost`;
- this container maps `runsc` and `vm` to 127.0.0.1.

So a proxy set as `http://$(hostname):3128`, for example a local cntlm or px proxy on a corporate machine, is missed. The unit connects only to 127.0.0.1:<port>, `net_ext = 0`, and every rule reuses the PASS.

**Failing test:** `<scratch>/review-R-002c/test_r002c_proxy_variants.py::test_proxy_named_by_another_loopback_hostname`. It takes the first non-localhost loopback name from `/etc/hosts`, which is `runsc` here, and sets `HTTPS_PROXY=http://runsc:41047`. It then runs a pytest unit that fetches `https://github.com/` with urllib, through the walker under strace. MEASURED on e939c1b:

```
AssertionError: closure reuses the PASS of a test that needs github.com via {'HTTPS_PROXY': 'http://runsc:41047'}
(net=1 net_ext=0): {'closure': None, 'func+guard': None, 'func': None, 'closure~cfg': None, 'func+guard~cfg': None}
```

Run it with `WT=<worktree> python -m pytest -q test_r002c_proxy_variants.py`. It needs the review-R-002 helper (`../review-R-002/test_r002_capture.py`), uv, strace, curl and a loopback HTTPS proxy, and it skips without the proxy. The other 4 tests in the file pass on e939c1b and fail on dbb3bbe. They also serve as regression tests for the variants that work.

**Fix suggestion.** In `proxy_endpoints()`, resolve a host that is not an IP literal with `socket.getaddrinfo(host, port)`, at record time and in the unit's environment. Add each loopback or unspecified result, or add `(None, port)` when any result is loopback. Resolving names is safe: a name that resolves to a public address is already external by its address. Then fix the comment.

**Severity.** Low (ESTIMATED). It is the same class of gap as R-002b, but narrower: the proxy must be configured by a name rather than by 127.0.0.1 or `localhost`. There is no effect on the study numbers, because GitHub Actions sets no proxy.

## Variants checked that hold (MEASURED, e939c1b)
- **Lowercase `https_proxy` only** (upper case removed): `closure = network`.
- **`ALL_PROXY` only** (no HTTP(S)_PROXY): the unit runs `curl https://github.com/`, which honours ALL_PROXY. strace `-f` follows the child, and `closure = network`.
- **`NO_PROXY=localhost,127.0.0.1,::1,127.0.0.0/8`** (as in this container): `closure = network`.
  - By reasoning, NO_PROXY cannot cause a false skip. A host that NO_PROXY exempts is reached directly, so its address is already external. A loopback service that NO_PROXY exempts listens on a different port from the proxy, so it is not taken for the proxy.
  - The only cost is over-rerun: a unit that talks only to a local service whose port equals the proxy port. That cannot happen while the proxy holds the port.
- **`HTTPS_PROXY=http://localhost:<port>`**: `closure = network`.

## Not counted (outside the env-variable design, for the record)
The guard reads only `HTTPS_PROXY`, `HTTP_PROXY` and `ALL_PROXY` from the walker's environment. It misses a proxy that a unit takes from somewhere else:
- another variable: `GLOBAL_AGENT_HTTPS_PROXY` (global-agent), `npm_config_https_proxy`, or a `<scheme>_proxy` such as `ftp_proxy` / `ws_proxy`, which Python urllib honours;
- a config file: `~/.gitconfig http.proxy`, `.npmrc`, `.curlrc`;
- a proxy URL written in the test code.

This container sets several of these, but always to the same port as `HTTPS_PROXY`, so they are caught here by accident. A sturdier option is to log each unit's connects at the proxy (my R-002b alternative). I did not count this as an error.

## REPORT v3.1 notes, details
- **Home Assistant (MEASURED from `results/r5/walk` and `results/v3/walk`):**
  - v2 shards 0, 2 and 3 start at 5165401a, and shard 1 starts at 182d5bfb. All 8 v3 shards start at 9bf68ccb and end at 5aaa6c4a.
  - v2 shards 0, 2 and 3 rerun every unit at 093f076f, 0c98254c, 8d331d64, d22efd4d and e362a965, as the report says. v2 shard 1 does so at those 5 plus 00235fdc and b0147d0a.
  - Every v3 shard reruns every unit at the same 8 commits: those 7 plus 5aaa6c4a. So the report is right that 7 of the 8 commits fall in a v2 window and 5aaa6c4a is v3 only.
  - The explanation (shards misaligned, merged by transition index) holds.
- **Withdrawn v2 claim.** The §2 observation now calls "no commit forced everything" an aggregation artefact, and the re-check section withdraws "0 of 50". Two cosmetic leftovers remain:
  - the §2 table's Home Assistant rows (lines 228-231) still print `0/50 (-)` in the "invalidate all" column with no marker;
  - the cross-reference in line 248 points to a heading that does not exist ("Home Assistant: 8 of 50 commits rerun everything"; the bullet reads "Note: Home Assistant v3 reruns everything at 8 of 50 commits").
- **Go `strict`.** The relabel goes through `aggregate.rule_label()`. In the agent table, Go is detected by `'go-cache' in ag['pooled_time']`. The three Go agent rows (github-mcp-server, typescript-go) read correctly.

## Files
- `<scratch>/review-R-002c/test_r002c_proxy_variants.py`: 5 variant tests. On e939c1b, 1 fails (error 1) and 4 pass. On dbb3bbe, all 5 fail.
- `<scratch>/review-R-002c/v3-md.md`: `aggregate.py --md v3` output on e939c1b.
- `<scratch>/review-R-002c/REPORT-v31.md`: the REPORT as reviewed.
