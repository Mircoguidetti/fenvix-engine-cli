const http = require('http');
let hits = 0, bg = 0, bumps = 0;
setInterval(() => { bg++; }, 100);
const page = `<!doctype html><html><body>
<div id="frames">0</div><div id="ticks">0</div><button id="go">go</button><div id="out"></div>
<script>
let frames = 0, ticks = 0, draws = 0;
function f(){ frames++; draws += Math.random() < 0.5 ? 1 : 0; document.getElementById('frames').textContent = frames + ':' + draws; requestAnimationFrame(f); }
requestAnimationFrame(f);
setInterval(() => fetch('/tick').then(r => r.text()).then(t => { ticks++; document.getElementById('ticks').textContent = t; }), 30);
document.getElementById('go').onclick = async () => {
  const r = await fetch('/data'); const t = await r.text();
  setTimeout(() => { document.getElementById('out').textContent = 'done ' + t + ' f=' + frames; }, 50);
};
</script></body></html>`;
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  if (req.url === '/quiet') { res.setHeader('content-type','text/html'); return res.end('<p>quiet</p>'); }
  if (req.url === '/tick') { hits++; return res.end(`tick ${hits} bg ${bg} t ${Date.now() % 100000}`); }
  if (req.url === '/data') return setTimeout(() => res.end(`data ${hits} ${bg} ${bumps}`), 20);
  if (req.url === '/bump') { bumps++; return res.end(`bumped ${bumps} bg ${bg}`); }
  res.setHeader('content-type', 'text/html'); res.end(page);
}).listen(4801);
