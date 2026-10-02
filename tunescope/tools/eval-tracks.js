// 実曲評価: truth.json (rekordbox正解) の各曲を ffmpeg でデコードし、
// 本番の analysis-worker.js で解析して BPM/Key を照合する
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { Worker } = require('worker_threads');
const ffmpeg = require('ffmpeg-static');

const SR = 44100;
const WIN_SEC = 8;
const truth = JSON.parse(fs.readFileSync(path.join(__dirname, 'truth.json'), 'utf8'));

// rekordbox キー表記 ("Bbm","F#","Ab") → {note, scale}
function parseRbKey(k) {
  const m = String(k).trim().match(/^([A-G](?:#|b)?)(m?)$/);
  if (!m) return null;
  return { note: m[1], scale: m[2] === 'm' ? 'minor' : 'major' };
}
const NOTE_IDX = { 'A': 0, 'A#': 1, 'BB': 1, 'B': 2, 'C': 3, 'C#': 4, 'DB': 4, 'D': 5, 'D#': 6, 'EB': 6, 'E': 7, 'F': 8, 'F#': 9, 'GB': 9, 'G': 10, 'G#': 11, 'AB': 11 };
const idx = n => NOTE_IDX[String(n).toUpperCase()];
const CAM_MIN = { 0: 8, 1: 3, 2: 10, 3: 5, 4: 12, 5: 7, 6: 2, 7: 9, 8: 4, 9: 11, 10: 6, 11: 1 };
const CAM_MAJ = { 0: 11, 1: 6, 2: 1, 3: 8, 4: 3, 5: 10, 6: 5, 7: 12, 8: 7, 9: 2, 10: 9, 11: 4 };
function camelotNum(note, scale) { return scale === 'minor' ? CAM_MIN[idx(note)] : CAM_MAJ[idx(note)]; }

function decode(file) {
  const r = spawnSync(ffmpeg, ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1', '-ar', String(SR), '-'],
    { maxBuffer: 1024 * 1024 * 512 });
  if (r.status !== 0 || !r.stdout || r.stdout.length < SR * 4 * 30) return null;
  return new Float32Array(r.stdout.buffer, r.stdout.byteOffset, Math.floor(r.stdout.length / 4));
}

function makeWorker() {
  const w = new Worker(path.join(__dirname, 'analysis-worker.js'));
  const q = [];
  w.on('message', (m) => { if (m.type !== 'worker_ready') { const r = q.shift(); r && r(m); } });
  return {
    analyze(seg) {
      return new Promise((resolve) => {
        q.push(resolve);
        const buf = seg.slice().buffer;
        w.postMessage({ type: 'analyze', buf, sr: SR }, [buf]);
      });
    },
    reset() { w.postMessage({ type: 'reset' }); },
    kill() { return w.terminate(); }
  };
}

(async () => {
  const w = makeWorker();
  const rows = [];
  let nB = 0, nBOct = 0, nK = 0, nKCam = 0, nKRel = 0, total = 0;
  const start = process.argv[2] ? parseInt(process.argv[2]) : 0;
  const limit = process.argv[3] ? parseInt(process.argv[3]) : truth.length;

  for (const t of truth.slice(start, start + limit)) {
    if (t.is_cloud) continue;
    const file = t.folder_path;
    if (!fs.existsSync(file)) { rows.push(`SKIP (file missing) ${t.title}`); continue; }
    const gtKey = parseRbKey(t.key);
    const sig = decode(file);
    if (!sig) { rows.push(`SKIP (decode fail) ${t.title}`); continue; }

    w.reset();
    // 曲の 25% / 45% / 65% 地点の 8 秒窓を解析（デバイスの累積投票を模倣）
    let last = null;
    for (const frac of [0.25, 0.45, 0.65]) {
      const start = Math.min(Math.max(0, Math.floor(sig.length * frac)), sig.length - SR * WIN_SEC);
      const seg = sig.subarray(start, start + SR * WIN_SEC);
      last = await w.analyze(seg);
    }
    total++;
    const det = last.bpm ? last.bpm[0] : 0;
    const alt = last.bpm ? last.bpm[2] : 0;
    const [dn, ds] = last.key ? last.key : ['', ''];

    const bOk = Math.abs(det - t.bpm) < 2.5 || Math.abs(det - t.bpm) / t.bpm < 0.015;
    const bOct = !bOk && [alt, det * 2, det / 2, det * 1.5, det * 2 / 3].some(v => Math.abs(v - t.bpm) / t.bpm < 0.02);
    const kExact = gtKey && dn && idx(dn) === idx(gtKey.note) && ds === gtKey.scale;
    const kCam = !kExact && gtKey && dn && camelotNum(dn, ds) === camelotNum(gtKey.note, gtKey.scale); // 相対調(同番号)
    const kRel = !kExact && !kCam && gtKey && dn && Math.abs(((camelotNum(dn, ds) - camelotNum(gtKey.note, gtKey.scale) + 12) % 12 + 18) % 12 - 6) === 5; // 隣接(±1)

    if (bOk) nB++; else if (bOct) nBOct++;
    if (kExact) nK++; else if (kCam) nKCam++; else if (kRel) nKRel++;
    rows.push(
      `${bOk ? 'OK ' : bOct ? 'OCT' : 'NG '} bpm ${String(det).padStart(6)}/${String(t.bpm).padStart(7)} | ` +
      `${kExact ? 'OK ' : kCam ? 'REL' : kRel ? 'ADJ' : 'NG '} key ${(dn + ' ' + ds).padEnd(9)}/${String(t.key).padEnd(4)} | ${(t.artist + ' - ' + t.title).slice(0, 48)}`
    );
    if (total % 10 === 0) console.error(`  ...${total} done`);
  }
  await w.kill();
  console.log(rows.join('\n'));
  console.log(`\n==== ${total} tracks ====`);
  console.log(`BPM : exact ${nB} (${(nB / total * 100).toFixed(0)}%)  +octave/triplet ${nBOct}  -> usable ${(100 * (nB + nBOct) / total).toFixed(0)}%`);
  console.log(`KEY : exact ${nK} (${(nK / total * 100).toFixed(0)}%)  +relative(same Camelot#) ${nKCam}  +adjacent(±1) ${nKRel}  -> DJ-compatible ${(100 * (nK + nKCam + nKRel) / total).toFixed(0)}%`);
})();
