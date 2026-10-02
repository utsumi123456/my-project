// 凍結（Freeze Device 相当）amxd を自前生成する
// 形式（Sc0pe_2.0.0.amxd のリバースエンジニアリングによる）:
//   ampf[4]"aaaa" | meta[4]u32le(7) | ptch[sizeLE]( mx@c16Bヘッダ + JSON + 依存ファイル連結 + dlstフッター )
//   dlst(u32be size) > dire ごとに type/fnam/sz32/of32/vers/flag/mdat（各 4cc + u32be size(ヘッダ込) + payload）
//   of32 は ptch データ先頭からのオフセット。fnam は NUL終端+4バイト境界パディング。
//   mdat は HFS 時刻（unix + 2082844800）。JSON エントリのみ flag=0x11。
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2] || 'TuneScope_1.0.0.amxd';
const DEVNAME = path.basename(OUT);

// 凍結に含める依存。node.script 用スクリプトは flag 0x8 必須（Producer Pal 解析で判明）。
// analyzer.js はワーカーバンドルを文字列として先頭に埋め込んだ単一ファイルに合成する
// （凍結展開では node スクリプト以外のファイル配置が保証されないため、Worker は eval 起動）。
const workerBundle = fs.readFileSync('analysis-worker.bundle.js', 'utf8');
const analyzerSrc = fs.readFileSync('analyzer.js', 'utf8');
const analyzerFrozen = 'globalThis.WORKER_SRC = ' + JSON.stringify(workerBundle) + ';\n' + analyzerSrc;
const DEPS = [
  { name: 'TuneScope_UI.js', data: fs.readFileSync('TuneScope_UI.js'), flag: 0 },
  { name: 'analyzer.js', data: Buffer.from(analyzerFrozen, 'utf8'), flag: 0x8 },
  { name: 'tagger.js', data: fs.readFileSync('tagger.js'), flag: 0 },
  // AGPL-3.0（essentia.js 同梱）の条件として、ライセンス文と第三者表記を配布物に含める
  { name: 'LICENSE', data: fs.readFileSync('LICENSE'), flag: 0 },
  { name: 'THIRD_PARTY_NOTICES.md', data: fs.readFileSync('THIRD_PARTY_NOTICES.md'), flag: 0 },
];

const patch = JSON.parse(fs.readFileSync('TuneScope.maxpat', 'utf8'));
const p = patch.patcher;
p.openinpresentation = 1;
// 凍結デバイスの appversion / project 日付は実在値が必要な疑い（Sc0pe 準拠に合わせる）
p.appversion = { major: 9, minor: 1, revision: 5, architecture: 'x64', modernui: 1 };
const hfsDate = Math.floor(Date.now() / 1000) + 2082844800;
if (!p.project) {
  p.project = {
    version: 1, creationdate: hfsDate, modificationdate: hfsDate,
    viewrect: [0.0, 0.0, 300.0, 500.0], autoorganize: 1, hideprojectwindow: 1,
    showdependencies: 1, autolocalize: 0, contents: { patchers: {} }, layout: {},
    searchpath: {}, detailsvisible: 0, amxdtype: 1633771873, readonly: 0,
    devpathtype: 0, devpath: '.', sortmode: 0, viewmode: 0, includepackages: 0
  };
}
const jsonBuf = Buffer.from(JSON.stringify(patch, null, 4) + '\n\0', 'utf8'); // NUL終端込み（Sc0pe準拠、sz32に含む）

const be32 = (v) => { const b = Buffer.alloc(4); b.writeUInt32BE(v >>> 0); return b; };
const chunkBE = (tag, payload) => Buffer.concat([Buffer.from(tag, 'ascii'), be32(payload.length + 8), payload]);
const fnamBuf = (name) => {
  const n = Buffer.from(name, 'utf8');
  const padded = Buffer.alloc(Math.ceil((n.length + 1) / 4) * 4); // NUL終端 + 4バイト境界
  n.copy(padded);
  return padded;
};
const hfsNow = () => Math.floor(Date.now() / 1000) + 2082844800;

function direEntry(type, name, size, offset, flag) {
  const payload = Buffer.concat([
    chunkBE('type', Buffer.from(type, 'ascii')),
    chunkBE('fnam', fnamBuf(name)),
    chunkBE('sz32', be32(size)),
    chunkBE('of32', be32(offset)),
    chunkBE('vers', be32(0)),
    chunkBE('flag', be32(flag)),
    chunkBE('mdat', be32(hfsNow())),
  ]);
  return chunkBE('dire', payload);
}

// mx@c サブヘッダ: 'mx@c' + u32be(ヘッダ長16) + u32be(0) + u32be(dlstオフセット: ptch先頭基準)
// ※最後の4バイトは Sc0pe では 0x00026774 で、偶然 ASCII の "..gt" に見えるが実体は dlst 位置。
//   これを定数と誤解すると「error -1 making directory / Device file broken」になる（実機で確認済み）。
const entries = [direEntry('JSON', DEVNAME, jsonBuf.length, 16, 0x11)];
const parts = [jsonBuf];
let offset = 16 + jsonBuf.length;
for (const dep of DEPS) {
  parts.push(dep.data);
  entries.push(direEntry('TEXT', dep.name, dep.data.length, offset, dep.flag));
  offset += dep.data.length;
}
const dlstOff = offset; // = 16 + 全ファイル長
const mxc = Buffer.concat([
  Buffer.from('mx@c', 'ascii'),
  be32(16),
  be32(0),
  be32(dlstOff),
]);
const ptch = Buffer.concat([mxc, ...parts, chunkBE('dlst', Buffer.concat(entries))]);

const le32 = (v) => { const b = Buffer.alloc(4); b.writeUInt32LE(v >>> 0); return b; };
const out = Buffer.concat([
  Buffer.from('ampf', 'ascii'), le32(4), Buffer.from('aaaa', 'ascii'),
  Buffer.from('meta', 'ascii'), le32(4), le32(7),
  Buffer.from('ptch', 'ascii'), le32(ptch.length), ptch,
]);
fs.writeFileSync(OUT, out);
console.log(`frozen ${OUT}: ${out.length} bytes (json ${jsonBuf.length}, deps: ${DEPS.map(d => d.name + '=' + d.data.length + (d.flag ? '/flag0x' + d.flag.toString(16) : '')).join(', ')})`);
