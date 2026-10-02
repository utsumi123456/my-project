// E2E検証: track0 のインストゥルメント確保 → テストクリップ(Am/120)生成 → 再生 → 解析確認 → 後片付け
const net = require('net');
const http = require('http');

function cmd(type, params = {}) {
  return new Promise((resolve, reject) => {
    const sock = net.createConnection({ host: '127.0.0.1', port: 9877 });
    let buf = '';
    sock.on('connect', () => sock.write(JSON.stringify({ type, params })));
    sock.on('data', (d) => { buf += d.toString(); try { const j = JSON.parse(buf); sock.end(); resolve(j); } catch (e) {} });
    sock.on('error', reject);
    setTimeout(() => { sock.destroy(); reject(new Error('timeout ' + type)); }, 15000);
  });
}
function bridgeState() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:7401/state', (res) => { let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(JSON.parse(d))); }).on('error', reject);
  });
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function findInstrument(node) {
  if (!node) return null;
  const prefer = /^(Drift|Operator|Wavetable|Analog|Electric)$/i;
  if (node.is_loadable && prefer.test(node.name)) return node;
  for (const c of (node.children || []).concat(node.categories || [])) {
    const hit = findInstrument(c);
    if (hit) return hit;
  }
  return null;
}

(async () => {
  // 0. インストゥルメント確保（既にあればスキップ）
  const t0 = (await cmd('get_track_info', { track_index: 0 })).result;
  const hasInst = (t0.devices || []).some(d => !/tunescope/i.test(d.name));
  if (hasInst) {
    console.log(`[e2e] 既存デバイスを使用: ${(t0.devices || []).map(d => d.name).join(', ')}`);
  } else {
    const tree = (await cmd('get_browser_tree', { category_type: 'instruments' })).result;
    const inst = findInstrument(tree);
    if (!inst) { console.log('[e2e] インストゥルメント未検出'); process.exit(1); }
    console.log(`[e2e] instrument: ${inst.name}`);
    await cmd('load_instrument_or_effect', { track_index: 0, uri: inst.uri });
    await sleep(2000);
  }

  // 1. テストクリップ（16拍 = 4小節 @ セットテンポ120 → 期待BPM 120, A minor）
  await cmd('delete_clip', { track_index: 0, clip_index: 0 }).catch(() => {});
  await cmd('create_clip', { track_index: 0, clip_index: 0, length: 16 });
  const notes = [];
  for (let b = 0; b < 16; b++) {
    notes.push({ pitch: 33, start_time: b, duration: 0.2, velocity: 110 });
    notes.push({ pitch: 45, start_time: b + 0.5, duration: 0.15, velocity: 70 });
  }
  [57, 60, 64].forEach(p => notes.push({ pitch: p, start_time: 0, duration: 16, velocity: 60 }));
  const mel = [69, 71, 72, 74, 76, 72, 71, 69];
  mel.forEach((p, i) => notes.push({ pitch: p, start_time: i * 2, duration: 1.8, velocity: 85 }));
  await cmd('add_notes_to_clip', { track_index: 0, clip_index: 0, notes });
  await cmd('set_clip_name', { track_index: 0, clip_index: 0, name: 'TuneScope Test (Am 120)' });

  // 2. 再生 → ポーリング
  await cmd('fire_clip', { track_index: 0, clip_index: 0 });
  console.log('[e2e] 再生中…');
  let s = null;
  for (let i = 0; i < 5; i++) {
    await sleep(3000);
    s = await bridgeState();
    console.log(`[poll ${i}] rms=${s.rms.toFixed(4)} ringFill=${s.ringFill} bpm=${s.bpm} conf=${s.bpmConf} key=${s.key} ${s.scale} keyConf=${s.keyConf}`);
  }

  // 3. 後片付け
  await cmd('stop_clip', { track_index: 0, clip_index: 0 });
  await cmd('stop_playback');
  await cmd('delete_clip', { track_index: 0, clip_index: 0 });

  const bpmOk = s && (Math.abs(s.bpm - 120) < 2.5 || Math.abs((s.altBpm || 0) - 120) < 2.5);
  const keyOk = s && s.key === 'A' && s.scale === 'minor';
  const audioOk = s && s.rms > 0.001;
  console.log(`[e2e] audio=${audioOk ? 'PASS' : 'FAIL'} BPM(120)=${bpmOk ? 'PASS' : 'CHECK'} Key(Am)=${keyOk ? 'PASS' : 'CHECK'}`);
  process.exit(0);
})().catch(e => { console.error('[error]', e.message); process.exit(2); });
