# Minimal reproductions of classic asyncio races

Each test is a deliberately flaky test written the way such tests are written in
real projects (a sleep used as synchronisation, a tight timeout, an assumed
order of results). They exist because the public flaky-test datasets contain
few asyncio timing races (see `docs/L1-ASYNCIO.md` and the L1 study report).
Only the standard library and pytest are used.
