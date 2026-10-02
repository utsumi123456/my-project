// TuneScope.maxpat → TuneScope.amxd 自動ビルド
// amxd 非凍結形式: "ampf"+size4+"aaaa" | "meta"+size4+u32 | "ptch"+size(LE) + JSON + NUL
// （Max 9 同梱 fourin_fourout.amxd の構造に準拠。meta=7 は Max9 製オーディオエフェクトの実例値）
const fs = require('fs');

const src = process.argv[2] || 'TuneScope.maxpat';
const dst = process.argv[3] || 'TuneScope.amxd';

const patch = JSON.parse(fs.readFileSync(src, 'utf8')); // 構文検証を兼ねる

// M4L 必須のデバイスメタを patcher 直下に保証
const p = patch.patcher;
p.openinpresentation = 1;
if (!p.project) {
  p.project = {
    version: 1,
    creationdate: 0,
    modificationdate: 0,
    viewrect: [0.0, 0.0, 300.0, 500.0],
    autoorganize: 1,
    hideprojectwindow: 1,
    showdependencies: 1,
    autolocalize: 0,
    contents: { patchers: {} },
    layout: {},
    searchpath: {},
    detailsvisible: 0,
    amxdtype: 1633771873, // 'aaaa' = audio effect
    readonly: 0,
    devpathtype: 0,
    devpath: '.',
    sortmode: 0,
    viewmode: 0,
    includepackages: 0
  };
}

const json = Buffer.from(JSON.stringify(patch, null, 4) + '\n', 'utf8');
const body = Buffer.concat([json, Buffer.from([0])]);

function chunk(id, data) {
  const size = Buffer.alloc(4);
  size.writeUInt32LE(data.length);
  return Buffer.concat([Buffer.from(id, 'ascii'), size, data]);
}
const meta = Buffer.alloc(4);
meta.writeUInt32LE(7);

const out = Buffer.concat([
  chunk('ampf', Buffer.from('aaaa', 'ascii')),
  chunk('meta', meta),
  chunk('ptch', body)
]);
fs.writeFileSync(dst, out);
console.log(`built ${dst} (${out.length} bytes, json ${json.length})`);
