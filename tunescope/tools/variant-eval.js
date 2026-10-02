// パラメータバリアント評価: cache/ の窓データに対し analysis-worker を設定違いで実行し精度比較
// 使い方: node variant-eval.js <variant名> （'list' で一覧）
const fs = require('fs');
const path = require('path');
const { Worker } = require('worker_threads');

const SR = 44100, WIN = SR * 8;
const dir = path.join(__dirname, process.env.CACHEDIR || 'cache');
const SETF = process.env.SETF || 'all'; // tune | holdout | all

const VARIANTS = {
  // BPM 系（Key/クロマをスキップして高速化）
  'bpm-base':     { skipKey: true, skipChroma: true },
  'bpm-no-tick':  { skipKey: true, skipChroma: true, useTick: false },
  'bpm-no-deg':   { skipKey: true, skipChroma: true, useDegara: false },
  'bpm-mf-only':  { skipKey: true, skipChroma: true, useTick: false, useDegara: false },
  'bpm-onset':    { skipKey: true, skipChroma: true, octaveUp: true },
  'final':        { skipChroma: true }, // 本番デフォルト（BPM+Key同時）
  // Key 系（BPM をスキップ）
  'key-base':     { skipBpm: true, skipChroma: true, profiles: ['edma', 'temperley'] },
  'key-3prof':    { skipBpm: true, skipChroma: true, profiles: ['edma', 'edmm', 'temperley'] },
  'key-edmm-t':   { skipBpm: true, skipChroma: true, profiles: ['edmm', 'temperley'] },
  'key-temperley':{ skipBpm: true, skipChroma: true, profiles: ['temperley'] },
  'key-bgate-t':  { skipBpm: true, skipChroma: true, profiles: ['bgate', 'temperley'] },
  'key-shaath-t': { skipBpm: true, skipChroma: true, profiles: ['shaath', 'temperley'] },
  'key-edmm-only':{ skipBpm: true, skipChroma: true, profiles: ['edmm'] },
  'key-edma-edmm':{ skipBpm: true, skipChroma: true, profiles: ['edma', 'edmm'] },
  'key-edmm2-t':  { skipBpm: true, skipChroma: true, profiles: ['edmm', 'edmm', 'temperley'] },
};
// オクターブ補正グリッド oct-<cutoff>-<ratio>
for (const c of [95, 100, 105, 110, 115]) {
  for (const r of [2.2, 2.5, 3.0]) {
    VARIANTS[`oct-${c}-${r}`] = { skipKey: true, skipChroma: true, octCutoff: c, octRatio: r };
  }
}
VARIANTS['bpm-max215'] = { skipKey: true, skipChroma: true, bpmMax: 215 };
VARIANTS['bpm-max215-oct110'] = { skipKey: true, skipChroma: true, bpmMax: 215, octCutoff: 110 };

const name = process.argv[2];
if (!name || !VARIANTS[name]) {
  console.log('variants:', Object.keys(VARIANTS).join(' '));
  process.exit(name === 'list' ? 0 : 1);
}
const opts = VARIANTS[name];

