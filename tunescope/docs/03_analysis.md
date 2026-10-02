# 03. 解析プロセス・メソッドの検討（BPM / Key 検出）

英語圏の MIR（Music Information Retrieval）研究・実装のリサーチ結果に基づく比較と採用方針。

## 1. 手法比較

### BPM 検出
| 手法 | 実装先 | 精度 | リアルタイム性 | 判定 |
|---|---|---|---|---|
| **essentia RhythmExtractor2013 (multifeature)** | node.script + essentia.js (WASM) | ◎ MIREX 上位級。ビート位置・信頼度も出力 | △ 2–4秒のバッファ解析（本用途には十分） | **採用** |
| Max ネイティブ（onset 検出 + 自己相関） | MSP パッチ / gen~ | △ EDM 系は良好、生演奏に弱い | ◎ | フォールバック候補 |
| BeatSeeker 方式（適応ビートトラッキング） | Ableton 公式 Pack | ○ ドラム追従特化 | ◎ | 参考実装（目的が異なる） |
| aubio (aubiojs) | node.script | ○ | ○ | essentia が優位のため不採用 |

### Key 検出
| 手法 | 実装先 | 精度 | 判定 |
|---|---|---|---|
| **HPCP クロマ + KeyExtractor（プロファイル照合）** | essentia.js | ◎ プロファイル切替可（temperley / krumhansl / edma = EDM 向け） | **採用** |
| fzero~ / retune~ ピッチ→ヒストグラム | Max ネイティブ | △ 単旋律向き。和音・ミックス済み音源に弱い（Sc0pe の Tuner はこれ） | 不採用 |
| CNN ベース key 推定（essentia-tensorflow 等） | ブラウザ/Python | ◎ | WASM 化未整備・重量級のため見送り |

## 2. 採用パイプライン詳細

### 前処理
1. ステレオ→モノ合算、22.05 kHz へダウンサンプル（解析負荷 1/2、Key/BPM に十分な帯域）
2. 4秒リングバッファ（約 88,200 サンプル）を node.script へ転送（2秒ごと・50% オーバーラップ）

### BPM: RhythmExtractor2013
- `method: multifeature`（精度優先。軽量版は `degara`）
- 出力: bpm / ticks / confidence（0–5.32、3.5 以上で高信頼）
- **オクターブ補正**: 推定値が設定レンジ外なら ×2 / ÷2。ハーフタイム楽曲対策として 2:1 近傍の第2候補も保持
- **平滑化**: 中央値フィルタ（直近5推定）→ 信頼度加重の指数平滑。ジャンプは信頼度が高い時のみ許可

### Key: HPCP → KeyExtractor
- フレーム: 4096 FFT / hop 2048、スペクトルピーク→ HPCP（36bin → 12bin 集約）
- プロファイル: デフォルト `edma`（electronic dance music 向け、DJ ユースに最適）、オプションで `temperley`（汎用ポップス）
- **累積戦略**: 曲単位で HPCP を累積平均し推定を安定化（LIVE KEY が「extreme cases をテスト中」と述べている難所はここ。転調・ルバート・ベースだけのイントロ等）
- 信頼度 = 1位/2位スコア比。低信頼時は表示を candidate 扱いにし、誤確定を防ぐ

### 精度を高める追加策（Phase 2 以降）
- **ジャンル適応**: 打楽器成分（percussive ratio）を見て BPM の half/double 判断に反映
- **HPSS**（Harmonic/Percussive 分離）で Key はハーモニック成分のみ、BPM はパーカッシブ成分のみに適用 — essentia.js に HPSS 相当が無ければ median-filtering 法を自前実装
- **無音・曲変化検出**: RMS ゲート + クロマ相関の急落で解析履歴を自動リセット
- **検証**: GiantSteps Key / Tempo データセット（EDM 向けベンチマーク、無償公開）から数十曲でオフライン正解率を測定してからチューニング

