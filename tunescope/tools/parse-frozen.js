// 凍結amxdのパーサ（自前ビルドの検証用）: コンテナ→dlst→各direを解読し、埋め込みファイルを照合
const fs = require('fs');
const b = fs.readFileSync(process.argv[2]);

function rd4(o) { return b.toString('ascii', o, o + 4); }
if (rd4(0) !== 'ampf') throw new Error('not amxd');
const metaVal = b.readUInt32LE(20);
const ptchSize = b.readUInt32LE(28);
console.log(`ampf ok, meta=${metaVal}, ptch size=${ptchSize} (file ${b.length})`);
const ptch = b.subarray(32, 32 + ptchSize);
console.log(`mx@c hdr: ${ptch.toString('ascii', 0, 4)} / fmt=${ptch.toString('ascii', 14, 16)}`);

// 末尾から dlst を探す（dlst サイズはヘッダ込み）
let dlstOff = -1;
for (let o = ptch.length - 8; o >= 0; o--) {
  if (ptch.toString('ascii', o, o + 4) === 'dlst' && o + ptch.readUInt32BE(o + 4) === ptch.length) { dlstOff = o; break; }
}
if (dlstOff < 0) throw new Error('dlst not found');
console.log(`dlst at ${dlstOff}, size ${ptch.readUInt32BE(dlstOff + 4)}`);

let o = dlstOff + 8;
const end = ptch.length;
while (o < end) {
  const tag = ptch.toString('ascii', o, o + 4);
  const size = ptch.readUInt32BE(o + 4);
  if (tag !== 'dire') { console.log(`  ?? ${tag}`); break; }
  let io = o + 8;
  const e = {};
  while (io < o + size) {
    const t = ptch.toString('ascii', io, io + 4);
    const s = ptch.readUInt32BE(io + 4);
    const pay = ptch.subarray(io + 8, io + s);
    if (t === 'type') e.type = pay.toString('ascii');
    if (t === 'fnam') e.name = pay.toString('utf8').replace(/\0+$/, '');
    if (t === 'sz32') e.size = pay.readUInt32BE(0);
    if (t === 'of32') e.offset = pay.readUInt32BE(0);
    if (t === 'flag') e.flag = pay.readUInt32BE(0);
    io += s;
  }
  // 埋め込み内容を元ファイルと照合
  const emb = ptch.subarray(e.offset, e.offset + e.size);
  let match = '';
  if (e.type === 'TEXT' && fs.existsSync(e.name)) {
    const orig = fs.readFileSync(e.name);
    if (e.flag === 0x8) {
      // node.script 用は「ワーカー埋め込み + 元ソース」に合成されているので末尾一致で確認
      const ok = emb.length >= orig.length && Buffer.compare(emb.subarray(emb.length - orig.length), orig) === 0;
      match = ok ? ' [元ソース+埋め込みワーカー✓]' : ' [内容不一致✗]';
    } else {
      match = Buffer.compare(emb, orig) === 0 ? ' [内容一致✓]' : ' [内容不一致✗]';
    }
  } else if (e.type === 'JSON') {
    try { JSON.parse(emb.toString('utf8').replace(/\0+$/, '')); match = ' [JSON解析✓]'; } catch (err) { match = ' [JSON破損✗]'; }
  }
  console.log(`  ${e.type} ${e.name}  size=${e.size} off=${e.offset} flag=0x${e.flag.toString(16)}${match}`);
  o += size;
}
console.log('parse OK');