// 正解 index 統合
const index = [];
for (const f of fs.readdirSync(dir).filter(f => f.startsWith('index-'))) {
  index.push(...JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')));
}
index.sort((a, b) => a.i - b.i);
const filtered = SETF === 'all' ? index.slice() : index.filter(t => (t.set || 'tune') === SETF);
index.length = 0; index.push(...filtered);

// ---- 判定ユーティリティ（eval-tracks.js と同一基準） ----
function parseRbKey(k) {
  const m = String(k).trim().match(/^([A-G](?:#|b)?)(m?)$/);
  return m ? { note: m[1], scale: m[2] === 'm' ? 'minor' : 'major' } : null;
}
const NOTE_IDX = { 'A': 0, 'A#': 1, 'BB': 1, 'B': 2, 'C': 3, 'C#': 4, 'DB': 4, 'D': 5, 'D#': 6, 'EB': 6, 'E': 7, 'F': 8, 'F#': 9, 'GB': 9, 'G': 10, 'G#': 11, 'AB': 11 };
const idx = n => NOTE_IDX[String(n).toUpperCase()];
const CAM_MIN = { 0: 8, 1: 3, 2: 10, 3: 5, 4: 12, 5: 7, 6: 2, 7: 9, 8: 4, 9: 11, 10: 6, 11: 1 };
const CAM_MAJ = { 0: 11, 1: 6, 2: 1, 3: 8, 4: 3, 5: 10, 6: 5, 7: 12, 8: 7, 9: 2, 10: 9, 11: 4 };
const camNum = (n, s) => (s === 'minor' ? CAM_MIN[idx(n)] : CAM_MAJ[idx(n)]);

function makeWorker() {
  const w = new Worker(path.join(__dirname, 'analysis-worker.js'));
  const q = [];
  w.on('message', (m) => { if (m.type !== 'worker_ready') { const r = q.shift(); r && r(m); } });
  return {
    run(buf) { return new Promise(res => { q.push(res); w.postMessage({ type: 'analyze', buf, sr: SR, opts }, [buf]); }); },
    reset() { w.postMessage({ type: 'reset' }); },
    kill() { return w.terminate(); }
  };
}

async function evalTrack(w, t) {
  const raw = fs.readFileSync(path.join(dir, `t${t.i}.f32`));
  w.reset();
  let last = null;
  for (let j = 0; j < t.windows; j++) {
    const ab = new ArrayBuffer(WIN * 4);
    new Uint8Array(ab).set(raw.subarray(j * WIN * 4, (j + 1) * WIN * 4));
    last = await w.run(ab);
  }
  const det = last.bpm ? last.bpm[0] : 0;
  const alt = last.bpm ? last.bpm[2] : 0;
  const [dn, ds] = last.key ? last.key : ['', ''];
  const gt = parseRbKey(t.key);
  const out = { i: t.i, det, dn, ds };
  if (!opts.skipBpm) {
    out.bOk = Math.abs(det - t.bpm) < 2.5 || Math.abs(det - t.bpm) / t.bpm < 0.015;
    out.bOct = !out.bOk && [alt, det * 2, det / 2, det * 1.5, det * 2 / 3].some(v => Math.abs(v - t.bpm) / t.bpm < 0.02);
  }
  if (!opts.skipKey && gt && dn) {
    out.kOk = idx(dn) === idx(gt.note) && ds === gt.scale;
    out.kCam = !out.kOk && camNum(dn, ds) === camNum(gt.note, gt.scale);
    const diff = (camNum(dn, ds) - camNum(gt.note, gt.scale) + 12) % 12;
    out.kAdj = !out.kOk && !out.kCam && ds === gt.scale && (diff === 1 || diff === 11);
  }
  return out;
}

(async () => {
  const POOL = parseInt(process.env.POOL || '4');
  const workers = Array.from({ length: POOL }, makeWorker);
  const results = [];
  let next = 0;
  const t0 = Date.now();
  await Promise.all(workers.map(async (w) => {
    while (next < index.length) {
      const t = index[next++];
      results.push({ t, r: await evalTrack(w, t) });
    }
  }));
  await Promise.all(workers.map(w => w.kill()));

  const n = results.length;
  if (!opts.skipBpm) {
    const b = results.filter(x => x.r.bOk).length;
    const o = results.filter(x => x.r.bOct).length;
    console.log(`${name}: BPM exact ${b}/${n} (${(b / n * 100).toFixed(1)}%)  +oct ${o}  usable ${((b + o) / n * 100).toFixed(1)}%  [${((Date.now() - t0) / 1000).toFixed(0)}s]`);
  }
  if (!opts.skipKey) {
    const k = results.filter(x => x.r.kOk).length;
    const c = results.filter(x => x.r.kCam).length;
    const a = results.filter(x => x.r.kAdj).length;
    console.log(`${name}: KEY exact ${k}/${n} (${(k / n * 100).toFixed(1)}%)  +rel ${c}  +adj ${a}  compat ${((k + c + a) / n * 100).toFixed(1)}%  [${((Date.now() - t0) / 1000).toFixed(0)}s]`);
  }
  fs.writeFileSync(path.join(__dirname, `variant-${name}.json`), JSON.stringify(results.map(x => ({ ...x.r, bpm: x.t.bpm, key: x.t.key, title: x.t.title })), null, 0));
})();
