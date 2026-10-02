// TuneScope 解析エンジン (node.script / Node for Max)
// メインスレッド: 音声受信・リング管理・SR実測・開発ブリッジのみ（決してブロックしない）
// 重い essentia 解析は analysis-worker.js (worker_threads) に委譲
let maxApi = null;
try { maxApi = require('max-api'); } catch (e) { /* スタンドアロンテスト時 */ }
const path = require('path');
const { Worker } = require('worker_threads');

const TARGET_SR = 44100;
const WINDOW_SEC = 8;
const ANALYZE_INTERVAL_MS = 2000;

let srIn = 44100;
let ring = new Float32Array(TARGET_SR * WINDOW_SEC);
let ringFill = 0;
let frozen = false;
let lastRms = 0, silentMs = 0, silenceResetDone = false;

const state = {
  bpm: 0, bpmConf: 0, key: "", scale: "", keyConf: 0, rms: 0,
  chunks: 0, lastChunkSize: 0, totalSamples: 0,
  firstChunkAt: 0, lastChunkAt: 0, measuredSr: 0, srLocked: false,
  workerBusy: false, votes: [], log: []
};
let outFn = null;

function log(msg) {
  state.log.push(`${new Date().toISOString()} ${msg}`);
  if (state.log.length > 50) state.log.shift();
}
function out(...args) {
  const [head, ...rest] = args;
  if (head === 'bpm') { state.bpm = rest[0]; state.bpmConf = rest[1]; }
  if (head === 'key') { state.key = rest[0]; state.scale = rest[1]; state.keyConf = rest[2]; }
  if (head === 'status') log(rest.join(' '));
  if (outFn) outFn(...args);
  else if (maxApi) maxApi.outlet(...args);
  else console.log(...args);
}

// ---- 解析ワーカー ----
let worker = null;
if (maxApi) {
  // execArgv を空にして Node for Max のプリロード（process.send 前提）が worker に継承されるのを防ぐ
  // 優先順: 開発ソース → バンドルファイル → 埋め込みコード（凍結版: build-frozen.js が WORKER_SRC を先頭に注入）
  const fsx = require('fs');
  const wSrc = path.join(__dirname, 'analysis-worker.js');
  const wBundle = path.join(__dirname, 'analysis-worker.bundle.js');
  if (fsx.existsSync(wSrc)) worker = new Worker(wSrc, { execArgv: [] });
  else if (fsx.existsSync(wBundle)) worker = new Worker(wBundle, { execArgv: [] });
  else if (typeof globalThis.WORKER_SRC === 'string') worker = new Worker(globalThis.WORKER_SRC, { eval: true, execArgv: [] });
  else throw new Error('analysis worker source not found');
  worker.on('message', (m) => {
    if (m.type === 'worker_ready') { out('status', 'ready', m.version); return; }
    state.workerBusy = false;
    if (m.error) { out('status', 'error', m.error); return; }
    if (m.bpm) out('bpm', ...m.bpm);
    if (m.key) out('key', ...m.key);
    if (m.chroma) out('chroma', ...m.chroma);
    if (m.votes) state.votes = m.votes;
    if (m.bpmDbg) log('bpm_dbg ' + m.bpmDbg);
  });
  worker.on('error', (e) => { state.workerBusy = false; out('status', 'error', 'worker: ' + e.message); });
  worker.on('exit', (code) => { state.workerBusy = false; worker = null; out('status', 'error', 'worker exited code=' + code); });
}

// ---- SR 実測（5秒スライディング窓 × 連続2回一致でスナップ、以後ロック） ----
let winT0 = 0, winSamples0 = 0;
let lastEstStd = 0;
function updateSrMeasure(now) {
  if (!winT0) { winT0 = now; winSamples0 = state.totalSamples; return; }
  const dt = (now - winT0) / 1000;
  if (dt < 5) return;
  const est = (state.totalSamples - winSamples0) / dt;
  state.measuredSr = Math.round(est);
  winT0 = now; winSamples0 = state.totalSamples;
  if (state.srLocked) return;
  const std = [44100, 48000, 88200, 96000].find(s => Math.abs(est - s) / s < 0.025);
  if (std && std === lastEstStd) {
    if (std !== srIn) {
      srIn = std;
      rsInit = false; rsPos = 0;
      out('status', 'sr_corrected', String(std));
    }
    state.srLocked = true; // 一度確定したら以後は変更しない（解析負荷等での誤補正防止）
    out('status', 'sr_locked', String(std));
  }
  lastEstStd = std || 0;
}

// ---- 位相連続リサンプラ ----
let rsPos = 0, rsLast = 0, rsInit = false;

