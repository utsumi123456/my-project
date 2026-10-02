// 凍結版ロード判定: track2 のデバイス名が frozen 版で、かつブリッジ応答があれば exit 0
const net = require('net');
const http = require('http');
function cmd(t, p = {}) {
  return new Promise((res, rej) => {
    const s = net.createConnection({ host: '127.0.0.1', port: 9877 });
    let b = '';
    s.on('connect', () => s.write(JSON.stringify({ type: t, params: p })));
    s.on('data', d => { b += d; try { const j = JSON.parse(b); s.end(); res(j); } catch (e) {} });
    s.on('error', rej);
    setTimeout(() => { s.destroy(); rej(new Error('to')); }, 8000);
  });
}
(async () => {
  const t = (await cmd('get_track_info', { track_index: 2 })).result;
  const names = (t.devices || []).map(d => d.name);
  const frozen = names.some(n => /frozen|1\.0\.0/i.test(n));
  if (!frozen) { console.log('not yet: ' + names.join(',')); process.exit(1); }
  await new Promise((res, rej) => { http.get('http://127.0.0.1:7401/state', r => { r.resume(); res(); }).on('error', rej); });
  console.log('FROZEN LOADED: ' + names.join(','));
  process.exit(0);
})().catch(e => { console.log('wait: ' + e.message); process.exit(1); });