## 3. リスクと対策
| リスク | 対策 |
|---|---|
| essentia.js WASM の Node for Max 上での動作（メモリ制限） | M1 マイルストーンで最初に検証。NG なら aubiojs / Meyda + 自前 Key 照合に切替 |
| node.script の転送オーバーヘッド | Float32Array を Dict 経由でなく `node.script` の raw message で送る。頻度は 0.5 Hz なので実質問題なし |
| リアルタイム制約 | 解析はワーカー的に非同期実行。UI 更新は deferlow（Sc0pe と同じ低優先パターン） |

## 4. チューニング結果（2026-09-30 実装済み）

合成ベンチマーク10ケース（10キー×テンポ70-174、スウィング/ハーフタイム/ノイズ込み）で **BPM 9/10・Key 10/10**。

実装した精度向上策:
1. **tick列の線形回帰**（外れ間隔除去＋取りこぼし拍補間付き最小二乗）— multifeature の bpm 出力にあった ±2% の系統誤差を解消（120→117.5 だったものが 120.0 ちょうどに）
2. **degara法クロスチェック** — 付点/3連グリッド誤認を補正（174 BPM を 117 と誤検出していたケースを解消）
3. **×2/÷2 代替候補の常時併出** — ハーフ/ダブルの本質的曖昧性（70↔140等）はアルゴリズムで断定せず、UI に第2候補を表示してワンクリック切替（`bpmswap`）

## 5. 実機E2Eデバッグで得た知見（2026-09-30、Live 12実機で全PASS到達）

| 問題 | 原因 | 対策 |
|---|---|---|
| 音声が実時間の3%しか届かない | `jit.spill` の listlength 既定値は **256** | `@listlength` 明示 |
| mode 3で320サンプル固定 | jit.catch~ mode 3 は**オシロスコープトリガーモード**（閾値なし→mode 2相当・framesize既定320） | **mode 0**（前回出力以降の全データ、欠落・重複なし）+ qmetro 25ms。内部バッファは100msなのでbang間隔<100ms必須 |
| BPM/Keyが約6%低くズレる | **adstatus sr が M4L 内で 44100 を誤申告**（Live実動作は48kHz） | チャンク実測レート（5秒窓×連続2回一致）でSRを自己判定しロック |
| BPMが不安定（±5%） | ①チャンク毎リサンプルの位相リセットで毎秒40回の微小クリック ②essentia解析(700ms)がnodeスレッドをブロックし音声メッセージが欠落 | ①位相連続リサンプラ ②解析を **worker_threads** に分離（`execArgv: []` 必須 — Node for Max のプリロードが worker に継承されると `process.send` でクラッシュ） |
| reset silence がログ洪水 | リセット後もチャンク受信でringFillが復活し毎チャンク再発火 | 無音期間につき1回のみのフラグ制御 |

最終E2E結果（AbletonMCP経由でクリップ自動生成・再生して検証）: 4分打ち→**BPM 120.0**、Am旋律+コード→**BPM 119.1 / A minor (conf 0.93)**。

## 6. 実音源ベンチマーク（2026-09-30、Core Library正解ラベル付きループ10種・AbletonMCPで全自動実行）

**BPM: 厳密一致 7/10 ＋ オクターブ候補（UIワンクリック切替）で救済 2/10 ＝ 実用 9/10**
- 真の失敗は DnB ブレイク（174→116、2/3グリッド誤認）の1件のみ
- 84/140 の低速・シンセ系は ×2/÷2 曖昧性（設計どおり alt 候補に正解あり）

**Key: 厳密一致 2/5（ただし内訳に注意）**
| ケース | 判定 | 分析 |
|---|---|---|
| Bmin / Amin | 正解 | — |
| B♭Maj → Gmin | 相対調（**Camelot同番号** 6B↔6A、ミックス互換） | 生ファイルではtemperleyのみ正解、ワープ再生音では全プロファイルがGmin。第2候補として併記する設計で対応 |
| Fmin → Cmin | 属調隣接（Camelot 4A→5A） | 7プロファイル全会一致でCmin＝essentia系の構造的挙動。既知の限界として文書化 |
| Dm → Cmin | **ラベル自体が疑わしい**（7プロファイル全てCm/CMaj、3.4秒の短尺） | ベンチから除外相当 |

