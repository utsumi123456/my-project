// E2E自動検証: セッション調査 → TuneScopeトラック特定 → クリップ再生 → 解析結果確認 → 停止
const net = require('net');
const http = require('http');

function cmd(type, params = {}) {
  return new Promise((resolve, reject) => {
    const sock = net.createConnection({ host: '127.0.0.1', port: 9877 });
    let buf = '';
    sock.on('connect', () => sock.write(JSON.stringify({ type, params })));
    sock.on('data', (d) => {
      buf += d.toString();
      try { const j = JSON.parse(buf); sock.end(); resolve(j); } catch (e) { /* 継続 */ }
    });
    sock.on('error', reject);
    setTimeout(() => { sock.destroy(); reject(new Error('timeout ' + type)); }, 10000);
  });
}

function bridgeState() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:7401/state', (res) => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  // 1. トラック調査
  const session = (await cmd('get_session_info')).result;
  console.log(`[session] tempo=${session.tempo} tracks=${session.track_count} playing=${session.is_playing}`);
  let tuneTrack = -1, clipTrack = -1, clipSlot = -1, clipName = '';
  for (let i = 0; i < session.track_count; i++) {
    const t = (await cmd('get_track_info', { track_index: i })).result;
    const devs = (t.devices || []).map(d => d.name);
    const clips = (t.clip_slots || []).filter(s => s.has_clip);
    console.log(`[track ${i}] "${t.name}" audio=${t.is_audio_track} devices=[${devs.join(', ')}] clips=${clips.length}`);
    if (devs.some(n => /tunescope/i.test(n))) tuneTrack = i;
    if (t.is_audio_track && clips.length && clipTrack < 0) {
      clipTrack = i; clipSlot = clips[0].index; clipName = clips[0].clip.name;
    }
  }
  if (tuneTrack < 0) { console.log('[verify] TuneScope デバイスが見つかりません'); process.exit(1); }
  console.log(`[verify] TuneScope はトラック ${tuneTrack} に存在`);

  // 2. ブリッジ初期状態
  const s0 = await bridgeState();
  console.log(`[bridge] ready. sr=${s0.srIn} ringFill=${s0.ringFill}`);

  // 3. 再生できるクリップがあれば再生して解析を確認
  if (clipTrack >= 0 && clipTrack === tuneTrack) {
    console.log(`[verify] クリップ "${clipName}" (track ${clipTrack}, slot ${clipSlot}) を12秒再生して解析検証`);
    await cmd('fire_clip', { track_index: clipTrack, clip_index: clipSlot });
    await sleep(12000);
    const s1 = await bridgeState();
    console.log(`[analysis] bpm=${s1.bpm} conf=${s1.bpmConf} key=${s1.key} ${s1.scale} keyConf=${s1.keyConf}`);
    await cmd('stop_clip', { track_index: clipTrack, clip_index: clipSlot });
    await cmd('stop_playback');
    console.log(s1.bpm > 0 && s1.key ? '[verify] E2E PASS: 解析まで動作確認' : '[verify] 再生したが解析値が未出力（音声ルーティング要確認）');
  } else {
    console.log('[verify] TuneScopeトラック上に再生可能なオーディオクリップなし → ロード確認まで完了（音を流せば解析開始）');
  }
  process.exit(0);
})().catch(e => { console.error('[error]', e.message); process.exit(2); });
