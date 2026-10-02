# TuneScope デバイス — Live への組み込み手順（v0.1 スケルトン）

> **リポジトリ構成の注**: ビルド/評価/デバッグ用スクリプトは `tools/` 配下にあります。
> `npm run bundle` → `npm run release` で凍結 .amxd を生成（Max 不要、詳細は docs/05_amxd-format.md）。
> `tools/` のテスト・評価スクリプトは元々デバイスフォルダ直下で動作していたもので、相対パスは適宜読み替えてください。
> 正解データ（truth*.json）はユーザーのライブラリ由来のためリポジトリには含めていません（tools/extract-*.py で再生成）。


## ファイル構成
| ファイル | 役割 |
|---|---|
| `TuneScope.maxpat` | パッチ本体（音声ルーティング・node.script・Live API 連携） |
| `TuneScope_UI.js` | jsui 描画スクリプト（BPM/Key/クロマ/FREEZE、autowatch 対応） |
| `analyzer.js` | 音声受信・リング管理・SR実測・開発ブリッジ（メインスレッド、非ブロッキング） |
| `analysis-worker.js` | essentia.js 解析ワーカー（worker_threads。BPM+Key+クロマを2秒間隔で実行） |
| `package.json` / `node_modules/` | essentia.js 依存（インストール済み） |
| `test-m1.js` / `test-m2.js` | 検証スクリプト（`node test-m2.js` で単体テスト可） |

## 組み込み手順（v0.3 から自動化）
**Max でのコピペ作業は不要になりました。** `build-amxd.js` が `.maxpat` から `.amxd` を直接生成し、
デバイス一式は Ableton User Library に自動配置されます:

```
User Library\Presets\Audio Effects\Max Audio Effect\TuneScope\TuneScope.amxd
```

**ユーザー操作は1つだけ**: Live のブラウザ（User Library → Presets → Audio Effects → Max Audio Effect → TuneScope）
から `TuneScope.amxd` をトラックへドラッグする。以後の更新も、Claude がビルド＆配置 → デバイスを挿し直すだけ。

開発用の再ビルド:
```bash
node build-amxd.js
```
（JS のみの変更なら再ビルド不要 — autowatch / node.script @watch が自動リロード）

## 動作確認・操作（v0.2）
- トラックに音源を流す → 数秒後に BPM と Key が表示される
- **BPM 数値クリック** = スムージング切替（F=Fast/N=Normal/S=Stable、右上の文字）
- **補助行 左（×2/÷2 表示）クリック** = ハーフ/ダブル切替 ／ **右（→SET）クリック** = Live テンポへ反映
- **Key 表示クリック** = 表記切替（Camelot → Open Key → 音名）
- **TAG（下段左）** = 再生中（なければ選択中）クリップ名に `[8A 124] ` を付与（既存タグは置換）
- **FREEZE（下段右）** = 検出ロック ／ **ダブルクリック** = リセット
- Notation / Smoothing は Live パラメータとして保存される（pattr 永続化）
- デバッグ: Max コンソールで node.script に `bridge 7401` を送ると `curl http://127.0.0.1:7401/state` で解析状態を照会可能

## ベンチマーク
`node test-m5.js` — 合成10ケースで BPM 9/10（残1件は ×2/÷2 候補に正解あり）・Key 10/10

## リリース手順（Freeze Device）
1. リリース前に `analyzer.js` のデバッグ機能を無効化するか判断（`/dump`・`bpm_dbg` ログ。ブリッジ自体は 127.0.0.1 限定なので残しても安全）
2. Live でデバイスの編集ボタン → Max エディタ → **File → Freeze Device**（JS / node_modules を .amxd に同梱）
3. `TuneScope_1.0.0.amxd` として保存 → 配布

## UI 開発（モック）
`ui-mock.html` — mgraphics→Canvas シムで実UIコードをブラウザ描画（状態別4シナリオ）。
`python -m http.server 8765` を device フォルダで起動し `http://127.0.0.1:8765/ui-mock.html` を開く。
Max を起動せずに UI の見た目を反復確認できる。

## 既知の制約
- 表示更新は解析間隔（2秒）ごと。信頼度が育つまで表示は薄い（仕様)
- 生成 amxd は非凍結形式。同フォルダの JS / node_modules に依存するため、**フォルダごと**移動すること
- 他環境への配布時は File → Freeze Device で node_modules ごと凍結すること