対応した改善: ①ブリッジ `/reset`（曲替わり時の状態クリア） ②edma+temperley 2プロファイル投票＋相対調ペアはtemperley累積票で決着 ③僅差第2候補のUI併記（`? 6B` 表示）。
**注**: ワープ再生はビートスライスで音色が変わるため、本ベンチのKey精度は下限値。通常再生の実曲ではより高い見込み。

## 7. 実曲チューニング（2026-10-01、rekordbox解析値107曲を正解ラベルとしたグリッド実験）

正解: rekordboxプレイリスト `tracck_data`（master.db をSQLCipher復号して直接取得）。
評価: ffmpegデコード→曲の20/35/50/65/80%の8秒窓×5→本番 analysis-worker を実行（デバイスと同一コード）。

### 実験結果と採用構成
| 項目 | 構成 | 厳密一致 | 実用(候補込み) |
|---|---|---|---|
| BPM 旧 | tick+degara | 56.1% | 84.1% |
| BPM 旧-tick / 旧-degara / mf単体 | | 54.2 / 52.3 / 51.4% | — |
| **BPM 新** | + **オンセット密度オクターブ補正**（検出<105 かつ onsetRate>2.5個/拍 → ×2側を主候補） | **66.4%** | 82.2% |
| Key 旧 | edma+temperley | 49.5% | 71.0% |
| Key temperley単独 / bgate+t / shaath+t / edmm単独 | | 44.9 / 49.5 / 47.7 / 39.3% | — |
| **Key 新** | **edmm+temperley**（edmm=マイナー重み付け。同主調混同を解消。相対調決着はtemperley累積票＝従来どおり） | **57.9%** | **80.4%** |

対初期実装（3窓・edma+temperley・補正なし）比: BPM 51→66%、Key 46→58%、DJ互換 63→80%。

### 残る誤りの内訳（素材特性）
- BPM: ハーフ/3連段の曖昧 17件（×2/÷2候補に正解あり→UIワンクリック）、残NGはブレイクコアの変則グリッド・可変テンポ
- Key: 相対調14件（Camelot同番号＝ミックス互換）・隣接10件。rekordbox自体の判定と原理的に揺れる領域

### 再評価の手順（曲を追加したら）
1. rekordboxで `tracck_data` に曲を追加 → `python extract-truth.py`
2. `node build-cache.js 0 999` → `node variant-eval.js final`

## 8. 拡張評価（2026-10-01、ライブラリ全体160曲・ホールドアウト法）

サンプルを rekordbox ライブラリ全体に拡張（ローカル解析済み160曲が上限。クラウド同期233曲はファイル非所持で対象外）。
`tracck_data` 107曲＝チューニング用、残り53曲＝**ホールドアウト（過適合検証用）**。

### 結果
| セット | BPM厳密 | BPM実用 | Key厳密 | Key DJ互換 |
|---|---|---|---|---|
| tune 107（最難: ブレイクコア偏重） | 67.3% | 82.2% | 57.9% | 80.4% |
| **holdout 48（未知データ）** | **81.3%** | **91.7%** | **64.6%** | 72.9% |
| **全155曲** | **71.6%** | **85.2%** | **60.0%** | **78.1%** |

- §7の改善（edmm+temperley・オンセット補正）は**ホールドアウトでも有効＝過適合なし**を確認
- グリッド15点: octRatio **2.5→2.2** に更新（tune +0.9pt、holdout劣化なし）。octCutoff は100-115で不感→105維持
- BPM上限215は効果なし→200維持
- 評価セットの注意: SETF=all 時の自己参照バグを修正済み（variant-eval.js）

## 主要ソース
- [RhythmExtractor2013 — Essentia docs](https://essentia.upf.edu/reference/std_RhythmExtractor.html)
- [KeyExtractor — Essentia docs](https://essentia.upf.edu/reference/std_KeyExtractor.html)
- [essentia.js API](https://mtg.github.io/essentia.js/docs/api/Essentia.html) / [ISMIR 2020 論文](https://program.ismir2020.net/static/final_papers/260.pdf)
- [BeatSeeker — Ableton](https://www.ableton.com/en/packs/beatseeker/)
