const http = require('http');
const s = http.createServer((req, res) => res.end('ok'));
s.keepAliveTimeout = Number(process.argv[2] || 50);
s.listen(4706, () => console.log('up'));
