# Set Agent — 開発移行ハンドオフ（新 Claude アカウント向け）

最終更新: 2026-09-15 / 作成理由: Claude アカウント変更にともなうシームレスな開発継続。

> **新しいセッションはまずこの1ファイルを読め。** そのうえで `HANDOFF.md`（作業状態の
> 累積ログ）と、あれば `rekordbox_set_agent_spec.md`（仕様の正典 Part A〜F）を読む。
> このファイルは「今どこにいて、次に何を作るか」を最短で渡すためのもの。
>
> **2026-09-16 更新:** §9 の 1・2・3（情報階層の再設計 / ヒーロー差し替え / 準自動更新）と
> §11 の決定（自由配置パネル・1 枚スクロール・2 ビュー再編・git 導入）は完了。
> 詳細と次の一手は `HANDOFF.md` 冒頭の「2026-09-16 追記」を読め。

---

## 0. 30秒オリエンテーション

- **Set Agent** = DJ の rekordbox ライブラリを読み、**DJ セットの尺とエネルギー配置を
  設計する補助ツール**。rekordbox の master.db と ANLZ を直接読む。**master.db には絶対に
  書かない**（不変条件 B-2）。
- 現行プロトは Python + pywebview(WebView2) の単一ウィンドウ。動いていて、実機で検証済み、
  チームに配布 exe を渡す段階まで来ていた。
- **だが 2026-09-15、ユーザー（AlphaTheta の開発者）の実使用フィードバックで方針が大きく
  変わった。** 下の「1. 方針転換」が最重要。過去の実装の一部は破棄される。

---

## 1. 方針転換（最重要 / 2026-09-15 のユーザーフィードバック）

### 1-1. 書き出し（XML export）は死んだ。読み取り専用の分析ツールにする。
- 事実: 書き出し→rekordbox 取り込みは成功したが、**プレイリスト内が空**だった。
- 理由: **Set Agent は曲の追加・削除・並べ替えを一切していない。** だから書き出しても
  中身は元のプレイリストと同一 → 書き出す意味がない。
- 結論: このシステムに必要なのは「rekordbox のプレイリストを**読んで分析する**」こと。
  Set Agent 側は編集しない。編集はすべて rekordbox 側でユーザーが行う。
- **新ループ:** ユーザーが rekordbox でプレイリストを編集 → **Set Agent の分析が自動更新**
  される。Set Agent は read-only。これは B-2（master.db に書かない）と完全に整合する。

### 1-2. これに伴い破棄/凍結する実装
- `setagent/rekordbox/xml_export.py` 系の**書き出し機能** → コア動線から除去。
- 書き出し後の**取り込みガイド・モーダル** → 不要。
- **今セッションで新規追加した「rekordbox 再起動代行」** (`setagent/webui/rbrestart.py`,
  `api.restart_rekordbox`, settings の `rekordbox_exe`, index.html の再起動ボタン)
  → **これも不要になる。** 再起動代行は「書き出し→取り込み」動線を助けるために作った
  もので、その動線ごと消えるため。※コードは残してあるが新方針では使わない。惜しむな。
- 補足: 将来「レコメンドを Set Agent 側で適用してセットを組み替える」機能を作るなら
  書き出しは復活しうる。だが現方針は「レコメンドは提示だけ、編集は rekordbox で」なので
  当面 read-only で正しい。

---

## 2. 新しいプロダクト定義（これが次に作るもの）

**Set Agent = rekordbox の上にオーバーレイする、read-only のセット分析 & AI エージェント。**

ユーザーが本当に欲しい価値（初期構想に立ち返って再確認された3つ）:
1. **現在のプレイリスト楽曲で予想される「セット全体の尺」はどれくらいか。** ← 一番欲しい情報。
2. **目標の尺に足りない場合** → コレクション内から、プレイリストに合い、かつ残り尺を
   埋めるのに最適な曲を**レコメンド**する。
3. **目標の尺をオーバーする場合** → ENERGY のピーク/ボトムから、**外してよい曲を
   レコメンド**する。

適用は Set Agent がやらない。ユーザーが rekordbox で反映し、Set Agent は再分析するだけ。

