# 02. 仕様書 v0.1 — BPM & Key 自動検出デバイス（仮称: TuneScope）

## 1. 概要

トラックに挿すだけで、流れているオーディオの **BPM** と **Key（調）** をリアルタイム解析して表示する Max for Live オーディオエフェクトデバイス。音声はパススルー（非破壊・レイテンシ0）。

- 対象: DJ / プロデューサーがサンプル・レコード・外部入力の曲情報を即座に知るユースケース
- 参考: LIVE KEY (@sidebrain) の機能セット、Sc0pe v2 の設計思想

## 2. 機能要件

### 2.1 BPM 検出
| 項目 | 仕様 |
|---|---|
| 検出範囲 | 60–200 BPM（半分/倍テンポの曖昧性はオクターブ補正で解決） |
| 更新間隔 | 2秒ごとに再推定、指数平滑で表示安定化 |
| 表示 | 小数1桁（例 `124.0`）+ 信頼度インジケータ |
| 補助機能 | Live のセットテンポとの差分表示（`+2.3` 等）／ワンクリックで Live テンポへ反映（live.object 経由） |

### 2.2 Key 検出
| 項目 | 仕様 |
|---|---|
| 出力 | 音名 + スケール（例 `A minor`）、**Camelot 表記併記**（例 `8A`）、Open Key 表記（オプション） |
| 更新 | 4秒窓の累積クロマで推定、確定までは candidate 表示（薄色） |
| 信頼度 | 1位と2位のスコア差から算出、バー表示 |
| 補助表示 | 12音クロマグラム（現在の音の強度分布）、relative / 隣接 Camelot キーのヒント |

### 2.3 共通
- リセット: 表示部ダブルクリックで解析履歴クリア（Sc0pe 踏襲）
- 解析対象曲が変わったことの検出（無音 >2秒 で自動リセット）
- Freeze ボタン: 検出結果をロック
- （Phase 2）選択クリップ名への `[8A 124]` 自動付与 — LIVE KEY のクリップリネーム相当。live.path/live.object で実装

## 3. 非機能要件
- CPU 負荷: 1コアの 5% 以下目標（解析は node.script 側・低優先度で実行）
- 音声パス: plugin~ → plugout~ 直結（解析は分岐のみ、DSP チェーンに影響なし）
- デバイス幅: 約130px（折りたたみ時）。Sc0pe v2 同等のコンパクト設計
- Live 12 / Max 9 / Windows・macOS 両対応（essentia.js は WASM なので OS 非依存）

## 4. アーキテクチャ

```
plugin~ ─┬─ plugout~                      （音声パススルー）
         └─ ダウンサンプル(22.05k) ─ jit.catch~/バッファ ─ node.script analyzer.js
                                                              │  essentia.js:
                                                              │  ─ RhythmExtractor2013 → BPM
                                                              │  ─ HPCP + KeyExtractor → Key
                                                              ▼
             live.observer(tempo) ──────────────► jsui (BPMKey_UI.js) ← dict/message
```

- **解析層**: node.script（essentia.js WASM）。4秒リングバッファに対し 2秒ごとに解析ジョブ実行
- **UI 層**: jsui 1枚 + 外部 JS（mgraphics 描画）。全データは `prepend <name>` 形式のメッセージで流し込む（Sc0pe 方式）
- **Live 連携**: live.thisdevice → live.path → live.observer(tempo) / live.object（テンポ設定・クリップリネーム）

## 5. パラメータ（pattr 永続化）
| 名前 | 型 | 初期値 | 説明 |
|---|---|---|---|
| Key Notation | enum | Camelot | Camelot / Open Key / 音名のみ |
| Smoothing | enum | Normal | Fast / Normal / Stable |
| BPM Range | enum | 60–200 | Half/Double 補正の基準域 |
| Freeze | toggle | off | 検出値ロック |

## 6. マイルストーン
1. **M1**: node.script + essentia.js でオフライン解析が動く（コンソール出力）
2. **M2**: 音声リングバッファ→リアルタイム解析→メッセージ出力
3. **M3**: jsui UI（BPM/Key/信頼度/クロマ）
4. **M4**: Live 連携（テンポ差分・テンポ反映）・pattr・Freeze
5. **M5**: 精度チューニング（テスト音源で正解率測定）→ 凍結・リリース
