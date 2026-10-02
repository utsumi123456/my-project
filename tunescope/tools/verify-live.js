// 自動検証: TuneScopeブリッジ(7401) と AbletonMCP Remote Script(9877) の稼働確認
const http = require('http');
const net = require('net');

function checkBridge() {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:7401/state', { timeout: 2000 }, (res) => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve({ ok: true, state: JSON.parse(d) }));
    });
    req.on('error', () => resolve({ ok: false }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false }); });
  });
}

function checkAbletonMCP() {
  return new Promise((resolve) => {
    const sock = net.createConnection({ host: '127.0.0.1', port: 9877, timeout: 2000 });
    let buf = '';
    sock.on('connect', () => sock.write(JSON.stringify({ type: 'get_session_info', params: {} })));
    sock.on('data', (d) => {
      buf += d.toString();
      try { const j = JSON.parse(buf); sock.end(); resolve({ ok: true, info: j }); } catch (e) { /* 継続受信 */ }
    });
    sock.on('error', () => resolve({ ok: false }));
    sock.on('timeout', () => { sock.destroy(); resolve({ ok: false }); });
    setTimeout(() => { try { sock.destroy(); } catch (e) {} resolve({ ok: false, partial: buf.slice(0, 200) }); }, 5000);
  });
}

(async () => {
  const b = await checkBridge();
  if (b.ok) {
    const s = b.state;
    console.log(`[TuneScope] LOADED  bpm=${s.bpm} conf=${s.bpmConf} key=${s.key} ${s.scale} sr=${s.srIn} ringFill=${s.ringFill} frozen=${s.frozen}`);
    if (s.log && s.log.length) console.log('[TuneScope] log:', s.log.slice(-3).join(' | '));
  } else {
    console.log('[TuneScope] NOT LOADED (bridge 7401 応答なし)');
  }
  const a = await checkAbletonMCP();
  if (a.ok) {
    const r = a.info.result || a.info;
    console.log(`[AbletonMCP] ACTIVE  tempo=${r.tempo} tracks=${r.track_count ?? (r.tracks && r.tracks.length)} playing=${r.is_playing}`);
  } else {
    console.log('[AbletonMCP] INACTIVE (port 9877 応答なし — Control Surface 未設定 or Live 再起動待ち)');
  }
  process.exit(0);
})();
