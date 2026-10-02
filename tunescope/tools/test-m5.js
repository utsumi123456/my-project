// M5ベンチマーク: 多キー・多テンポ・変則条件での検出精度測定
const analyzer = require('./analyzer.js');

const SR = 48000, DUR = 8, N = SR * DUR;
const NOTE_NAMES = ["A","A#","B","C","C#","D","D#","E","F","F#","G","G#"]; // index 0 = A
const A4 = 440;
const noteFreq = (semiFromA4) => A4 * Math.pow(2, semiFromA4 / 12);

// 音楽的なテストトラック生成
function makeTrack(o) {
  const sig = new Float32Array(N);
  const beat = (60 / o.bpm) * SR;

  // キック（ハーフタイム時は2拍毎）
  const kickStep = o.halftime ? beat * 2 : beat;
  for (let s = 0; s < N; s += kickStep) {
    const s0 = Math.round(s);
    for (let i = 0; i < 4500 && s0 + i < N; i++) {
      const f = 110 * Math.exp(-i / 1200) + 45; // ピッチ下降キック
      sig[s0 + i] += 0.8 * Math.exp(-i / 800) * Math.sin(2 * Math.PI * f * (i / SR));
    }
  }
  // ハイハット（8分、スウィング対応）
  for (let k = 0; ; k++) {
    let s = k * beat / 2;
    if (o.swing && k % 2 === 1) s += beat * 0.08;
    const s0 = Math.round(s);
    if (s0 >= N) break;
    for (let i = 0; i < 900 && s0 + i < N; i++) {
      sig[s0 + i] += 0.12 * Math.exp(-i / 250) * (Math.random() * 2 - 1);
    }
  }
  // コード（root, 3rd, 5th）+ ベース
  const rootSemi = o.root - 12; // A3 基準側へ
  const third = o.scale === "minor" ? 3 : 4;
  for (const semi of [rootSemi, rootSemi + third, rootSemi + 7]) {
    const f = noteFreq(semi);
    for (let i = 0; i < N; i++) {
      sig[i] += 0.10 * Math.sin(2 * Math.PI * f * (i / SR)) + 0.03 * Math.sin(2 * Math.PI * 2 * f * (i / SR));
    }
  }
  const bassF = noteFreq(rootSemi - 12);
  for (let i = 0; i < N; i++) sig[i] += 0.15 * Math.sin(2 * Math.PI * bassF * (i / SR));
  // メロディ（スケール上行下行を1拍毎）
  const scaleSteps = o.scale === "minor" ? [0, 2, 3, 5, 7, 8, 10, 12] : [0, 2, 4, 5, 7, 9, 11, 12];
  for (let k = 0; ; k++) {
    const s0 = Math.round(k * beat);
    if (s0 >= N) break;
    const step = scaleSteps[k % scaleSteps.length];
    const f = noteFreq(o.root + step);
    for (let i = 0; i < beat && s0 + i < N; i++) {
      sig[s0 + i] += 0.14 * Math.sin(2 * Math.PI * f * (i / SR)) * Math.min(1, i / 800);
    }
  }
  // ノイズ
  if (o.noise) for (let i = 0; i < N; i++) sig[i] += o.noise * (Math.random() * 2 - 1);
  return sig;
}

const normNote = (n) => {
  const map = { "BB":"A#","DB":"C#","EB":"D#","GB":"F#","AB":"G#" };
  const u = String(n).toUpperCase();
  return map[u] || u;
};

// テストケース（root: A4 からの半音差。0=A4, 3=C5, -2=G4 ...）
const cases = [
  { name: "A min 128 基本",        root: 0,  scale: "minor", bpm: 128 },
  { name: "C maj 120 基本",        root: 3,  scale: "major", bpm: 120 },
  { name: "F# min 140",            root: -3, scale: "minor", bpm: 140 },
  { name: "G maj 95 スウィング",   root: -2, scale: "major", bpm: 95, swing: true },
  { name: "D min 70 スロー",       root: 5,  scale: "minor", bpm: 70 },
  { name: "E min 174 DnB",         root: 7,  scale: "minor", bpm: 174 },
  { name: "F maj 87 ハーフタイム", root: 8,  scale: "major", bpm: 87, halftime: true },
  { name: "A# min 150 ノイズ",     root: 1,  scale: "minor", bpm: 150, noise: 0.05 },
  { name: "B maj 110",             root: 2,  scale: "major", bpm: 110 },
  { name: "G# min 132 sw+noise",   root: -1, scale: "minor", bpm: 132, swing: true, noise: 0.03 },
];

let last = {};
analyzer._setOut((head, ...rest) => {
  if (head === "bpm") { last.bpm = rest[0]; last.alt = rest[2]; }
  if (head === "key") { last.key = rest[0]; last.scale = rest[1]; last.conf = rest[2]; }
});
analyzer._setSr(SR);
analyzer._setSmoothing(1);

let passB = 0, passK = 0;
const rows = [];
for (const c of cases) {
  analyzer.resetState();
  last = {};
  const sig = makeTrack(c);
  const chunk = Math.round(SR * 0.25);
  for (let pos = 0; pos + chunk <= N; pos += chunk) {
    analyzer.pushAudio(sig.subarray(pos, pos + chunk));
    if ((pos / chunk) % 8 === 7) analyzer.analyze();
  }
  const expNote = NOTE_NAMES[((c.root % 12) + 12) % 12];
  const bOk = Math.abs((last.bpm || 0) - c.bpm) < 2;
  const altOk = Math.abs((last.alt || 0) - c.bpm) < 2; // ×2/÷2 候補（ワンクリック切替）に正解あり
  const kOk = last.key && normNote(last.key) === normNote(expNote) && last.scale === c.scale;
  if (bOk) passB++;
  if (kOk) passK++;
  rows.push(`${bOk ? "OK " : (altOk ? "ALT" : "NG ")} | ${kOk ? "OK" : "NG"} | ${c.name.padEnd(20)} | bpm ${String(last.bpm).padStart(6)} alt ${String(last.alt).padStart(6)} (exp ${c.bpm}) | key ${last.key} ${last.scale} (exp ${expNote} ${c.scale}) conf ${last.conf}`);
}
console.log("BPM | KEY | case");
console.log(rows.join("\n"));
console.log(`\nBPM: ${passB}/${cases.length}  KEY: ${passK}/${cases.length}`);
