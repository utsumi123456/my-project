// 実機スモーク: rekordbox正解付きの実曲をデバイス経由で解析し、オフライン評価と一致するか確認
const net = require('net');
const http = require('http');
const fs = require('fs');
const path = require('path');

function cmd(type, params = {}) {
  return new Promise((resolve, reject) => {
    const sock = net.createConnection({ host: '127.0.0.1', port: 9877 });
    let buf = '';
    sock.on('connect', () => sock.write(JSON.stringify({ type, params })));
    sock.on('data', (d) => { buf += d.toString(); try { const j = JSON.parse(buf); sock.end(); resolve(j); } catch (e) {} });
    sock.on('error', reject);
    setTimeout(() => { sock.destroy(); reject(new Error('timeout ' + type)); }, 20000);
  });
}
const get = (p) => new Promise((res, rej) => http.get('http://127.0.0.1:7401' + p, r => { let d = ''; r.on('data', c => d += c); r.on('end', () => res(d)); }).on('error', rej));
const sleep = ms => new Promise(r => setTimeout(r, ms));

const truth = JSON.parse(fs.readFileSync(path.join(__dirname, 'truth.json'), 'utf8'));
const pick = (substr) => truth.find(t => (t.artist + ' ' + t.title).includes(substr));
const cases = [pick('Bangarang'), pick('heal'), pick('watercolor')].filter(Boolean);

(async () => {
  // track 2 に TuneScope があるか
  const t2 = (await cmd('get_track_info', { track_index: 2 })).result;
  if (!(t2.devices || []).some(d => /tunescope/i.test(d.name))) {
    console.log(`track2 (${t2.name}) に TuneScope なし devices=[${(t2.devices || []).map(d => d.name)}]`); process.exit(1);
  }
  for (const c of cases) {
    await cmd('set_tempo', { tempo: Math.round(c.bpm * 100) / 100 }); // ワープ≈恒等（正解=rekordbox BPM）
    await cmd('delete_clip', { track_index: 2, clip_index: 0 }).catch(() => {});
    await cmd('create_audio_clip', { track_index: 2, clip_index: 0, path: c.folder_path.replace(/\//g, '\\') });
    await sleep(3000); // クリップのロード完了待ち（直後の fire は空振りすることがある）
    await get('/reset');
    await cmd('fire_clip', { track_index: 2, clip_index: 0 });
    // 音が流れ始めるまで待機（最大10秒、無音なら再fire）
    for (let i = 0; i < 10; i++) {
      await sleep(1000);
      const s0 = JSON.parse(await get('/state'));
      if (s0.rms > 0.01) break;
      if (i === 4) await cmd('fire_clip', { track_index: 2, clip_index: 0 });
    }
    await sleep(22000);
    const s = JSON.parse(await get('/state'));
    await cmd('stop_clip', { track_index: 2, clip_index: 0 });
    await cmd('stop_playback');
    await cmd('delete_clip', { track_index: 2, clip_index: 0 });
    const bOk = Math.abs(s.bpm - c.bpm) / c.bpm < 0.02;
    console.log(`${bOk ? 'OK ' : 'NG '} ${c.artist} - ${c.title}: det ${s.bpm} ${s.key} ${s.scale} (rb: ${c.bpm} ${c.key}) rms=${s.rms.toFixed(3)}`);
  }
  await cmd('set_tempo', { tempo: 120 });
  process.exit(0);
})().catch(e => { console.error('[error]', e.message); process.exit(2); });
