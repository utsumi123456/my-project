// 各曲から 8 秒窓×5 (20/35/50/65/80%) を切り出して cache/ にバイナリ保存
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const ffmpeg = require('ffmpeg-static');

const SR = 44100, WIN = SR * 8;
const FRACS = [0.20, 0.35, 0.50, 0.65, 0.80];
const truth = JSON.parse(fs.readFileSync(path.join(__dirname, process.env.TRUTH || 'truth.json'), 'utf8'));
const dir = path.join(__dirname, process.env.CACHEDIR || 'cache');
fs.mkdirSync(dir, { recursive: true });

const start = parseInt(process.argv[2] || '0');
const count = parseInt(process.argv[3] || String(truth.length));

const index = [];
for (let i = start; i < Math.min(start + count, truth.length); i++) {
  const t = truth[i];
  if (t.is_cloud || !fs.existsSync(t.folder_path)) { console.error(`skip ${i}`); continue; }
  const r = spawnSync(ffmpeg, ['-v', 'error', '-i', t.folder_path, '-f', 'f32le', '-ac', '1', '-ar', String(SR), '-'],
    { maxBuffer: 1024 * 1024 * 512 });
  if (r.status !== 0 || !r.stdout || r.stdout.length < SR * 4 * 60) { console.error(`decode fail ${i}`); continue; }
  const sig = new Float32Array(r.stdout.buffer, r.stdout.byteOffset, Math.floor(r.stdout.length / 4));
  const bufs = [];
  for (const f of FRACS) {
    const s = Math.min(Math.max(0, Math.floor(sig.length * f)), sig.length - WIN);
    bufs.push(Buffer.from(sig.buffer, sig.byteOffset + s * 4, WIN * 4));
  }
  fs.writeFileSync(path.join(dir, `t${i}.f32`), Buffer.concat(bufs));
  index.push({ i, bpm: t.bpm, key: t.key, title: t.title, artist: t.artist, windows: FRACS.length, set: t.set || 'tune' });
  if ((i - start) % 10 === 9) console.error(`...${i + 1}`);
}
fs.writeFileSync(path.join(dir, `index-${start}.json`), JSON.stringify(index));
console.log(`cached ${index.length} tracks (start=${start})`);
