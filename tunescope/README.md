# TuneScope 繝・ヰ繧､繧ｹ 窶・Live 縺ｸ縺ｮ邨・∩霎ｼ縺ｿ謇矩・ｼ・0.1 繧ｹ繧ｱ繝ｫ繝医Φ・・

> **リポジトリ構成の注**: ビルド/評価/デバッグ用スクリプトは `tools/` 配下にあります。
> `npm run bundle` → `npm run release` で凍結 .amxd を生成（Max 不要、詳細は docs/05_amxd-format.md）。
> `tools/` のテスト・評価スクリプトは元々デバイスフォルダ直下で動作していたもので、相対パスは適宜読み替えてください。
> 正解データ（truth*.json）はユーザーのライブラリ由来のためリポジトリには含めていません（tools/extract-*.py で再生成）。
## 繝輔ぃ繧､繝ｫ讒区・
| 繝輔ぃ繧､繝ｫ | 蠖ｹ蜑ｲ |
|---|---|
| `TuneScope.maxpat` | 繝代ャ繝∵悽菴難ｼ磯浹螢ｰ繝ｫ繝ｼ繝・ぅ繝ｳ繧ｰ繝ｻnode.script繝ｻLive API 騾｣謳ｺ・・|
| `TuneScope_UI.js` | jsui 謠冗判繧ｹ繧ｯ繝ｪ繝励ヨ・・PM/Key/繧ｯ繝ｭ繝・FREEZE縲∥utowatch 蟇ｾ蠢懶ｼ・|
| `analyzer.js` | 髻ｳ螢ｰ蜿嶺ｿ｡繝ｻ繝ｪ繝ｳ繧ｰ邂｡逅・・SR螳滓ｸｬ繝ｻ髢狗匱繝悶Μ繝・ず・医Γ繧､繝ｳ繧ｹ繝ｬ繝・ラ縲・撼繝悶Ο繝・く繝ｳ繧ｰ・・|
| `analysis-worker.js` | essentia.js 隗｣譫舌Ρ繝ｼ繧ｫ繝ｼ・・orker_threads縲・PM+Key+繧ｯ繝ｭ繝槭ｒ2遘帝俣髫斐〒螳溯｡鯉ｼ・|
| `package.json` / `node_modules/` | essentia.js 萓晏ｭ假ｼ医う繝ｳ繧ｹ繝医・繝ｫ貂医∩・・|
| `test-m1.js` / `test-m2.js` | 讀懆ｨｼ繧ｹ繧ｯ繝ｪ繝励ヨ・・node test-m2.js` 縺ｧ蜊倅ｽ薙ユ繧ｹ繝亥庄・・|

## 邨・∩霎ｼ縺ｿ謇矩・ｼ・0.3 縺九ｉ閾ｪ蜍募喧・・**Max 縺ｧ縺ｮ繧ｳ繝斐・菴懈･ｭ縺ｯ荳崎ｦ√↓縺ｪ繧翫∪縺励◆縲・* `build-amxd.js` 縺・`.maxpat` 縺九ｉ `.amxd` 繧堤峩謗･逕滓・縺励・繝・ヰ繧､繧ｹ荳蠑上・ Ableton User Library 縺ｫ閾ｪ蜍暮・鄂ｮ縺輔ｌ縺ｾ縺・

```
User Library\Presets\Audio Effects\Max Audio Effect\TuneScope\TuneScope.amxd
```

**繝ｦ繝ｼ繧ｶ繝ｼ謫堺ｽ懊・1縺､縺縺・*: Live 縺ｮ繝悶Λ繧ｦ繧ｶ・・ser Library 竊・Presets 竊・Audio Effects 竊・Max Audio Effect 竊・TuneScope・・縺九ｉ `TuneScope.amxd` 繧偵ヨ繝ｩ繝・け縺ｸ繝峨Λ繝・げ縺吶ｋ縲ゆｻ･蠕後・譖ｴ譁ｰ繧ゅ，laude 縺後ン繝ｫ繝会ｼ・・鄂ｮ 竊・繝・ヰ繧､繧ｹ繧呈諺縺礼峩縺吶□縺代・
髢狗匱逕ｨ縺ｮ蜀阪ン繝ｫ繝・
```bash
node build-amxd.js
```
・・S 縺ｮ縺ｿ縺ｮ螟画峩縺ｪ繧牙・繝薙Ν繝我ｸ崎ｦ・窶・autowatch / node.script @watch 縺瑚・蜍輔Μ繝ｭ繝ｼ繝会ｼ・
## 蜍穂ｽ懃｢ｺ隱阪・謫堺ｽ懶ｼ・0.2・・- 繝医Λ繝・け縺ｫ髻ｳ貅舌ｒ豬√☆ 竊・謨ｰ遘貞ｾ後↓ BPM 縺ｨ Key 縺瑚｡ｨ遉ｺ縺輔ｌ繧・- **BPM 謨ｰ蛟､繧ｯ繝ｪ繝・け** = 繧ｹ繝繝ｼ繧ｸ繝ｳ繧ｰ蛻・崛・・=Fast/N=Normal/S=Stable縲∝承荳翫・譁・ｭ暦ｼ・- **陬懷勧陦・蟾ｦ・暗・/ﾃｷ2 陦ｨ遉ｺ・峨け繝ｪ繝・け** = 繝上・繝・繝繝悶Ν蛻・崛 ・・**蜿ｳ・遺・SET・峨け繝ｪ繝・け** = Live 繝・Φ繝昴∈蜿肴丐
- **Key 陦ｨ遉ｺ繧ｯ繝ｪ繝・け** = 陦ｨ險伜・譖ｿ・・amelot 竊・Open Key 竊・髻ｳ蜷搾ｼ・- **TAG・井ｸ区ｮｵ蟾ｦ・・* = 蜀咲函荳ｭ・医↑縺代ｌ縺ｰ驕ｸ謚樔ｸｭ・峨け繝ｪ繝・・蜷阪↓ `[8A 124] ` 繧剃ｻ倅ｸ趣ｼ域里蟄倥ち繧ｰ縺ｯ鄂ｮ謠幢ｼ・- **FREEZE・井ｸ区ｮｵ蜿ｳ・・* = 讀懷・繝ｭ繝・け ・・**繝繝悶Ν繧ｯ繝ｪ繝・け** = 繝ｪ繧ｻ繝・ヨ
- Notation / Smoothing 縺ｯ Live 繝代Λ繝｡繝ｼ繧ｿ縺ｨ縺励※菫晏ｭ倥＆繧後ｋ・・attr 豌ｸ邯壼喧・・- 繝・ヰ繝・げ: Max 繧ｳ繝ｳ繧ｽ繝ｼ繝ｫ縺ｧ node.script 縺ｫ `bridge 7401` 繧帝√ｋ縺ｨ `curl http://127.0.0.1:7401/state` 縺ｧ隗｣譫千憾諷九ｒ辣ｧ莨壼庄閭ｽ

