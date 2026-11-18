// M1 check (round 3): does a server keep-alive close crossing the runner's socket reuse give 'read ECONNRESET'?
// node keepalive-server.js 50 & node keepalive-client.js 50 idle|busy   (run from node/ so playwright-core resolves)
const { request } = require('playwright-core');
const KA = Number(process.argv[2] || 50), MODE = process.argv[3];
(async () => {
  const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:4706' });
  const errs = {}; const N = 300;
  for (let i = 0; i < N; i++) {
    try { await ctx.get('/x'); } catch (e) { const k = (/read ECONNRESET|socket hang up|EPIPE|ECONNRESET/.exec(e.message) || [e.message.slice(0, 50)])[0]; errs[k] = (errs[k] || 0) + 1; }
    await new Promise((r) => setTimeout(r, KA - 10));
    if (MODE === 'busy') { const t = Date.now(); while (Date.now() - t < 12 + (i % 6)) { /* runner busy when the close arrives */ } }
    else await new Promise((r) => setTimeout(r, 12 + (i % 6)));
  }
  console.log(JSON.stringify({ keepAliveTimeout: KA, mode: MODE, requests: N, errors: errs }));
  await ctx.dispose();
})();
