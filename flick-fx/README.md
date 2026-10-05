# FlickFX

![status](https://img.shields.io/badge/status-prototype-blue)

ゲームパッドのスティックをピンボールのプランジャーのように「引いて離す」と、
左隣の FX の Dry/Wet が発射され、余韻を残して減衰する Max for Live オーディオエフェクト。

**成果物: `dist/FlickFX.amxd`（フリーズ済み 1 ファイル）** — FX の右にドロップするだけ。
Python・MIDI・常駐プロセス・環境設定は不要。コントローラーが繋がっていれば即動く（抜き差しも追従）。

```
[gamepad] (SDL2, Max 9 内蔵) ─> flickfx.js プランジャー物理 ─> live.remote~ ×3 ─> 左隣の FX
                                   │                              Dry/Wet / X:音色 / Y:長さ
                                   └─> flickfx_view.js 粒子アニメーション（デバイス画面）
```

## 使い方

FlickFX を 1 台トラックに置き、L / R それぞれのメニューで FX を選ぶ。FlickFX は自分の**右側**に
`[FlickFX] [FlickFX L · fx] [FlickFX R · fx] [FlickFX · Limiter]` を自動で挿入・差し替え・削除し、すべて折りたたんで表示する
（FX を切り替えても FlickFX の位置は動かない）。末尾の Limiter（Ceiling ≈ -1 dB）が連続発射のクリップを防ぐ。
L と R は同時に独立して動く。

FX は 2 種類のふるまいを持つ。

- **プランジャー型**（Reverb / Echo）: 引くとうっすら、はじくと発射して余韻が減衰。引いた方向で 2 つのパラメータを基準から曲げる。
  倒し切って**ぐるぐる回すとプランジャーを巻き上げ**、離した時の余韻が最大 +80 % 伸びる（画面ではバネがねじれ、ボールの周りに巻き数の螺旋）
- **ホールド型**（Grain Delay / Auto Filter / Phaser-Flanger / Redux）: **倒し切りがスイートスポット**。角度でパラメータが決まり、
  倒し切って**回すと回転速度に応じた効果**が乗る。はじくと FX 固有のジェスチャー。画面はすり鉢: 倒し切るとボールが縁に押し付けられて光り、
  回すと縁に光の尾が残り、遠心力で火花が飛ぶ

| FX | 型 | 倒し切り（角度） | 回す | はじく | 余韻ボタン |
|---|---|---|---|---|---|
| Reverb | プランジャー | うっすら（Preload） | 巻き上げ（余韻が伸びる） | 発射、HiShelf / Decay Time を方向で曲げる | Decay Time |
| Echo | プランジャー | うっすら | 巻き上げ | 発射、Reverb Level / Feedback を方向で曲げる | Feedback |
| Grain Delay | ホールド | ピッチが角度で ±7 st（緩やかなカーブ） | グレインが散る（Spray） | ピッチが跳ねて急降下（pew） | Feedback |
| Auto Filter | ホールド | 角度でカットオフ（下=暗い〜上=明るい、閉じ切らない） | 共振が上がりワウ | 共振つきで上から下へザップ | かかり時間のみ |
| Phaser-Flanger | ホールド | 角度でノッチ位置、Amount 100 % | ノッチが周回するジェット | ノッチが駆け上がるジェット | Feedback |
| Redux | ホールド | 傾き量でサンプルレート低下、上でビット落ち | サンプルレートが揺れる | bit drop（潰れて段階的に復帰） | CRUSH（潰す深さ） |

余韻ボタン: L = 十字キー ↑↓、R = Y(↑) / A(↓)。12 段階で、かかり時間（Decay L/R）も連動。値は FX 本体に書き込まれる。
Redux だけは「どれだけ潰すか（CRUSH）」を切り替え、値は Crush L/R ノブに保存される（画面は段が粗くなるサンプル&ホールド波形）。

**zoom**: 右上の zoom で拡大ウィンドウ（1100×344、デバイスと同じ縦横比）を開く。同じ描画をベクターのまま拡大し、FX 名もヘッダーに表示。

## ノブ（通常は畳まれている。右上の knobs で開閉）

Preload 15% / Launch 100% / Attack 30 ms / Hold 80 ms / Decay L・R 1.20 s / Weight 60% / Snap 100 ms / Spread 30% / Crush L・R 73%。
すべて Live のパラメータ（保存・オートメーション・MIDI マップ可）。FX L / FX R のメニューも同様。

## ビルド

```
python m4l/build.py          # dist/FlickFX.amxd を生成し User Library にコピー
python m4l/build.py --dev    # 非フリーズ版（m4l/ の .js を参照）
```

開発ループ（この PC 固有）: `python tools/dev_reload.py <track>` がビルド → Live の Current Project へコピー →
既存 FlickFX（本体を先に）と管理下の FX を削除 → 再ロードまで行う。`tools/watch_params.py` で掴んだパラメータの変化を監視。
どちらもローカル改変した AbletonMCP リモートスクリプト（`current_project` URI 探索 + `delete_device`）が前提。

## 検証

- `python tools/sim_plunger.py` — プランジャー物理のオフライン検証（PASS/FAIL）
- `FLICKFX_BENCH=1 python tools/dev_reload.py 1` — 計測ビルド。合成スティック操作（回転・保持・はじき、パッドイベント ~750/s）を流し、
  5 秒ごとにフレーム間隔を Live の Log.txt に出す（`FlickFX bench` / `FlickFX bench [zoom]`）。本番ビルドには含まれない
- 描画: 動かない層（背景・枠・点群の下地・ラベル）は 2 倍解像度のオフスクリーン画像にキャッシュし、毎フレームは動く要素だけ描く。
  zoom を開いている間はデバイス内ビューの描画を止める

## 状態

2026-10-05 プロトタイプ完成（ユーザー判断）。デザインは Dillon Bastan「Coalescence」の流儀（黒い場・細枠・円形の点群・サーモンのリング・ミントのノード）。

## 旧プロトタイプ

`flick_fx.py`（Python で XInput を読み UDP/MIDI 送信）と `tools/sim_plunger.py` は物理モデル検証用に残している。