function pushAudio(chunk) {
  const now = Date.now();
  state.chunks++;
  state.lastChunkSize = chunk.length;
  state.totalSamples += chunk.length;
  if (!state.firstChunkAt) state.firstChunkAt = now;
  state.lastChunkAt = now;
  updateSrMeasure(now);

  let data;
  if (srIn === TARGET_SR) {
    data = chunk;
  } else {
    const ratio = srIn / TARGET_SR;
    const src = new Float32Array(chunk.length + 1);
    src[0] = rsInit ? rsLast : chunk[0];
    src.set(chunk, 1);
    const outArr = [];
    let pos = rsInit ? rsPos : 1;
    while (pos <= src.length - 1 - 1e-9) {
      const i0 = Math.floor(pos), frac = pos - i0;
      outArr.push(src[i0] + (src[i0 + 1] - src[i0]) * frac);
      pos += ratio;
    }
    rsPos = pos - chunk.length;
    rsLast = chunk[chunk.length - 1];
    rsInit = true;
    data = Float32Array.from(outArr);
    if (data.length === 0) return;
  }

  const n = data.length;
  if (n >= ring.length) {
    ring.set(data.subarray(n - ring.length));
    ringFill = ring.length;
  } else {
    ring.copyWithin(0, n);
    ring.set(data, ring.length - n);
    ringFill = Math.min(ringFill + n, ring.length);
  }
  let sum = 0;
  for (let i = 0; i < n; i++) sum += data[i] * data[i];
  lastRms = Math.sqrt(sum / n);
  state.rms = lastRms;
  const chunkMs = (n / TARGET_SR) * 1000;
  if (lastRms < 0.001) {
    silentMs += chunkMs;
    if (silentMs > 2000 && !silenceResetDone) {
      silenceResetDone = true;
      resetState('silence');
    }
  } else {
    silentMs = 0;
    silenceResetDone = false;
  }
}

function resetState(reason) {
  if (ringFill === 0 && state.bpm === 0 && !state.key) return;
  ringFill = 0;
  state.bpm = 0; state.bpmConf = 0; state.key = ""; state.scale = ""; state.keyConf = 0;
  if (worker) worker.postMessage({ type: 'reset' });
  out('status', 'reset', reason || 'manual');
}

function requestAnalyze() {
  if (frozen || state.workerBusy || !worker) return;
  if (ringFill < TARGET_SR * 3) return;
  if (lastRms < 0.001) return;
  const seg = ring.slice(ring.length - ringFill); // コピー（transferでリングを失わないため）
  state.workerBusy = true;
  worker.postMessage({ type: 'analyze', buf: seg.buffer, sr: TARGET_SR }, [seg.buffer]);
}

// ---- 開発ブリッジ ----
let bridgeServer = null;
function startBridge(port) {
  if (bridgeServer) return;
  const http = require('http');
  bridgeServer = http.createServer((req, res) => {
    if (req.url === '/reset') {
      resetState('bridge');
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end('{"ok":true}');
    } else if (req.url === '/dump') {
      res.writeHead(200, { 'Content-Type': 'application/octet-stream' });
      res.end(Buffer.from(ring.buffer, ring.byteOffset, ring.length * 4));
    } else if (req.url === '/state') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ...state, srIn, ringFill, frozen }));
    } else {
      res.writeHead(404); res.end();
    }
  });
  bridgeServer.listen(port, '127.0.0.1', () => out('status', 'bridge', `listening 127.0.0.1:${port}`));
  bridgeServer.on('error', (e) => { out('status', 'error', 'bridge: ' + e.message); bridgeServer = null; });
}

if (maxApi) {
  maxApi.addHandler('audio', (...floats) => pushAudio(Float32Array.from(floats)));
  maxApi.addHandler('sr', (v) => { if (!state.srLocked) srIn = Number(v) || 44100; });
  maxApi.addHandler('reset', () => resetState('manual'));
  maxApi.addHandler('freeze', (v) => { frozen = !!Number(v); });
  maxApi.addHandler('smoothing', (v) => worker && worker.postMessage({ type: 'smoothing', value: Number(v) }));
  maxApi.addHandler('bpmswap', () => worker && worker.postMessage({ type: 'bpmswap' }));
  maxApi.addHandler('bridge', (port) => startBridge(Number(port) || 7401));
  setInterval(requestAnalyze, ANALYZE_INTERVAL_MS);
  startBridge(7401);
} else {
  // スタンドアロンテスト用（ワーカーなし・同期解析は旧テストが analysis-worker を直接使う）
  module.exports = { pushAudio, resetState, _setSr: v => (srIn = v), _setOut: fn => (outFn = fn), _state: state, _ring: () => ring.slice(ring.length - ringFill) };
}
