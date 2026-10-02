// AbletonMCP Remote Script (127.0.0.1:9877) への直接コマンド送信
// 使い方: node ableton-cmd.js <type> ['<params JSON>']
const net = require('net');
const type = process.argv[2] || 'get_session_info';
const params = process.argv[3] ? JSON.parse(process.argv[3]) : {};

const sock = net.createConnection({ host: '127.0.0.1', port: 9877, timeout: 5000 });
let buf = '';
sock.on('connect', () => sock.write(JSON.stringify({ type, params })));
sock.on('data', (d) => {
  buf += d.toString();
  try {
    const j = JSON.parse(buf);
    console.log(JSON.stringify(j, null, 2));
    sock.end();
    process.exit(j.status === 'error' ? 1 : 0);
  } catch (e) { /* 継続受信 */ }
});
sock.on('error', (e) => { console.error('ERROR:', e.message); process.exit(2); });
setTimeout(() => { console.error('TIMEOUT. partial:', buf.slice(0, 500)); process.exit(3); }, 15000);
