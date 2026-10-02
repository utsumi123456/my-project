// M1検証: essentia.js が Node 上で動き、既知の BPM/Key を正しく推定できるか
const esm = require('essentia.js');

const SR = 44100;
const DUR = 8; // seconds
const N = SR * DUR;

// --- テスト信号1: 128 BPM のクリックトラック（キック風: 減衰サイン 80Hz） ---
function makeClickTrack(bpm) {
  const sig = new Float32Array(N);
  const interval = (60 / bpm) * SR;
  for (let start = 0; start < N; start += interval) {
    const s0 = Math.round(start);
    for (let i = 0; i < 4000 && s0 + i < N; i++) {
      const env = Math.exp(-i / 600);
      sig[s0 + i] += 0.9 * env * Math.sin(2 * Math.PI * 80 * (i / SR));
    }
  }
  return sig;
}

// --- テスト信号2: A minor（A-C-E）のコードパッド＋分散和音 ---
function makeAminorPad() {
  const sig = new Float32Array(N);
  const freqs = [220.0, 261.63, 329.63, 440.0]; // A3, C4, E4, A4
  for (const f of freqs) {
    for (let i = 0; i < N; i++) {
      // 各音に軽い倍音を追加して現実的なスペクトルに
      sig[i] += 0.15 * Math.sin(2 * Math.PI * f * (i / SR))
              + 0.05 * Math.sin(2 * Math.PI * 2 * f * (i / SR));
    }
  }
  // メロディ: A-B-C-D-E (Aナチュラルマイナー) を1秒ずつ
  const melody = [440.0, 493.88, 523.25, 587.33, 659.25, 523.25, 493.88, 440.0];
  melody.forEach((f, k) => {
    const s0 = k * SR;
    for (let i = 0; i < SR && s0 + i < N; i++) {
      sig[s0 + i] += 0.2 * Math.sin(2 * Math.PI * f * (i / SR)) * Math.min(1, i / 1000);
    }
  });
  return sig;
}

async function main() {
  const t0 = Date.now();
  const essentia = new esm.Essentia(esm.EssentiaWASM);
  console.log(`[init] essentia.js ${essentia.version} (algorithms: ${essentia.algorithmNames.split(',').length}) init ${Date.now() - t0}ms`);

  // BPM
  let t = Date.now();
  const clickVec = essentia.arrayToVector(makeClickTrack(128));
  const rhythm = essentia.RhythmExtractor2013(clickVec, 208, 'multifeature', 40);
  console.log(`[bpm] estimated=${rhythm.bpm.toFixed(2)} (expected 128) confidence=${rhythm.confidence.toFixed(2)} in ${Date.now() - t}ms`);
  clickVec.delete();

  // Key
  t = Date.now();
  const padVec = essentia.arrayToVector(makeAminorPad());
  const key = essentia.KeyExtractor(padVec);
  console.log(`[key] estimated=${key.key} ${key.scale} (expected A minor) strength=${key.strength.toFixed(2)} in ${Date.now() - t}ms`);
  padVec.delete();

  const bpmOk = Math.abs(rhythm.bpm - 128) < 1.0;
  const keyOk = key.key === 'A' && key.scale === 'minor';
  console.log(`[result] BPM: ${bpmOk ? 'PASS' : 'FAIL'} / Key: ${keyOk ? 'PASS' : 'FAIL'}`);
  process.exit(bpmOk && keyOk ? 0 : 1);
}

main().catch(e => { console.error('[error]', e); process.exit(2); });
