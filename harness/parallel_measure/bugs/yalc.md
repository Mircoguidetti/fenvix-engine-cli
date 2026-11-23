# yalc: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/Othmane-Khadri/YALC-the-GTM-operating-system at 5686d1f2f526346133f78eef3349fc5a655757b4; engine verdicts from trunk ['bfaf70b4']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

1 test(s).

## `src/__tests__/capability-adapters.test.ts::icp-company-search adapters::crustdata adapter calls autocomplete_filter BEFORE company_search_db`

* plain runs failed: plain par4-1, plain par4-2, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2; passed: plain serial 1
* engine runs: engine P1w2=failed, engine P1w4=failed, engine P2w2=failed, engine P2w4=failed, engine P3w2=failed, engine P3w4=failed, engine S1=failed, engine S2=failed, engine S3=failed
* engine cause (verify1w2.json): [env] outside any test the run read sources that are not controlled (env:*, env:HTTPS_PROXY, env:NO_PROXY, env:OLDPWD, env:PWD, env:SHLVL, env:TEMP, env:TMP, env:TMPDIR, env:_, env:https_proxy, env:no_proxy, native:/home/user/pm/repos/YALC-the-GTM-operating-system/node_modules/.pnpm/@libsql+linux-x64-gnu@0.5.22/node_modules/@libsql/linux-x64-gnu/index.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/yalc/repro/par4-1.raw.json --reporter=/home/user/pm/repos/YALC-the-GTM-operating-system/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (6 of 7 plain runs failed)

