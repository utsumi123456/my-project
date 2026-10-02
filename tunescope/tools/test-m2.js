// M2検証: analyzer.js を Max なしでシミュレート（48kHz・250msチャンク・混合信号）
const analyzer = require('./analyzer.js');

const SR = 48000, DUR = 8, N = SR * DUR;
const sig = new Float32Array(N);

// 128 BPM キック + A minor パッド + メロディ（混合＝実音源に近い条件）
const interval = (60 / 128) * SR;
for (let start = 0; start < N; start += interval) {
  const s0 = Math.round(start);
  for (let i = 0; i < 4500 && s0 + i < N; i++) {
    sig[s0 + i] += 0.8 * Math.exp(-i / 700) * Math.sin(2 * Math.PI * 75 * (i / SR));
  }
}
for (const f of [220.0, 261.63, 329.63, 440.0]) {
  for (let i = 0; i < N; i++) {
    sig[i] += 0.12 * Math.sin(2 * Math.PI * f * (i / SR)) + 0.04 * Math.sin(2 * Math.PI * 2 * f * (i / SR));
  }
}
const melody = [440.0, 493.88, 523.25, 587.33, 659.25, 523.25, 493.88, 440.0];
melody.forEach((f, k) => {
  const s0 = k * SR;
  for (let i = 0; i < SR && s0 + i < N; i++) sig[s0 + i] += 0.15 * Math.sin(2 * Math.PI * f * (i / SR));
});

analyzer._setSr(SR);
const chunk = Math.round(SR * 0.25);
let analyzeCount = 0;
for (let pos = 0; pos + chunk <= N; pos += chunk) {
  analyzer.pushAudio(sig.subarray(pos, pos + chunk));
  // 2秒ごとに解析（実機の setInterval 相当）
  if ((pos / chunk) % 8 === 7) {
    const t = Date.now();
    analyzer.analyze();
    console.log(`  (analyze #${++analyzeCount}: ${Date.now() - t}ms)`);
  }
}