### 2-1. ヒーロー指標の再設計（重要な UX 転換）
- 現行 UI は「**目標との差（+/-）**」を最重要情報として大きく出している。**これは誤り。**
- ユーザーが瞬間的に知りたいのは「**セット全体の予測時間（絶対値）**」。+/- は直感的でない。
- → 予測総尺を主役に。差分は副次情報。
- 目標時間の右にある「結論テキスト（verdict）」は**不要**。予測時間が確認できれば足りる。
  補足が要るなら「分析結果」セクションを別に設けてオンデマンド表示。冗長な助言や
  テキスト出力は**エージェント機能**に寄せる。

---

## 3. UI 設計方針（情報階層・オーバーレイ・色）

### 3-1. 情報量を絞る（デフォルト非表示 → オンデマンド）
- 初期段階より視認性は上がったが、まだ情報過多。
- **メイン UI に出すのは「ユーザーが本来知りたい情報」だけ**（＝予測総尺、目標との過不足の
  一言、レコメンドの入口）。
- **デフォルトで隠す**もの: ENERGY グラフ、その全体プレビュー（ミニマップ）、画面下部の
  警告、フレーズ解析の詳細。これらは「詳細/分析結果ページ」に移し、ユーザーが必要な時だけ開く。

### 3-2. 色を減らす
- 使用色が多く視認性を犠牲にしている。主因は**メイン UI に ENERGY グラフとフレーズ解析
  データを同居**させていること。
- → 詳細情報を別ページに逃がせば、メインの色数は自然に減る。フレーズ配色（6色）は詳細
  ページ側でだけ使う。

### 3-3. オーバーレイ前提の設計
- 実使用で判明: ユーザーは rekordbox と Set Agent を**交互に操作**する。ウィンドウ切替と
  視線移動がユーザビリティを落とす。→ **同一画面で操作できるのが理想。**
- rekordbox 内部の改造は不可能（過去の調査で確定）。→ **rekordbox の上にオーバーレイ**する
  方式を検討。frameless + always-on-top の細いパネルを rekordbox の脇/上にドッキング。
- ウィンドウ分割・常駐を前提にした視認性・レイアウトにする（狭い縦長でも成立するUI）。
- pywebview は frameless / on_top / 位置サイズ指定に対応。技術的には可能。

---

## 4. 確定した2つのワークフロー（設計の土台）

### 4-1. DJ の実使用フロー（rekordbox 中心）
1. DJ が rekordbox でプレイリストを組む
2. 組んだセットの尺、必要な曲・不要な曲を確認したくなる
3. Set Agent を開く
4. Set Agent の分析で、尺が超過か不足かを判断する
5. 必要に応じてセットの詳細分析を確認する
6. rekordbox でセットを編集する
7. 再度 Set Agent で編集後の尺を確認する（→ 4 に戻るループ）
8. セット確認完了。rekordbox の操作（USB エクスポート等）へ移る

→ 4↔6↔7 のループを**ウィンドウ切替なし**で回せることが UX の肝（=オーバーレイ）。

### 4-2. Set Agent を開いた時のフロー（Set Agent 内部）
1. Set Agent を開く
2. 分析するプレイリストを選択
3. セット全体で目指す尺を選択
4. mix のタイプを選択
5. mix の流れ（curve）を選択
6. Set Agent が分析
7. ユーザーは**自分が入力した条件**を確認できる（現状の入力サマリ）
8. 分析結果を見る（**楽曲のアートワークも表示できるのが理想** — 視認性向上）
9. rekordbox でプレイリストを編集（Set Agent 側フロー完了）

---

## 5. 技術的課題（新方針で最初に解くべきもの）

### 5-1. 自動更新（rekordbox の編集を Set Agent が拾う）— 最重要かつ最難関
- 望む挙動: rekordbox でプレイリストを編集 → Set Agent の分析が自動で更新。
- 既知の壁: **rekordbox 起動中は最新編集が `master.db-wal` に溜まり**、こちらのリーダーが
  マージしていない（`setagent/rekordbox/library.py` の `rekordbox_running()` /
  `pending_wal_bytes()` が既にこの状態を検出している）。しかも master.db は暗号化
  (SQLCipher) されており、復号して読む構造。
- 検討すべき方式（未決）:
  - (a) master.db と -wal の mtime/サイズを監視 → 変化時に再読込（ポーリング or watchdog）。
    ただし WAL 中の未コミット編集が見えるかは要検証。
  - (b) ウィンドウ再フォーカス時 / 手動更新ボタンで再読込（確実だが「自動」ではない）。
  - (c) rekordbox が WAL を master.db に書き戻す（チェックポイント）タイミングに依存する挙動を
    受け入れ、「rekordbox で保存/操作後に反映」と割り切る。
  - **まず (b)+ mtime 監視で「準自動」を成立させ、WAL 可視性を実測してから (a) を狙うのが安全。**
