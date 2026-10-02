# TuneScope

流れている音声の **BPM** と **Key（調）** をリアルタイムに検出する Max for Live オーディオエフェクトです。
Key は Camelot / Open Key / 音名で表示でき、検出値を Live のテンポへ反映したり、クリップ名にタグとして書き込んだりできます。

*A Max for Live audio effect that detects the BPM and musical key of whatever is playing, in real time.
Shows Camelot / Open Key / note names, syncs Live's tempo, and tags clip names. Drop it on an audio track.*

## ダウンロード

[Releases](https://github.com/utsumi123456/my-project/releases?q=tunescope) から最新の **`TuneScope_x.y.z.amxd`** をダウンロードしてください。
ファイル1つで完結しています（Max での追加インストールや Freeze は不要です）。

## 必要な環境

- Ableton Live 12 で Max for Live が使えること（Suite、または Standard + Max for Live）
- Windows で動作確認済み（Live 12.4.6 / Max 9）。macOS は未確認です（解析エンジンは WebAssembly なので動く見込み）

## インストール

1. ダウンロードした `.amxd` を、Live のオーディオトラック（またはマスター）にドラッグ＆ドロップします
2. 繰り返し使う場合は User Library の `Presets/Audio Effects/Max Audio Effect/` に置くと、ブラウザから呼び出せます

音声はそのまま通過します（音には一切影響しません）。

## 使い方

再生すると、数秒で BPM と Key が表示されます。信頼度が低いうちは表示が薄く、確度が上がると濃くなります。

| 操作 | 動作 |
|---|---|
| BPM の数値をクリック | 平滑化の切替：F（速い）/ N（標準）/ S（安定） |
| BPM 下の左側（`×2` / `÷2`）をクリック | 倍テンポ／半テンポの候補に切替 |
| BPM 下の右側（`→SET`）をクリック | 検出 BPM を Live のテンポに反映 |
| Key 表示をクリック | 表記の切替：Camelot → Open Key → 音名 |
| TAG | 再生中（なければ選択中）のクリップ名の先頭に `[8A 124] ` を付ける（既存のタグは置き換え） |
| FREEZE | 検出値を固定 |
| ダブルクリック | 解析履歴をリセット（曲を変えたとき） |

Key の右下に薄く `? 6B` のように出るのは、僅差の第2候補です（多くは相対調で、ハーモニックミックス上は同じ番号＝互換）。
表記と平滑化の設定は Live セットに保存されます。2秒以上無音が続くと、解析は自動でリセットされます。

## 精度

rekordbox の解析値を正解として、ローカルにある解析済みの全 160 曲で評価しました（デコード不可の 5 曲を除く 155 曲）。

| | 一致 | 候補を含めて一致 |
|---|---|---|
| BPM | 71.6%（±2.5 以内） | 85.2%（`×2`/`÷2` 候補で正解になるものを含む） |
| Key | 60.0%（完全一致） | 78.1%（相対調・Camelot 隣接を含む） |

チューニングに使っていない 48 曲（ホールドアウト）では BPM 81.3% / 91.7%、Key 64.6% でした。
評価方法と実験の全記録は [docs/03_analysis.md](docs/03_analysis.md) にあります。

## 既知の制約

- BPM の検出範囲は 60–200 です。200 を超える曲は半分の値が出ます（`×2` 候補で対応）
- 曲頭の疎なイントロ（キックだけ等）では半テンポ側が出やすく、曲が進むと更新されます
- ブレイクコアなど変則的なリズムや、テンポが変化する曲は苦手です
- 開発用の HTTP エンドポイントが `127.0.0.1:7401` で動いています（このPC内からのみ接続可能。解析状態の確認用）。2台目以降の TuneScope ではこのエンドポイントは起動しません

## ソースからビルドする

Max は不要です。Node.js 20 以上で、このディレクトリから実行します。

```bash
npm install
```

```bash
npm run release
```

`TuneScope_1.0.0.amxd` が生成されます。続けて内部構造の検証結果が表示されます。
凍結 `.amxd` の形式と、Max を使わずに生成している仕組みは [docs/05_amxd-format.md](docs/05_amxd-format.md) にまとめています。

## ディレクトリ構成

| パス | 内容 |
|---|---|
| `TuneScope.maxpat` | デバイス本体のパッチ |
| `TuneScope_UI.js` | 表示（jsui / mgraphics） |
| `analyzer.js` / `analysis-worker.js` | 解析エンジン（node.script ＋ essentia.js をワーカースレッドで実行） |
| `tagger.js` | クリップ名へのタグ書き込み（Live API） |
| `tools/` | 凍結ビルド、形式検証、ロード判定、精度評価、Live での E2E テストのスクリプト |
| `docs/` | 仕様書、解析手法と評価結果、デザイン方針、.amxd 形式の仕様 |
| `ui-mock.html` | Max なしで表示を確認するためのブラウザ用モック |

`tools/` の評価・テスト用スクリプトの一部は開発時にデバイスフォルダ直下で使っていたもので、パスは適宜読み替えてください。
精度評価に使った正解データ（`truth*.json`）は個人の楽曲ライブラリ由来のため含めていません。`tools/extract-*.py` で自分の rekordbox ライブラリから作れます。

## ライセンス

TuneScope は **GNU AGPL-3.0** です（[LICENSE](LICENSE)）。
解析エンジンに AGPL-3.0 の [essentia.js](https://github.com/MTG/essentia.js) を同梱しているため、配布物全体がこのライセンスになります。
リポジトリ内の他のプロジェクト（`set-agent/` など）はリポジトリ直下の MIT ライセンスのままです。
第三者ソフトウェアの表記は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
