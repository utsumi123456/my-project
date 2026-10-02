// TuneScope 解析ワーカー — essentia.js の重い処理を専用スレッドで実行
// （メインスレッドの音声受信をブロックしないための分離。in: {type, seg?, ...} / out: 解析結果）
const { parentPort } = require('worker_threads');
const esm = require('essentia.js');
const essentia = new esm.Essentia(esm.EssentiaWASM);

const BPM_MIN = 60, BPM_MAX = 200;
let bpmHistory = [];
let histLen = 5;
let keyVotes = new Map();
let temperleyVotes = new Map(); // 相対調ペアの決着用（temperley はメジャー/マイナー判別に強い）
let octaveSwap = false;

let foldMax = BPM_MAX;
function foldBpm(bpm) {
  while (bpm < BPM_MIN) bpm *= 2;
  while (bpm > foldMax) bpm /= 2;
  return bpm;
}
function median(arr) {
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

function analyze(seg, sr, opts) {
  opts = opts || {};
  // 実曲107曲グリッド実験 (2026-10-01, rekordbox正解) で確定したデフォルト:
  //   profiles edmm+temperley (Key厳密 49.5→57.9%)、octaveUp ON (BPM厳密 56.1→66.4%)
  const profiles = opts.profiles || ['edmm', 'temperley'];
  const useTick = opts.useTick !== false;
  const useDegara = opts.useDegara !== false;
  const octaveUp = opts.octaveUp !== false;
  const octCutoff = opts.octCutoff || 105;   // これ未満の検出BPMでオンセット密度チェック
  const octRatio = opts.octRatio || 2.2;     // 1拍あたりオンセット数の閾値（160曲グリッドで2.2が最良）
  const bpmMax = opts.bpmMax || BPM_MAX;
  foldMax = bpmMax;
  const vec = essentia.arrayToVector(seg);
  const res = { type: 'result' };
  try {
    if (opts.skipBpm) { res.bpm = null; }
    else {
    // --- BPM ---
    const r = essentia.RhythmExtractor2013(vec, 208, 'multifeature', 40);
    let raw = r.bpm;
    const dbgMf = raw;
    let dbgTick = 0, dbgDeg = 0;

    // tick 列の線形回帰で精密化（外れ間隔除去・取りこぼし拍補間つき）
    const ticks = essentia.vectorToArray(r.ticks);
    if (useTick && ticks.length >= 5) {
      const diffs = [];
      for (let i = 1; i < ticks.length; i++) diffs.push(ticks[i] - ticks[i - 1]);
      const med = median(diffs);
      let sx = 0, sy = 0, sxx = 0, sxy = 0, n = 0, idx = 0;
      for (let i = 1; i < ticks.length; i++) {
        const d = ticks[i] - ticks[i - 1];
        idx += Math.max(1, Math.round(d / med));
        if (Math.abs(d - med * Math.round(d / med)) / med > 0.15) continue;
        sx += idx; sy += ticks[i]; sxx += idx * idx; sxy += idx * ticks[i]; n++;
      }
      if (n >= 4) {
        const period = (n * sxy - sx * sy) / (n * sxx - sx * sx);
        const tickBpm = 60 / period;
        dbgTick = tickBpm;
        if (period > 0 && Math.abs(tickBpm - raw) / raw < 0.1) raw = tickBpm;
      }
    }

    // degara クロスチェック（付点/3連グリッド誤認補正）
    if (useDegara) try {
      const degF = foldBpm(essentia.RhythmExtractor2013(vec, 208, 'degara', 40).bpm);
      dbgDeg = degF;
      const cands = [1, 0.5, 2, 2 / 3, 1.5].map(m => foldBpm(raw * m));
      const best = cands.reduce((a, b) => (Math.abs(b - degF) < Math.abs(a - degF) ? b : a));
      if (Math.abs(best - degF) / degF < 0.04) raw = best;
    } catch (e) { /* multifeature のみで続行 */ }

    let bpm = foldBpm(raw);
    const conf = Math.min(1, r.confidence / 5.32);
    bpmHistory.push({ bpm, conf });
    while (bpmHistory.length > histLen) bpmHistory.shift();
    let smoothed = median(bpmHistory.map(h => h.bpm));
    let altBpm = smoothed * 2 <= bpmMax ? smoothed * 2 : smoothed / 2;
    if (altBpm < BPM_MIN) altBpm = smoothed;
    // オンセット密度によるハーフ検出補正
    // 検出BPMに対しオンセットが過密（octRatio 個/拍 超）なら ×2 側を主候補にする
    if (octaveUp && smoothed < octCutoff && smoothed * 2 <= bpmMax) {
      try {
        const or = essentia.OnsetRate(vec);
        if (or.onsetRate > (smoothed / 60) * octRatio) { const t = smoothed; smoothed = altBpm; altBpm = t; }
        or.onsets && or.onsets.delete && or.onsets.delete();
      } catch (e) { /* 利用不可なら無視 */ }
    }
    if (octaveSwap) { const t = smoothed; smoothed = altBpm; altBpm = t; }
    const avgConf = bpmHistory.reduce((a, h) => a + h.conf, 0) / bpmHistory.length;
    res.bpm = [Math.round(smoothed * 10) / 10, Math.round(avgConf * 100) / 100, Math.round(altBpm * 10) / 10];
    res.bpmDbg = `mf=${dbgMf.toFixed(1)} tick=${dbgTick.toFixed(1)} deg=${dbgDeg.toFixed(1)} final=${raw.toFixed(1)}`;
    }

    if (!opts.skipKey) {
    // --- Key（複数プロファイル投票。相対調ペアの決着は temperley を採用） ---
    let lastStrength = 0;
    let temperleyPick = null;
    for (const profile of profiles) {
      let k;
      try {
        k = essentia.KeyExtractor(vec, true, 4096, 4096, 12, 3500, 60, 25, 0.2, profile, sr);
      } catch (e) {
        try { k = essentia.KeyExtractor(vec); } catch (e2) { continue; }
      }
      const label = `${k.key} ${k.scale}`;
      keyVotes.set(label, (keyVotes.get(label) || 0) + k.strength);
      if (profile === 'temperley') {
        temperleyPick = label;
        temperleyVotes.set(label, (temperleyVotes.get(label) || 0) + k.strength);
      }
      lastStrength = Math.max(lastStrength, k.strength);
    }
    // 相対調ペア（同一構成音のメジャー/マイナー、Camelot同番号）判定
    const NOTE_IDX = { 'A': 0, 'A#': 1, 'BB': 1, 'B': 2, 'C': 3, 'C#': 4, 'DB': 4, 'D': 5, 'D#': 6, 'EB': 6, 'E': 7, 'F': 8, 'F#': 9, 'GB': 9, 'G': 10, 'G#': 11, 'AB': 11 };
    function isRelativePair(a, b) {
      const [na, sa] = a.split(' '), [nb, sb] = b.split(' ');
      if (sa === sb) return false;
      const ia = NOTE_IDX[na.toUpperCase()], ib = NOTE_IDX[nb.toUpperCase()];
      if (ia === undefined || ib === undefined) return false;
      const [maj, min] = sa === 'major' ? [ia, ib] : [ib, ia];
      return (maj - min + 12) % 12 === 3; // 例: C major(3) と A minor(0)
    }
    if (keyVotes.size > 0) {
      const sorted = [...keyVotes.entries()].sort((a, b) => b[1] - a[1]);
      let bestLabel = sorted[0][0];
      if (sorted.length >= 2 && isRelativePair(sorted[0][0], sorted[1][0])) {
        // 相対調の曖昧性は temperley の累積票で決着（メジャー/マイナー判別に最も強い）
        const t0 = temperleyVotes.get(sorted[0][0]) || 0;
        const t1 = temperleyVotes.get(sorted[1][0]) || 0;
        if (t0 !== t1) bestLabel = t0 > t1 ? sorted[0][0] : sorted[1][0];
      }
      const [name, scale] = bestLabel.split(' ');
      const total = [...keyVotes.values()].reduce((a, b) => a + b, 0);
      res.key = [name, scale, Math.round(((keyVotes.get(bestLabel) || 0) / total) * lastStrength * 100) / 100];
      // 第2候補が僅差（80%以上）なら併記用に出力（相対調・近親調の曖昧性をユーザーに提示）
      const second = sorted.find(([l]) => l !== bestLabel);
      if (second && second[1] > (keyVotes.get(bestLabel) || 0) * 0.8) {
        const [an, as] = second[0].split(' ');
        res.key.push(an, as);
      }
      res.votes = sorted;
    }
    }

    if (opts.skipChroma) return res; // vec は finally で解放
    // --- クロマ (HPCP 平均、直近8フレーム) ---
    const chroma = new Float32Array(12);
    let frames = 0;
    for (let ofs = seg.length - 4096 * 8; ofs + 4096 <= seg.length; ofs += 4096) {
      if (ofs < 0) continue;
      const fv = essentia.arrayToVector(seg.subarray(ofs, ofs + 4096));
      const win = essentia.Windowing(fv, true, 4096, 'hann');
      const spec = essentia.Spectrum(win.frame, 4096);
      const peaks = essentia.SpectralPeaks(spec.spectrum, 0, 3500, 60, 25, 'magnitude', sr);
      const hpcp = essentia.HPCP(peaks.frequencies, peaks.magnitudes, true, 500, 0, 3500, false, 60,
        true, 'unitMax', 25, sr, 12);
      const arr = essentia.vectorToArray(hpcp.hpcp);
      for (let i = 0; i < 12; i++) chroma[i] += arr[i];
      frames++;
      [fv, win.frame, spec.spectrum, peaks.frequencies, peaks.magnitudes, hpcp.hpcp].forEach(v => v.delete && v.delete());
    }
    if (frames > 0) res.chroma = [...chroma].map(v => Math.round((v / frames) * 1000) / 1000);
  } catch (e) {
    res.error = String(e.message || e);
  } finally {
    vec.delete();
  }
  return res;
}

parentPort.on('message', (msg) => {
  if (msg.type === 'analyze') {
    const seg = new Float32Array(msg.buf);
    parentPort.postMessage(analyze(seg, msg.sr, msg.opts));
  } else if (msg.type === 'reset') {
    bpmHistory = [];
    keyVotes.clear();
    temperleyVotes.clear();
  } else if (msg.type === 'smoothing') {
    histLen = [3, 5, 9][Math.max(0, Math.min(2, Number(msg.value) || 0))];
    while (bpmHistory.length > histLen) bpmHistory.shift();
  } else if (msg.type === 'bpmswap') {
    octaveSwap = !octaveSwap;
  }
});
parentPort.postMessage({ type: 'worker_ready', version: essentia.version });