- 検証は「スクショで確かめる」をやめ、`window.evaluate_js()` と実データ照合で行う（HANDOFF の
  検証ドクトリン参照）。

### 5-2. アートワーク表示
- rekordbox の楽曲アートワークをどこから取るか（ANLZ / DB の画像パス / キャッシュ）を調査。
  分析結果の視認性向上に効く。ユーザーの明示要望。

### 5-3. オーバーレイ実装
- frameless + always-on-top の pywebview ウィンドウ。rekordbox ウィンドウの位置に追従させるか、
  ユーザーが好きに置くか。まずは「常駐する細いパネル」から。過去に S6 overlay（D3D12 直描画）は
  保留済み ── そこまでやらず、独立ウィンドウのドッキングで足りるか先に試す。

---

## 6. コード地図（残す資産 / いま何がどこにあるか）

リポジトリ: `C:\Users\7166700\source\setagent\setagent_new\`

**触るな系（不変ゾーン・分析ロジックの正典）:**
- `setagent/rekordbox/` — master.db/ANLZ リーダー、`library.py`（`Library`,
  `rekordbox_running()`, `pending_wal_bytes()`, `default_master_db_candidates()`）。
  read-only 分析の心臓。新方針でもここは資産。**分析ロジックは今回も触っていない。**
- `setagent/` のドラフト/コマンド/履歴モデル（`SetDraft`, `History`, `Command` 群,
  `TargetCurve` 等）— Command/History パターン。エージェントは ChangeSet を出すだけ（B-8）。

**UI 層（新方針で大改修の対象）:**
- `setagent/webui/state.py` — Draft+分析 → JSON。フレーズ strip をここで生成。
  ※テスト `test_webui_state.py`（12件）がフレーズ strip の契約を固定。
- `setagent/webui/api.py` — js_api ブリッジ。全呼び出しを1ワーカースレッドに直列化
  （SQLite のスレッド親和性対策）。`_SERIAL` タプルにメソッド名を登録する方式。
- `setagent/webui/index.html` — 単一ファイル UI（~55KB, CSS/JS 全部入り）。**ここを
  情報階層・オーバーレイ方針で作り直す。**
- `setagent/webui/app.py` — pywebview 起動（`api._window = window`。`api.window` にすると
  pywebview が public 属性を辿って無限再帰するので underscore 必須 — 既知の地雷）。
- `run_timeline.py` — エントリ。既定 WebView2、`--classic`(tkinter)/`--doctor` フォールバック。
- `setagent/gui/timeline.py` — 旧 tkinter 版（`--classic` フォールバックとして温存）。
- `build.py` — PyInstaller。index.html を `--add-data` で同梱、winforms/clr_loader を hidden-import。

**新方針で不要（凍結）:** `setagent/webui/rbrestart.py`, `api.restart_rekordbox`,
settings の `rekordbox_exe`, index.html の再起動ボタン/`doRestart`, xml_export 動線。

---

## 7. 不変条件（触るな — 仕様の背骨）

- **B-2: master.db には絶対に書かない。** read-only。編集は rekordbox 側でユーザーが行う。
  新方針はこれを一層強化する（書き出しすら捨てる）。
- **B-8: エージェントは ChangeSet を emit するだけ。** Draft を直接触らない。全編集は
  `History.run(Command)` を通す。
- **分析ロジックは触らない。** UI/UX を上げるのが今のフェーズ。精度ロジックは既存を使う。
- **検証はスクショに頼らない。** WebView2 はスクショ困難。`window.evaluate_js()` と実データ照合。
- Command のシグネチャは `inspect.signature` で確認してから使う（例: `Move(track_id, to)` は
  位置ではなく track_id を取る — 過去に誤ってバグらせた）。
- `state.py` のフィールド名は実データクラスをダンプして確認（過去に5つ推測で外した）。

---

## 8. 今セッション（2026-09-15）の成果と、その扱い

**TAD-5 決着（rekordboxAgent ローカル API 調査）:**
- rekordboxAgent は `localhost:30001`、マウントパス `/api/v1/`。`GET /api/v1/hello` のみ 200、
  他は全て 401。認証 `api_token` は `token/generate_token` の **RSA 署名ゲート**で、
  バンドルには公開鍵のみ・秘密鍵は rekordbox.exe 側。**サードパーティは正規に token を取れない。**
- → rekordboxAgent 経由の取り込み自動化は不可能。XML が唯一の正規ルートだったが、その XML 動線
  自体を新方針で捨てる。この調査は「その線は無い」を確定させた意味で有効。write 動詞は未使用。

**再起動代行の実装（今回作った）:** 動作は実機検証済みだが、**新方針で不要**。凍結。

**detail:** 詳細は `HANDOFF.md` 冒頭の「2026-09-15 追記」に記録済み。

---

## 9. 次セッションの推奨着手順（優先順位）

1. **情報階層の再設計（設計から）。** メイン UI = 予測総尺（主役）+ 過不足の一言 +
   レコメンド入口。詳細（ENERGY/フレーズ/警告/ミニマップ）は別ページへ。まず紙/モックで
   情報階層を決めてから index.html を作り直す。`design:design-critique` 等のスキルが使える。
2. **ヒーロー指標の差し替え。** verdict テキスト撤去、絶対時間を主役に。`state.py` の
   出力はそのまま使える（差分ではなく総尺を前面に出すのは view 側の仕事）。
3. **自動更新（準自動から）。** §5-1 の (b)+mtime 監視を先に成立させ、WAL 可視性を実測。
4. **オーバーレイ化。** frameless+on_top の常駐パネルを試作。狭い縦長で成立する UI に。
5. **レコメンド機能（コア価値）。** 尺不足→補完候補 / 尺超過→除外候補。分析データ
   （ENERGY ピーク/ボトム、フレーズ）と co-occurrence 統計（`lib.get_play_history`）を使う。
6. アートワーク表示。
7. LLM を実キーで通す（ユーザー指示で「最後」。DPAPI 保存は実装済み）。

**やらない:** 書き出し/取り込み/再起動代行の磨き込み（凍結）。分析ロジックの改変。

---

## 10. 環境・起動・ビルド

- 実機: Windows, DPI 144 / 物理 1920×1200。rekordbox 7.2.14 を
  `C:\Program Files\rekordbox\rekordbox 7.2.14\rekordbox.exe` にインストール。
- master.db: `%APPDATA%\Pioneer\rekordbox\master.db`。
- dev 起動: リポジトリ直下で `python run_timeline.py`（既定 WebView2）。
- ビルド: `python build.py` → 単一 exe（`SetAgentTimeline.exe`）。他人の PC で動く前提。
- WebView2 は Windows 10/11 標準。JS ビルド不要、ローカル HTTP サーバ不要（js_api 直結）。
- テスト: `python -m unittest`（`test_webui_state.py` 等）。

---

## 11. 未解決の設計判断（新セッションがユーザーと決めること）

- 「自動更新」をどこまで自動にするか（完全自動 vs 準自動＋更新ボタン）。WAL 可視性の実測次第。
- オーバーレイの追従方式（rekordbox ウィンドウ追従 vs 自由配置の常駐パネル）。
- レコメンドの「適用」をどうするか（Set Agent は提示だけ／将来 rekordbox 反映を支援するか）。
  ※現方針は「提示だけ、編集は rekordbox」。ここを変えると書き出しが復活しうる。
- 詳細ページの粒度（1枚に集約 vs タブ分割）。

---

## 12. 引き継ぎチェックリスト（新セッションの最初の一手）

- [ ] このファイル → `HANDOFF.md`（特に 2026-09-15 追記）→ あれば spec を読む。
- [ ] `python run_timeline.py` で現行 UI を一度起動し、現状を体感する。
- [ ] §9 の順で、まず情報階層の設計をユーザーと合意してから実装に入る。
- [ ] 「無難にまとめるな」— ユーザーの一貫した要求。UX を一段上げる提案を出す。
- [ ] 分析ロジックと B-2/B-8 は触らない。

---

## 付記: 過去の重要な地雷（再発防止）

- `api.window=window` は無限再帰 → `api._window` に。
- pywebview は各 js_api 呼び出しを別スレッドで走らせる → SQLite スレッド親和性のため
  `api.py` で1ワーカーに直列化（`_SERIAL`）。setagent/rekordbox は触らずに解決した。
- `.scroll` に `min-height` が無いと ENERGY/SECTIONS が画面外へ押し出される（flex 崩れ）。
- `device_commit_files` が書き込みを黙って落とすことがあった → 書き込み後は必ずバイト数確認。
- rekordbox の XML は起動時にしか読まれない（ツリー再読込では反映されない）。※参考情報。