## 繝吶Φ繝√・繝ｼ繧ｯ
`node test-m5.js` 窶・蜷域・10繧ｱ繝ｼ繧ｹ縺ｧ BPM 9/10・域ｮ・莉ｶ縺ｯ ﾃ・/ﾃｷ2 蛟呵｣懊↓豁｣隗｣縺ゅｊ・峨・Key 10/10

## 繝ｪ繝ｪ繝ｼ繧ｹ謇矩・ｼ・reeze Device・・1. 繝ｪ繝ｪ繝ｼ繧ｹ蜑阪↓ `analyzer.js` 縺ｮ繝・ヰ繝・げ讖溯・繧堤┌蜉ｹ蛹悶☆繧九°蛻､譁ｭ・・/dump`繝ｻ`bpm_dbg` 繝ｭ繧ｰ縲ゅヶ繝ｪ繝・ず閾ｪ菴薙・ 127.0.0.1 髯仙ｮ壹↑縺ｮ縺ｧ谿九＠縺ｦ繧ょｮ牙・・・2. Live 縺ｧ繝・ヰ繧､繧ｹ縺ｮ邱ｨ髮・・繧ｿ繝ｳ 竊・Max 繧ｨ繝・ぅ繧ｿ 竊・**File 竊・Freeze Device**・・S / node_modules 繧・.amxd 縺ｫ蜷梧｢ｱ・・3. `TuneScope_1.0.0.amxd` 縺ｨ縺励※菫晏ｭ・竊・驟榊ｸ・
## UI 髢狗匱・医Δ繝・け・・`ui-mock.html` 窶・mgraphics竊辰anvas 繧ｷ繝縺ｧ螳欟I繧ｳ繝ｼ繝峨ｒ繝悶Λ繧ｦ繧ｶ謠冗判・育憾諷句挨4繧ｷ繝翫Μ繧ｪ・峨・`python -m http.server 8765` 繧・device 繝輔か繝ｫ繝縺ｧ襍ｷ蜍輔＠ `http://127.0.0.1:8765/ui-mock.html` 繧帝幕縺上・Max 繧定ｵｷ蜍輔○縺壹↓ UI 縺ｮ隕九◆逶ｮ繧貞渚蠕ｩ遒ｺ隱阪〒縺阪ｋ縲・
## 譌｢遏･縺ｮ蛻ｶ邏・- 陦ｨ遉ｺ譖ｴ譁ｰ縺ｯ隗｣譫宣俣髫費ｼ・遘抵ｼ峨＃縺ｨ縲ゆｿ｡鬆ｼ蠎ｦ縺瑚ご縺､縺ｾ縺ｧ陦ｨ遉ｺ縺ｯ阮・＞・井ｻ墓ｧ・
- 逕滓・ amxd 縺ｯ髱槫㍾邨仙ｽ｢蠑上ょ酔繝輔か繝ｫ繝縺ｮ JS / node_modules 縺ｫ萓晏ｭ倥☆繧九◆繧√・*繝輔か繝ｫ繝縺斐→**遘ｻ蜍輔☆繧九％縺ｨ
- 莉也腸蠅・∈縺ｮ驟榊ｸ・凾縺ｯ File 竊・Freeze Device 縺ｧ node_modules 縺斐→蜃咲ｵ舌☆繧九％縺ｨ
