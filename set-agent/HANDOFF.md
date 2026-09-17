# Set Agent — 引き継ぎメモ

## ▶ 次のセッションはここから（2026-09-17 16:30 時点の引き継ぎ）

ここだけ読めば続きから拾える。詳細は下の日付付き追記に全部ある。

### いま何ができているか（実機で全部確認済み）
- **read-only の常駐パネル**（WebView2、460×940、常に手前）。rekordbox の master.db + -wal を復号して読み、
  rekordbox で編集すると 5 秒以内に自動追従。書き出し・rekordbox 操作はしない。
- **メイン画面**（上から）: 条件（Playlist / Target Time / Mix / Curve / ドロップ上限 / **Target BPM** / BPM 変化あり）。
  **Target BPM は常に値を持つ**（2026-09-17 フィードバック: 原曲 BPM のままかけることは稀）。未入力なら
  プレイリストの BPM 中央値（欄に「自動」）。空欄に戻すと中央値に戻る。変化点は「140 → 150 BPM」の形で from→to を出す
  → **予測総尺 56px**＋超過・不足ピル＋BPM チップ → 次の一手カード → **候補リスト**
  （超過: 外す候補、不足: 足す候補、目標内: 非表示）。
- **詳細画面**: TRACKS（2 色交互、幅 24px 以上のブロックに「No. 曲名」、ダブルクリックでフレーズ構成シート）/ ENERGY（実測＋
  目標カーブ、点の編集可）/ SECTIONS / 削り代カード（超過時のみ）/ 選択中（読み取りのみ）。
  **「全体」は横幅に収めて表示**（横スクロールなし、ミニマップ非表示、ENERGY は 3px バケットの平均で近似、
  目盛は 48px 以上空く粗さを自動選択）。「詳細」は 96px/分で横スクロール。fit 密度ではブロックの端トリムは無効。
- **アートワークはホバーの小窓**（`#artpop`、120px）。TRACKS のブロックと候補リストの行に 260ms 乗せると出る。
  キーボードフォーカスでも出る。ドラッグ開始・クリック・スクロール・離脱で消える。
- **マイルストーン起点のプレイリスト生成（2026-09-17 実装）**: TRACKS のブロック（または外す候補の行）を
  **右クリック**（キーボードは M）→「マイルストーンにする／目標時刻を設定…／位置をロック」。エージェントに
  「埋めて」「プレイリストを作って」「組んで」と言うと `analysis.plan_fill_sections`（`agent/fillplan.py`）が
  区間ごとの予算（目標時刻、無ければ目標尺の残りを均等配分）を、直前の曲の BPM・キーに繋がる実在曲で埋めた
  Change Set を出す。ルールベースの Advisor も同じ計画（BUILD_WORDS）。実測 15min_mix: 11 曲で 10:02 → 57:37。
  結果は Set Agent 内の Draft（read-only 方針のまま。rekordbox へ渡す手段は XML 書き出し凍結中で未決）。
- **エージェント**（右ドロワー）: 提案は Change Set、チェックして適用、undo 可。**LLM は API キー不要**:
  この PC の Claude Code のログイン（企業アカウント）を `claude -p` 子プロセスで使い、ツールは自前の
  ローカル MCP サーバ（`agent/mcp_server.py`、stdlib のみ）で渡す。順位は Claude Code → API キー → ルールベース。
  設計と実測は `docs/llm_backend_2026-09-17.md`。
- **設定シート**: rekordbox の手動再読込、Claude の接続状態（接続中／未ログイン→「ログイン」ボタン／見つかりません）、
  モデル（Sonnet／Opus）、API キー（任意、DPAPI）。
- フォントは rekordbox と同じ **Arial 系**（同梱なし）。磨き込み済み: AA コントラスト・11px 下限・全要素フォーカス可。

### 最新の状態
- GitHub `utsumi123456/my-project` `main` = 2026-09-17 の「TRACKS labels at both densities; artwork in a hover popover」コミット
  （作業ツリー clean、push 済み）。
- 配布 exe: `C:\Users\7166700\source\my-project\set-agent\dist\SetAgent.exe`（2026-09-17 ビルド、同コミットと同一ソース）。
- テスト 199 件 OK。**`python -m tools.eval_agent acid` 6/6 PASS（平均 11.5 秒、最大 23.9 秒）、`15min_mix` 5/5 PASS、
  `15min_mix build fill` 2/2 PASS（build 18.9 秒、fill 25.6 秒）。**
  `probe_views` acid 460×940、`probe_agent` acid（ルールベース経路。probe 内で `SETAGENT_LLM_BACKEND=api` に固定）。
- gh CLI はログイン済み（`utsumi123456`）。**この Claude のシェルでは PATH に無い**ので
  `"C:\Program Files\GitHub CLI\gh.exe"` のフルパスで呼ぶ。git の資格情報は gh に設定済み（push はそのまま通る）。

### 次にやること（ユーザー決定、2026-09-16 22:17。上から順）
1. ~~LLM 実キー疎通~~ **キー不要になった（2026-09-17）**。`python -m tools.probe_llm acid` が Claude Code 経由で通る。
   残りは rekordbox 新版での動作確認（手順案は 09-16 深夜の追記）。
2. ~~AI エージェントの検証~~ **第 1 段完了（2026-09-17 午後）。** `tools/eval_agent.py` が実 Claude で 6 シナリオ
   （尺の質問／一番長い曲／フレーズ構成／存在しない曲の挿入依頼／60:00 に収める／1 曲外す）を流し、
   「回答中の mm:ss が全部ツール結果に由来するか」「Change Set が目標に届くか」「不要な Change Set を作らないか」
   「30 秒以内か」を自動判定する。直したこと（下の 14 時台の追記）: fit 計画をツール化（48 曲外して 58:46 に届く。
   以前は手選びの 4 曲で 106:16 止まり）、ツール出力の圧縮と壊れない切り詰め、操作スキーマの厳密化と別名許容、
   diff に増減を明記、プロンプト（summary の値を引用・引き算しない・確認を聞き返さず Change Set を出す）。
   ~~その後に「マイルストーン起点のプレイリスト生成」~~ **済み（16:30、上記）**。
   **次:** 解析精度の向上（フレーズ解析なし曲の扱い、removal のスコア、recommend の重み）。eval に新シナリオを
   足してから直す、の順で。生成結果を rekordbox に渡す手段（XML 書き出しの復活か、手動でのプレイリスト作成手順）は
   ユーザー判断待ち。
3. ~~TRACKS の「全体」密度にもトラック No.＋曲名~~ **済み（2026-09-17）**。`renderLanes` は幅 `LABEL_MIN_PX`（24px）以上の
   ブロック全部に `.trk-t` を出し、`text-overflow:ellipsis` で省略。acid 全体密度: 96/96 にラベル、幅不足 0、うち 92 が省略表示。
4. ~~アートワークはホバーのウィンドウで表示~~ **済み（2026-09-17）**。`#artpop`（fixed、120px、pointer-events:none）。
   `ART_L` に track_id ごとに 120px 版をキャッシュ（`api.artwork([id], 120)`）。行の 28px サムネは据え置き。
5. ~~マイルストーン／ロックの UI 復帰~~ **済み（2026-09-17 16:30）**: 右クリックメニュー（`#ctx`）。

次の着手候補は 2（エージェント検証・解析精度）。

**eval の地雷:** `tool_server()` は最初の ask で遅延生成されるので、ask の前に呼んでおかないと最初のシナリオの
ツール記録が空になる（第 1 回の「ツール未使用」は誤判定だった）。master.db の読みは `api._pool` 経由で。
モデルは同じプロンプトでも揺れる（fit で「提示してよいですか」と聞き返した回があった）。判定は 2 回回して見る。

**Claude Code backend の地雷:** `--bare` を付けると OAuth を読まず「Not logged in」になる／stdin は閉じて渡す／
この Claude セッションの中から子 `claude` を起こすと `CLAUDECODE` 等が継承されるので `_child_env()` で落としている／
`claude auth status` は 1〜2 秒かかるので 10 分キャッシュ（`forget_cli_status()` で破棄）／MCP のツール名に `.` は使えない
（`analysis_get_sections`）／ツール本体は HTTP スレッドではなく、`ask()` で待っている api ワーカーが `pump()` で実行する
（SQLite のスレッド固定のため。HTTP スレッドで直接呼ぶと `ProgrammingError`）。

### 動かし方と判定
```
cd C:\Users\7166700\source\my-project\set-agent
python -m unittest discover -s tests -q          # 157 tests
python run_setagent.py                           # パネル
python -m tools.probe_views acid 460 940         # 両ビューの実測（Set BPM 往復・候補リスト・フレーズシート込み）
python -m tools.probe_polish acid 400 900        # 磨き込みの終了判定（文字サイズ・コントラスト・フォーカス）
python -m tools.probe_refresh acid               # 自動追従 4 シナリオ
python -m tools.probe_actions acid               # bridge 経由の操作・ドラッグ並べ替え
python -m tools.probe_agent acid                 # ドロワー〜Change Set 適用
python build.py                                  # テスト → exe → dist/
```
- **probe は 1 本ずつ。テストと並走させない**（復号キャッシュが固定パスで、同時実行すると
  `database disk image is malformed` になる）。
- **`build.py` の前に起動中の Set Agent を閉じる**（dist の exe がロックされる）。
  ロックされたら `python build.py --skip` で build/exe から再配置できる。
- 長い置換スクリプトはヒアドキュメントで渡さず、ファイルに書いて `python <path>` で実行する
  （`ENAMETOOLONG`、`\s` のほつれ）。
- 文言は です・ます。数値は `analysis.*` から取り、UI で計算しない（§7）。

### 主要ファイル
| 何 | どこ |
|---|---|
| UI 本体（素の HTML/CSS/JS、ビルド工程なし） | `setagent/webui/index.html` |
| JS↔Python ブリッジ（単一ワーカー直列化、`_reco_block`、`set_set_bpm`） | `setagent/webui/api.py` |
| 表示用 JSON 整形、Mix プリセットの日本語ラベル | `setagent/webui/state.py` |
| Draft / Command / History（`SetSetBpm`, `SetBpmChange` を含む） | `setagent/domain/draft.py` |
| 尺の計算（セット BPM の優先順はここ） | `setagent/analysis/timing.py` |
| 外す候補 / 足す候補 | `setagent/analysis/removal.py`, `setagent/agent/recommend.py` |
| 配布用説明書（画面の見かた） | `dist_readme/はじめに.md` |

---

## 2026-09-16 追記（22 時台） — 公開（配布なし）に向けた磨き込みパス

進捗報告のため現段階の Set Agent を見せる必要が出た。**情報・表記方法・位置は現行設計のまま**、
間隔・階層・タイポ・色・状態表示だけを整える、というユーザーの制約で実施。参照したスキルは
`frontend-design`（方針・自己批評）/ `baseline-ui`（守るべき下限）/ `design-review`（判定軸）。

**目標（数値で置いた）:** 全テキスト 4.5:1 以上（56px の hero だけ 3:1 可）／最小文字 11px／クリックに
反応する要素は全部キーボードフォーカス可／入力欄はプレースホルダが収まる／386〜400px で横はみ出しなし。
**終了判定:** 新設 `tools/probe_polish.py` が両ビューで PASS（DOM の computed style から実測。CSS を
読むのではなく描画結果で判定する）。実行: `python -m tools.probe_polish acid 400 900`。

**直したもの:**
- 赤の文字色: 塗り用の `--critical`（#d03b3b、3.7:1）を文字に使っていた → 文字は `--critical-ink`
  （#ec6059、surface 5.5:1 / raised 4.9:1）。hero・区間の超過・削り代の超過に適用。塗り（ピル・バー）は据え置き。
- 補助文字 `--ink-3` #7d8794（raised 上 4.4:1）→ #8b95a3（5.3:1）。
- 10px の文字 5 箇所 → 11px（目盛・リスト見出し・理由行）。行の余白 4→6px。
- フォーカス: `.btn` だけだった `:focus-visible` を select / input / セグメント / 行 / 曲ブロック /
  カード / 候補 / リンク / カーブの点に拡張。候補行と曲ブロックに `tabindex=0`、Enter で選択
  （曲ブロックは Shift+Enter でフレーズ構成）。
- Set BPM 欄: 幅 70px でプレースホルダ「原曲のまま」が切れていた → 96px。条件行のコントロール高さを 28px に統一。
- レコメンドカードの hover で左アクセントが `inherit` で消えていた不具合 → 状態ごとに色を維持。
- ピルの角を 999px（真のピル）に。全体の字間 .09em → .06em。スクロールバーをテーマ色に。
- 緑 #1fb013 の直書きを `--ok` に集約。

**変えていないもの（制約どおり）:** 表示項目、文言、各機能の位置と順番、大文字ラベル（TRACKS / ENERGY /
SECTIONS は readme の呼称なので据え置き）。

**フォントを rekordbox に合わせた（追加タスク、22:30〜）:** 調べた範囲では rekordbox 7.2.14 は
フォントを同梱もインストールもしていない（`Program Files
ekordbox` に .ttf/.otf なし、exe 内に
フォント本体なし、レジストリの Fonts に Pioneer 由来なし）。ブラウザ／メニューの文字は設定の
`MenuFontName`（既定 **Arial**、環境設定 > 表示 で変更可）で、日本語は OS のフォールバック。
skins の SVG 3 枚に `HelveticaNeueLTW1G` があるが、これは画像素材の指定。exe 内の "Montserrat" は
ICU ロケールの国名で、フォントではない。→ `--sans` と `--mono` をともに
`"Arial","Yu Gothic UI","Meiryo UI",system-ui` にし、数字は `font-variant-numeric:tabular-nums` で
桁を揃える（Consolas は廃止）。フォントは同梱しない（rekordbox と同じ機械のフォントを使うことで一致する）。
ユーザーが rekordbox 側でフォントを変えている場合は一致しない点に注意。

**実測（acid, 400×900 / 460×940）:** 文字サイズの集合 {11,12,13,14,15,56}、低コントラスト 0、
フォーカス不可 0、Set BPM 欄 95px（必要 81px）、横はみ出しなし、バー 1 行 53px。
`probe_views` 回帰なし（外す候補 48 行、Set BPM 往復、詳細 96/96 ラベル）。テスト 157 件 OK。

**次回以降（ユーザー決定、2026-09-16 22:17）:**
1. 検証（LLM 実キー疎通・rekordbox 新版）は後日。
2. マイルストーン起点のプレイリスト生成は **AI エージェントの検証と解析精度の向上を済ませてから** 実装。
3. TRACKS の「全体」密度にもトラック No. と曲名を出す（長い場合は省略 `Track name 123…`）。未着手。
4. アートワークは **ホバーで出るウィンドウ**に表示する方針（詳細レーンに常設はしない）。未着手。
5. マイルストーン／ロックの UI 復帰は AI エージェント検証後に判断。

---

## 2026-09-16 追記（深夜） — セット BPM で尺を補正、レビュー第 2 弾の細部

**気づきへの回答: 予測時間はこれまで「各曲を原曲 BPM でかける」前提だった。** 曲ごとの手動テンポ
（`TrackEntry.tempo`）はあったが、セット全体の BPM を持っていなかったので、140 BPM の曲を 160 の
セットでかける場面では実測と 12.5% ずれる。今回入れたもの:
- `Constraints.set_bpm`（None = 原曲どおり）と `Constraints.bpm_changes: {track_id: bpm}`
  （「この曲から X BPM」。track_id キーなので並べ替えても曲に付いて動く）。コマンド `SetSetBpm` /
  `SetBpmChange`（History 経由、undo 可）。`timing.compute` の優先順は **曲ごとの手動テンポ → 変化点／
  セット BPM → 原曲 BPM**。テスト `tests/test_timing.py::SetTempoTests`（5 件）。
- 条件行に **Set BPM**（空欄 = 原曲のまま。`Settings.set_bpm` に文字列で保存、40〜300 のみ受理）と
  **「BPM 変化あり」スイッチ**。オンで下に変化点パネル（曲を選んで BPM を入力 → 追加／外す）。
  タブではなくインライン展開にした（縦長パネルにタブを増やすより読む流れを崩さない）。オフにすると
  変化点を全部外す。hero の下に「@ 160 BPM →変化あり」か「原曲 BPM」のチップ。
- 実測 acid: 原曲 137:18 → Set BPM 160 で **124:59**（全曲 set_tempo 160）→ 4 曲目から 170 で 117:51
  → undo・空欄で 137:18 に復帰。`probe_views` に往復を追加。

**細かな修正:**
- 凡例の「N曲中 N曲にフレーズ解析あり」→ **解析なしの曲があるときだけ**「N曲中 M曲にフレーズ解析なし」。
- 削り代カードの「目標の範囲に入っています…」→ 目標内なら **行ごと非表示**。
- TRACKS の曲名 → **「詳細」密度のときだけ全ブロックに「No. 曲名」**。36px では出さない（出る箱と出ない箱が
  混ざるのをやめた）。尺・BPM の 2 行目は撤去。
- ズーム「全体（3px/分）」を **廃止**。旧「区間（36px）」を「全体」、96px を「詳細」の 2 段に。
  ミニマップが全体像の役。`DENSITY` から overview を消したので `mode` に "overview" は来ない。
- 詳細の最下段 **インスペクタ編集欄（Mix / Tempo / マイルストーン / ロック）を撤去**。読み取り
  （位置・再生・BPM・Mix・フレーズ・構成を見る）だけ残した。**注意:** これで UI からマイルストーンと
  ロックを付ける手段が無くなった。`api.set_milestone` / `set_lock` / `set_preset` / `set_tempo` は
  残っており、`probe_actions` は bridge 直叩きに書き換えた。SECTIONS レーンは当面 1 区間のまま。
  マイルストーンを UI に戻すなら、曲リストの行メニュー（右クリック）あたりが候補。
- `probe_actions` は XML 書き出しボタン（前回撤去済み）も参照していて元から壊れていた。合わせて直した。

**検証済み:** テスト 157 件 OK。`probe_views` acid（Set BPM 往復・詳細密度で 96/96 ブロックにラベル・
凡例カウント空・インスペクタ編集欄なし）と 15min_mix（目標内で削り代行が非表示）、`probe_actions`
（bridge 経由の preset/milestone/lock、Set BPM 160 → 131:59、undo で復帰、ドラッグ並べ替え OK）。
exe は `python build.py` で再ビルド済み。

**地雷（今回）:**
- `Library` の復号キャッシュは `%LOCALAPPDATA%\SetAgent\cache\master_plain.db` の **固定パス**。probe と
  unittest を同時に走らせると片方が `database disk image is malformed` になる（probe_actions で踏んだ）。
  **probe は 1 本ずつ、テストと並走させない。**
- `probe_actions` のドラッグは `ra.left + 4` から掴んでいて、端トリム（7px）に取られていた。中央から掴むように直した。
- `set_set_bpm` は settings に即保存するので、undo で戻しても保存値が残る → `_persist_set_bpm()` を
  undo/redo でも呼び、draft の値に揃えるようにした。

---

## 2026-09-16 追記（夜） — レビュー反映: 読む順番・重複除去・候補リスト・2 色レーン

ユーザーのレビュー（成果物は理想に近づいている。項目の意味が分からない箇所と表示順が主な指摘）を
一括で反映。すべて実機 WebView2 で probe 済み（`probe_views` acid/15min_mix × 460/1280、
`probe_refresh` 4 シナリオ、`probe_agent` B-8 経路）。テスト 152 件 OK。

**判断したこと（レビューで「決めて」と言われた点）:**
- **Mix の「short」** → 削除ではなく改名。内部キーは変えず（`phrases.py` のフォールバック先・
  settings・テストが参照）、表示だけ `state.PRESET_LABELS` / `PRESET_HELP` で日本語化:
  フル尺 / 1ドロップ / 2ドロップ / **イントロ/アウトロ短縮**。各選択肢とラベルに説明を title で付けた。
  short の中身は「ドロップ数は変えず、イントロとアウトロを 8 小節ずつ残して詰める」。
  1ドロップ/2ドロップ でドロップが見つからない曲は自動でこの扱いになる（`preset_range` の既存挙動）。
- **cap 32bar** → 「**ドロップ上限 32 小節**」に改名し、説明を title で付けた。意味は
  `cfg["max_drop_bars"]=32`（1 つのドロップが 32 小節を超えたら 32 で切る。dnb 向け）。
  **1ドロップ/2ドロップ 以外では非表示**（`#cap32Lbl`。フル尺・短縮では効かないので出さない）。
- **cap32 の下の曲リスト** → プレイリスト一覧は廃止（rekordbox と重複）。代わりに
  `api._reco_block()` が返す **候補リスト**: 超過なら「外す候補」（`analysis.removal` の
  `removal_candidates`+`pick_removals`、上から N 曲で収まる。各行に理由・節約分・外した後の総尺、
  収まった行から緑）、不足なら「足す候補」（`tools.recommend_candidates`、プレイリスト外・最後の曲に
  繋がる BPM/キー、穴が 1 曲分より短いときは平均曲長を枠にする）。目標内なら非表示。
  外す行クリック → その曲を選択（詳細で見る）。足す行クリック → 挿入案をドロワーで確認（B-8 のまま）。
  実測 acid: 外す候補 48 行、最終行の「外した後」58:34。15min_mix（9:28 / 50:32 不足）: 足す候補 12 行。
- **警告欄** → 削除。尺の判定は hero、平坦は ENERGY で見える。`ST.warnings` は残してある（エージェントが読む）。

**表示順（メイン）:** バー（タブ・元に戻す・やり直す・エージェント・設定）→ **条件** → **予測総尺** →
レコメンド入口カード → 候補リスト。実測 top: 条件 139 / hero 246 / カード 421 / リスト 521（460 幅）。

**重複の除去:** バーのプレイリスト名（条件の Playlist と重複）、hero 下の「目標 60:00」
（バレットバーの目盛と重複）、最下段の「rekordbox の編集を反映」ボタン（自動追従と意味が衝突）。
手動再読込は **設定シートの「rekordbox ライブラリ」欄**に移動。試行を保っていて自動反映を止めた
ときは **設定ボタンにドット**（`.hasnew`）＋ toast 1 回。`probe_refresh` / `probe_live` を追従させた。

**ホバー説明:** `#app` 内の `title` 属性 185 個（タブ・各ボタン・条件の各項目・hero・バー・カード・
レーン見出し・インスペクタの各項目）。ネイティブ tooltip なので実装コストゼロ、約 1 秒で出る。

**TRACKS レーンの 2 色化:** フレーズ色は帯から撤去。曲ごとに `#2a313a` / `#3a4350` を交互
（`.trk.alt`）、解析なしはハッチのまま。高さ 72→44px。ミニマップも同じ 2 色。
**フレーズ構成は曲をダブルクリック**（または選択中の「構成を見る」）で開くシートに移した
（`showPhrases`: 色帯 + ラベルと時刻の一覧。色は rekordbox と同じ意味、色相は変えていない）。
凡例はハッチ / 目標 / 提案後 / 操作ヒント / 解析件数だけ。

**exe:** `python build.py` で再ビルド（下記の実行ログ参照）。`はじめに.md` §3〜5 を新レイアウトに合わせた。

**ユーザーから明確化されたオーダー（今後）:**
1. **rekordbox のバージョン検証** — 本機は 7.2.14。7.2.14 より新しい版で master.db の暗号鍵・
   スキーマ（djmdContent/djmdSongPlaylist/ImagePath）・ANLZ フォーマット（PSSI フレーズ）・WAL の
   扱いが変わっていないかを確認する必要がある。手順案: 別 PC か仮想環境に新版を入れ、`--doctor` →
   `python -m tools.probe_state <playlist>` → `probe_views` の 3 段で見る。未着手。
2. **マイルストーン起点のプレイリスト生成**（エージェントに担わせる） — DJ が核になる曲を複数選び
   大まかな順番を決める → その曲を要（マイルストーン）として、間の空白を推奨曲で埋めたプレイリストを
   AI が作る。既存の `sections`（区間予算）+ `recommend.candidates`（区間の BPM/キー/エネルギー）が
   土台になるが、**楽曲解析の精度を上げてから**追加検討とする（ユーザー判断）。read-only 方針との
   整合（生成結果を rekordbox にどう渡すか。XML 書き出しは凍結中）も要決定。

**地雷（今回）:** 長い置換スクリプトをヒアドキュメントで渡すと `ENAMETOOLONG` で落ちる／`\s` が
1 段ほどけて一致しない。スクリプトはファイルに書いて実行すること。

---

## 2026-09-16 追記 — read-only 方針で UI を 2 ビューに再編（新アカウント初日）

方針は `docs/handoff_2026-09-15_pivot.md` §1〜§4 のとおり（書き出し廃止・read-only・予測総尺が主役・
オーバーレイ前提）。ユーザーと合意した決定: **自由配置の常駐パネル / 詳細は 1 枚のスクロール
ページ / index.html を 2 ビュー構成に再編 / git init して差分管理**。

**やったこと（すべて実機 WebView2 で probe 検証済み、テスト 131 件 OK）:**
- `git init` — 初回コミットは 2026-09-15 時点のスナップショット。以降は差分で追える。
- `webui/index.html` を **メイン / 詳細の 2 ビュー**に再編。上部バーの「セット｜詳細」で切替。
  - メイン（Tier 1 だけ）: **予測総尺 56px（主役）** → 目標・過不足ピル・曲数 → バレットバー →
    **レコメンド入口カード**（超過:「N 分ぶん外す必要」→ エージェントに「mm:ss に収めて」を送る /
    不足: 「候補を出して」を送る / 目標内: 詳細へ）→ 条件行（Playlist/Target/Mix/Curve/cap32）→
    **曲リスト**（#・曲名・尺・累積時刻。目標を越えた行は累積が赤、◆=マイルストーン、
    「解析なし」タグ）→ 鮮度行（「HH:MM 時点の rekordbox ライブラリ」+ 反映ボタン）。
  - 詳細（Tier 2）: 旧 transport / TRACKS / ENERGY / SECTIONS / 凡例 / 削り代 waterfall / 警告 /
    インスペクタ。既存 JS（ドラッグ・端トリム・カーブ編集・エージェント・ゴースト）は無改変。
    `.detail{overflow:auto}` の 1 枚スクロール、`.scroll` の床は 400px。
  - verdict テキスト・XML 書き出しボタン・再起動ボタン・`doExport`/`doRestart` を UI から除去。
    Python 側 `api.export_*` / `api.restart_rekordbox` / `rbrestart.py` は凍結のまま残置。
- **準自動更新（§5-1 の (b)+mtime）**: `api.library_changed()`（ワーカー非経由、stat のみ）で
  master.db と -wal の mtime/size を返す。JS が 5 秒ポーリング + window focus / visibility で
  即時確認。master.db が変わり、かつアプリ内編集が無い（History が load 直後の基準点のまま）なら
  **自動で rescan**。編集があれば「rekordbox の変更を検出 — 反映していない」+ ボタン点灯で保持。
  -wal だけ変わった場合は「rekordbox に未保存の編集がある（まだ読めない）」と正直に出す
  （復号器は WAL をマージしないので実際に読めない）。
- `app.py`: 起動を **460×940 / min 380×560 / on_top=True** の細い縦長パネルに変更（maximized 廃止）。
- 新 probe: `tools/probe_views.py`（両ビューの実測、`[playlist] [w h]` で幅指定可）、
  `tools/probe_refresh.py`（自動更新 4 シナリオ）。`probe_layout.py` は新 id に追従。

**実測値（acid / 1280×778）:** hero「137:18」、ピル「77:18 超過」、96 行中 49 行が目標超え、
レコメンドカード「77:18 ぶん外す必要がある / 1曲平均 1:26 なので、およそ 54 曲」。
386px 幅でも横はみ出しなし。詳細ビューは 3 レーンすべて画面内。

**WAL 可視性の実測結果（2026-09-16 16:03–16:13、rekordbox 7.2.14、`tools/watch_masterdb.py`）:**

| 操作 | master.db | master.db-wal |
|---|---|---|
| 監視開始時 | 最終更新 23 時間前 | 19 フレーム、ckpt_seq 0 |
| 15min_mix に 1 曲追加 | 不変 | +10 フレーム |
| 同曲を削除 | 不変 | +18 フレーム |
| fav_1 で複数曲の順番変更（6 回のドラッグ） | 不変 | +165 フレーム（ドラッグ 1 回 = 1 トランザクション） |
| 1 分放置 | 不変 | 不変 |
| rekordbox 終了 | +4096 B、mtime 更新（プロセス消滅の 7 秒前） | -wal / -shm とも削除 |
| rekordbox 再起動 | 不変 | 直後に再生成、6 → 11 フレーム |

結論: **rekordbox 起動中は一度もチェックポイントしない。** 編集は全部 -wal に溜まり、master.db に
書き戻るのは終了時だけ（前セッションは 23 時間書き戻していない）。放置でも発火しない。SQLite 既定の
自動チェックポイント（1000 ページ ≈ 4 MB）に届くかは未確認（本セッションは 213 フレームで終了）。
→ 現行の準自動更新は rekordbox 起動中は「まだ読めない」表示にしかならず、§5-1 の「編集したら
Set Agent が追従する」は **WAL を読まない限り成立しない。**

WAL を読むのは実現可能。SQLCipher は WAL のフレームヘッダ（24 B: ページ番号・コミット後 DB サイズ・
salt・チェックサム）を平文で持ち、ページ本体は master.db と同じ鍵・同じ方式（ページ単位 AES-CBC、
末尾 reserve に IV + HMAC、HMAC にページ番号を含む）。`decrypt_masterdb.decrypt` のページ処理は
そのまま WAL フレームに使える。やることは標準の WAL リプレイ: 有効フレーム（salt が WAL ヘッダと
一致、最後のコミットフレームまで）を歩き、ページ番号ごとに最新フレームを復号済み DB へ上書き。
読み取り専用なので B-2 はそのまま。ただし `setagent/rekordbox/` の凍結ゾーンに手が入る。

**WAL リプレイ実装済み（2026-09-16、ユーザー決定）:** `tools/decrypt_masterdb.py` に `decrypt_page` /
`committed_wal_frames` / `replay_wal` を追加し、`decrypt(src, dst, wal=...)` が標準の WAL リプレイ
（salt 一致・累積チェックサム・最後のコミットフレームまで、ページごとに最新フレームが勝つ）を行う。
`Library._decrypt` は master.db → -wal の順にスナップショットし、その間に master.db が動いたら
やり直す（チェックポイントを挟んで世代の違うページを混ぜないため）。`rescan()` も同じ経路。
実機の暗号化 WAL 11 フレームを HMAC 検証つきで復号し integrity_check ok。UI は「まだ読めない」状態を
撤去し、-wal の変化も自動再読込の対象にした（`probe_refresh` 4 シナリオ OK）。テストは
`tests/test_wal_replay.py`（sqlite3 が実際に書いた WAL に対して、未コミット尾・破損フレーム・salt
不一致・DB 成長を確認）。**実機で確認済み（`tools/probe_live.py`、16:27）:** rekordbox 起動中に
15min_mix へ 1 曲追加 → パネルの hero 8:23→9:16 / 8→9 曲へ自動追従、削除 → 8:23 / 8 曲へ戻る。
どちらもアプリに触れずに反映（ポーリング 5 秒以内）。§5-1 の自動更新はこれで成立。

**パネル位置/サイズの記憶（2026-09-16）:** `Settings.window`（"x,y,w,h"）。`app.saved_geometry` は
保存位置が現在接続中のスクリーンに 200×120 以上重なる場合だけ復元し、それ以外は既定サイズ・既定位置
（外したモニタの座標で画面外に出さない）。`remember_geometry` が moved/resized（0.8 秒デバウンス）と
closing で保存。実機 probe: 200,60,500,720 で復元 → move/resize → 320,90,480,800 が保存された。
テスト `tests/test_window_geometry.py`。

**レコメンド本体（外す候補）実装済み（2026-09-16、提案をユーザー了承）:** `setagent/analysis/removal.py`。
`removal_candidates()` が各曲に「外しやすさ」スコアを付ける — 前後と同じ高さに埋もれている(+)、
目標カーブから 0.2 以上外れている(+)、外した後の継ぎ目のキーが 1 歩以内(+) / 山・谷を作っている(−0.4)、
継ぎ目の BPM 差が 8% 超(−、20% で −0.5) / キーが 3 歩以上(−0.2)。ロックとマイルストーンは対象外。
`pick_removals()` は上から貪欲に、まず隣接を避け、足りなければ隣接も許す。節約量は play_s から消える
オーバーラップを引いた値（これを忘れると 8 分ほど届かない）。`advisor.fit_to_target` は range で
届かない残りをこれで埋め、range + remove を 1 つの ChangeSet にする（B-8 どおり提案のみ、
チェックを外せばその曲は残る）。実機 acid（96 曲 137:18 → 目標 60:00）: 48 曲を提案、適用後 58:46。
テスト `tests/test_removal.py`（7 件）。演奏履歴の共起は不使用（djmdSongHistory 83 行・MyTag 0 件で
統計にならない。DJPlayCount は `Track` に載っていないため未使用）。

**口調の統一（2026-09-16、ユーザー指示）:** 前任アカウントの命令形・断定調（「〜しろ」「お前が決めろ」
「〜だ」）を、標準的なアシスタントの丁寧語（です・ます）に全面置換。対象は advisor / changeset /
llm（SYSTEM_PROMPT にも口調の規則を追加）/ tools / diagnostics / library / webui api / index.html。
旧 tkinter 版 `gui/timeline.py` は放置。**新しい文言を書くときも です・ます で。**

**判断済み:** frameless にはしない（OS のタイトルバーで移動・リサイズ・閉じるが無料で付く）。

**アートワーク表示（2026-09-16）:** 取得元は `djmdContent.ImagePath`（例
`/PIONEER/Artwork/126/8c18…/artwork.jpg`）→ `<share>/PIONEER/Artwork/…` の JPEG（100〜170 KB、
実機 347 曲中 267 曲にあり、全件解決）。`MasterDB.image_path()` / `Library.artwork_path()` を追加。
ページは pywebview のローカル HTTP サーバ経由なので file:// の img は読めない → `api.artwork(ids, 56)`
が Pillow で 56px に切り出した JPEG を data URL で返す（1 枚 ≈ 1.8 KB、24 枚 0.28 秒、セッション内
キャッシュ）。曲リストの行に 28px のサムネ列を追加（グリッド 28/22/1fr/50/56、行高 37px）。
386px 幅で横はみ出しなし。`probe_views` に `artImgs` / `rowH` を追加。

**未検証 / 次にやること（優先順）:**
1. LLM 実キー疎通 — `python -m tools.probe_llm acid` を用意（キーは表示しない。設定画面か
   `SETAGENT_LLM_KEY` で入れてから実行）。既定モデルは `claude-sonnet-5` に更新。
2. ~~exe 再ビルド~~ 済み（17:11、`dist/SetAgent_20260916.zip` 28.0 MB。Pillow 同梱で 22→28 MB）。
   **配布形態を変更（ユーザー指示）:** zip は廃止。`dist/` には `SetAgent.exe`（この PC で動く exe そのもの）と
   `はじめに.md` だけを置く。PyInstaller の出力は `build/exe/`。`はじめに.md` は 2 ビュー UI・自動追従・外す候補に
   合わせて書き直し、口調も です・ます に統一。
   起動スモーク: exe を起こして 20 秒後にウィンドウ「Set Agent」が出ることを確認して終了。
   **実機確認済み（2026-09-16 18:10、新クローン `my-project/set-agent` にて）:** exe（17:52 ビルド）より新しいソースは
   無し、Pillow は同梱（archive_viewer で確認）、`--playlist acid` で 25 秒以内に「Set Agent」ウィンドウ。
   同じコードの Python 版に probe を当てた結果: `probe_views` サムネ 96/96・hero 137:18・詳細 3 レーン画面内、
   `probe_refresh` 4 シナリオ OK、`probe_agent` B-8 境界 OK、`api.ask("60:00 に収めて")` が 48 件の Change Set。
   exe は probe の入口を持たないので、exe そのものへの操作 probe は不可（同一ソースであることで代替）。
   地雷: `probe_refresh` の `wait_ready` は再読込中も `#app` が見えるためすぐ抜けていた。アートワーク取得で
   再読込が約 3 秒かかるようになり露見。`wait_reload`（`LOADED_AT` の更新 + カーテン消灯を待つ）に直した。
3. ~~バーは 386px で 2 行に折り返す（98px）~~ 済み（2026-09-16 21:40）: 元に戻す／やり直すを ↶ ↷ の
   グリフ（title 付き）にし、gap を 8px に。386px で 1 行 53px、横はみ出しなし（`probe_views acid 400 900`）。
   **dist の exe には未反映**（ユーザーが起動中でロックされるため。次の `python build.py` で入る）。
4. 詳細ビューの TRACKS レーンやインスペクタにもアートワークを出すか（未着手）。

**コンソールの点滅を修正（2026-09-16 18:20、ユーザー報告）:** 起動中にターミナルが開いて閉じるを繰り返していた。
原因は 5 秒ポーリングの `library_changed()` → `rekordbox_running()` が `tasklist` を子プロセスで起こしていたこと。
`--noconsole` の exe には親コンソールが無いので、子プロセスごとに新しいコンソールが作られて一瞬見える。
`rekordbox/library.py` の `subprocess.run` に `creationflags=CREATE_NO_WINDOW` を付けた（`rbrestart.py` はもとから付いていた）。
exe を再ビルド（18:18）。検証は user32 `EnumWindows` で可視の `ConsoleWindowClass` を 10 ms 間隔で数える方式:
フラグ無しの最小再現で 2 件検出、フラグ有りで 0、新 exe 35 秒で 0。
**地雷: GUI exe から `subprocess` を呼ぶときは必ず `CREATE_NO_WINDOW`。** `Process.MainWindowHandle` ではこの点滅は捉えられない。

**地雷（今回踏んだ）:** `_load` は SetTargetLength / SetRange を History に積むので、`_done` が
空かで「編集あり」を判定すると常に true になる。`api._done_base` に load 直後の長さを持たせて比較。
pywebview の `evaluate_js` に async 関数を渡すと `{}` が返る — 結果は `window.__x` に置いて後で読む。

---

## 2026-09-15 追記 — TAD-5 決着 & rekordbox 再起動代行

**TAD-5 結論: rekordboxAgent の API で XML 取り込みは自動化できない。**
- マウントパスは `/api/v1/`（前回 404 だったのは接頭辞漏れ）。`GET /api/v1/hello` は 200。
- `/hello` 以外は全て 401。認証 `api_token`（`APITokenAuthHandler`）が必須で、発行 `token/generate_token` は **RSA 署名ゲート**。バンドルには**公開鍵のみ**、秘密鍵は rekordbox.exe 側。サードパーティは正規に token を取れない。
- 書き込み口（`data/*/create_item|update_item|delete_item`, `localSync/mutateItems`）は実在するが到達不能。
- → **XML 経由が唯一の正規ルート**。B-2（master.db に書かない）と整合。write 動詞は未使用。起動した rekordboxAgent.exe は停止済み。

**ユーザー決定: 3ステップ XML 維持 + UI補助。「再起動代行」を確認ダイアログ付きで許可。**

**訂正（前回の私の誤り）:** 「再起動で減るステップはゼロ」は不正確。XML は**起動時にしか読まれない**（ツリー再読込では反映されない）ので、再エクスポートごとの再起動は*必要な手順*であり自動化できる＝手動 quit/relaunch を1つ消せる。実マージ（デッキ→「コレクションに追加? Yes」）だけは rekordbox 仕様で手に残る（=B-2 と整合）。

**実装:**
- `setagent/webui/rbrestart.py`（新規）— exe 探索 / graceful kill→relaunch。`_candidates()` は `Program Files\rekordbox\rekordbox 7.2.14\rekordbox.exe` の**バージョン付きサブフォルダ**を glob で拾う（実機の実際の場所）。running中は CIM で exe パス取得。**force=True は UI の二段目確認からのみ**（未保存プロンプトを勝手に強制終了せず `still_running` を返す）。
- `setagent/settings.py` — `rekordbox_exe` フィールド追加（見つけた exe を記憶、閉状態でも起動可）。
- `setagent/webui/api.py` — `restart_rekordbox(force)` 追加、`_SERIAL` 登録、exe を settings に保存。
- `setagent/webui/index.html` — 書き出し後モーダルに「rekordbox を再起動」ボタン。`doRestart()` が進行表示→成功toast / `still_running`時は二段目「強制終了して再起動」(danger) / `no_exe`時は手動案内。`.btn.danger` CSS 追加。手順コピーを「初回だけ」「下のボタンで代行」に更新。

**検証:** 実機で launch→graceful再起動→後始末(閉)を1パス通過（データ損失なし、元の閉状態に復帰）。JS node --check クリーン。Python 3ファイル import 実行 OK。

**未検証/フォロー:** `still_running`→force 経路は実地未踏（graceful 成功のため）。UI ボタンからの実クリック検証は残。再起動ボタンは書き出し後モーダル内のみ。**配布 exe の再ビルドは未実施**（今回の変更を反映するには `python build.py` が必要）。

---

中断しても次のセッションがここだけ読めば続きから拾えるように書いてある。
仕様の正典は `rekordbox_set_agent_spec.md`（Part A〜F）。このファイルは**作業状態**だけを持つ。

最終更新: 2026-09-15（**UI フェーズ完了。旧 tkinter 版の操作はすべて新 UI に移植し、実機で検証済み。配布 exe 済み**）

> ⚠️ `rekordbox_set_agent_spec.md` は現在どこにも無い（クラウドの旧作業ディレクトリが消えている）。
> 手元にあるなら `my-project/set-agent/` に置け。無くてもこのファイルで作業は続けられる。

---

## 1. これは何か

rekordbox のライブラリを読んで、**DJ セットの尺と展開を設計する**コンパニオン。
rekordbox 本体には手を入れない。読み取りは master.db と ANLZ を直接、書き戻しは rekordbox XML。

- 対象スコープ: セットメイク（時間管理 B-2 / 展開管理 B-3）。REC の UNDO は**スコープ外**。
- ゴール: プロトをビルドしてチーム内に配布。**他人の PC でもそのライブラリを読めること**が要件。

---

## 2. 置き場所

| 場所 | 中身 |
|---|---|
| GitHub `https://github.com/utsumi123456/my-project`（`main`） | **リモートの正本**（2026-09-16 から）。プロトごとに 1 フォルダのモノレポで、Set Agent は `set-agent/` 配下（Python パッケージは `set-agent/setagent/`）。作業は PC で行い、区切りごとに push |
| PC `C:\Users\7166700\source\my-project\` | リポジトリのクローン（ルート）。`LICENSE` とプロト一覧の README だけがある |
| PC `C:\Users\7166700\source\my-project\set-agent\` | **Set Agent の作業ディレクトリ。編集・テスト・ビルドはここで**（`python -m unittest discover -s tests -q`、`python build.py`、`python run_setagent.py`） |
| PC `…\my-project\set-agent\dist\` | チームに渡すもの（`SetAgent.exe` ＋ `はじめに.md`）。git 対象外 |
| PC `C:\Users\7166700\source\setagent\setagent\` | 旧ビルドツリー。さわらない |

クラウド作業ディレクトリはセッションごとに消える。**PC 側が正本**。
クラウドで長いファイルを書いたら `/mnt/user-data/outputs/` に置いて `device_commit_files` で転送し、
**書いたら必ずバイト数と末尾を確認しろ**（稀に取りこぼす）。
短い編集は desktop-commander の `edit_block` が確実。

---

## 3. 今どこまで出来ているか

✅ = 実機で確認済み

| ストーリー | 状態 | 実体 |
|---|---|---|
| TAD 1/2/6（master.db 復号・ANLZ フレーズ・プリセット定義） | ✅ | `tools/decrypt_masterdb.py`, `rekordbox/anlz.py`, `analysis/phrases.py` |
| S1-1〜S1-6（Set Draft・尺・テンポ・目標尺・what-if・削り代） | ✅ | `domain/draft.py`, `analysis/timing.py` |
| S2-1〜S2-7（タイムライン・実測エネルギー・目標カーブ・乖離・平坦警告） | ✅ | `analysis/energy.py`, `analysis/curve.py` |
| S3-1〜S3-6（マイルストーン・区間予算・骨組み） | ✅ | `analysis/sections.py` |
| S5-1 / TAD-3（XML 書き出しと取り込み） | ✅ | `rekordbox/xml_export.py` |
| S4-1〜S4-7（エージェント） | ✅ | `setagent/agent/` |
| S5-2（書き戻し前のプレビュー） | ✅ | `xml_export.export_preview` |
| 配布可能プロト化 | ✅ | 設定の永続化・初回起動の master.db 選択・rekordbox 起動中の検出・`doctor`・配布 zip |
| **UI フェーズ（WebView2 への載せ替え）** | ✅ | `setagent/webui/`（後述） |
| S6（オーバーレイ） | ✗ 保留 | rekordbox 7 は D3D12＋非共有 vtable でフックが当たらない（TAD-4/4b） |

### UI フェーズで入ったもの（2026-09-14）

```
setagent/webui/
  state.py    Draft + analysis -> JSON。純粋関数。フレーズ帯の時間変換はここ
  api.py      pywebview js_api。全呼び出しを単一ワーカースレッドに直列化
  app.py      エントリ（maximized で起動）
  index.html  UI 本体。素の JS / CSS。ビルド工程なし
tests/test_webui_state.py   12本（フレーズ帯のマッピングと「データなし」の扱い）
tools/probe_state.py    ウィンドウ無しで state を検算する
tools/probe_layout.py   起動してレイアウトの実測値を JSON で吐く（後述）
tools/probe_actions.py  UI を実際に操作して結果を読み返す（配線テスト）
tools/raise_window.py   スクショ用にウィンドウを一時的に最前面へ
```

新 UI に載っている操作（2026-09-15 時点）:

| 操作 | どこ | 検証 |
|---|---|---|
| 曲の選択 | TRACKS をクリック | ✅ probe_actions |
| **ドラッグで並べ替え** | TRACKS をドラッグ（5px でクリックと分岐） | ✅ probe_actions |
| プリセット変更 / テンポ / マイルストーン / ロック | 右下のインスペクタ | ✅ probe_actions |
| Undo / Redo | 上部バー | ✅ |
| **XML 書き出し**（プレビュー → 保存 → rekordbox 側の手順表示） | 上部バー | ✅ |
| **LLM キーの設定**（DPAPI で暗号化して settings.json へ） | 上部バー「設定」 | ✅ |
| ズーム3段階 / ミニマップ / 横スクロール | transport 行 | ✅ |
| **エージェント**（会話・候補・Change Set・ゴーストプレビュー・介入度） | 上部バー「エージェント」→ 右ドロワー | ✅ probe_agent |
| **再生範囲の端ドラッグ**（曲ブロックの左右7px を掴んで in/out を削る） | TRACKS | ✅ probe_trim |
| **目標カーブの編集**（制御点ドラッグ / ダブルクリックで追加 / 右クリックで削除） | ENERGY | ✅ probe_curve |
| **プロアクティブ通知**（介入度 proactive のとき、1ターン1件だけ） | ドロワー ＋ ボタンの未読ドット | ✅ |
| 曲ブロックのホバー詳細（位置・再生尺・BPM・プリセット・ロック・フレーズ内訳） | TRACKS の title | ✅ |

エージェントは **Tier 2 なのでドロワー**にした（常時は出ない、タイムラインは見えたまま）。
B-8 の境界はそのまま: `api.ask` は Change Set を返すだけで、`set_item_approved` で
チェックした操作だけが `apply_pending` → `History.run_all` を通る。
**チェックを外すとゴーストのブロック数が変わる**（S4-3 のプレビューが生きている証拠）。

入力欄の下のヒント文は **advisor の語彙に合わせて書いてある**（`HINTS` 定数）。
「区間に合う曲を探して」では候補が出ず「候補を出して」なら出る、という語彙依存があるので、
`advisor.py` の `*_WORDS` を変えたら `HINTS` も合わせろ。

決まったこと:

1. **プラットフォームは B（Web UI をローカルウィンドウ）** — pywebview 6.2.1 + WebView2。
   WebView2 は Windows 10/11 に標準搭載なので配布先で追加インストール不要。
   **ローカル HTTP サーバも JS のビルド工程も使っていない**（js_api で Python を直接呼ぶ、素の JS）。
2. **時間軸は DAW 方式** — 固定ピクセル密度（全体 3px/分・区間 36px/分・詳細 96px/分）＋
   横スクロール＋ミニマップ。旧 UI は 137分を795pxに圧縮していた（**1分5.8px**）。
3. **TRACKS 帯は rekordbox のフレーズ色で塗る。** 色相は rekordbox 7.2.14 の画面から
   ピクセル単位で採取し、この地色用に彩度と明度だけ上げてある（下表）。
4. **削り代は waterfall。** 「77:18 超過」と「-0:27」を並べて置いていたのをやめた。
5. tkinter 版は `--classic` で残してある。WebView2 が起動できない PC のための退路。

採取した rekordbox のフレーズ色と、実装で使っている色:

| フレーズ | rekordbox 実測 | Set Agent（再ステップ後） |
|---|---|---|
| INTRO | `#c83200` | `#c83201` |
| UP 1/2 | `#8c32ff` | `#8c32ff` |
| UP 3 | `#5a32ff` | （UP に統合） |
| DOWN / BRIDGE | `#9b732d` | `#955b00` |
| CHORUS（ドロップ） | `#10aa01` / `#00aa7d` | `#1fb013` |
| OUTRO | `#5f87af` | `#2f84cf` |
| VERSE | 未採取 | `#5a6270` |

この5色は dataviz の検証スクリプトで**明度帯・彩度下限・色覚特性の分離・通常視の分離・
コントラスト すべて PASS**（地色 `#14171c`）。**色相を変えるな** — 変えると rekordbox との
意味の一致が壊れる。彩度と明度は調整してよい。

---

## 4. 次にやること

### 4-1. UI フェーズの残り

**UI の移植は終わった。** 旧 tkinter 版にあった操作はすべて新 UI に載っている。残りはこれだけ:

| 項目 | 状態 |
|---|---|
| **LLM を実キーで通す** | **未検証。ここが最大の残り。** 鍵の保存（DPAPI）と `llm_config()` の解決は動いているが、実際に Anthropic API を叩いた経路は一度も通っていない。キーを入れて `ask` を投げ、ツールループが回ること、失敗時にアドバイザへ落ちることを確認しろ。**「キーが無くても全機能が動く」の裏面は誰も見ていない** |
| VERSE / BRIDGE の実色採取 | 未。検証に使った曲に出てこなかった。出る曲を rekordbox で開いて `grabscreen.ps1` でピクセルを読め |
| 削り代の拡張 / `lib.get_play_history`（共起統計） | 未着手（旧メモから継続） |

### 4-2. TAD-5（rekordbox へのワンアクション反映）— UI 実装の後と決定済み

**`rekordboxAgent.exe` が localhost:30001 で HTTP サーバを立てている。Express（Node.js）だ。**
`GET /` が Express 既定の "Cannot GET /" を返すことを 2026-09-14 に確認した。
設定は `%APPDATA%\Pioneer\rekordboxAgent\storage\options.json`（`["port","30001"]`）。
実体は `C:\Program Files\rekordbox\rekordbox 7.2.14\rekordboxAgent-win32-x64\`。

→ 配下の JS バンドルを grep してルート定義を洗い出せ。ライブラリ更新やプレイリスト作成を
叩ける口があれば、「書き出し → rekordbox 再起動 → トグル」の3手順がボタン1つになる。
無ければ現実解は settings 書き換え＋再起動の代行（要確認ダイアログ）。
`anthropic-skills:autonomous-investigation` の Fact/Inference/Assumption ラベルで報告しろ。

### 4-3. 後回しにしたもの

- **D-4 ユーザー検証（発案者以外の DJ 2人）** … UI が出来たので当てられる状態になった
- `lib.get_play_history`（共起統計）、削り代の拡張、S6 オーバーレイ（保留）
- 旧 tkinter 版の凡例下にあった操作ヘルプ行が、DPI 対応の副作用で画面外に出たまま
  （Tier 3 情報なので Web UI 側のショートカット一覧に移す前提で放置している）

---

## 5. 動かし方

```bash
# クラウド（tkinter も WebView2 も無い。ロジックのテストのみ）
cd /home/claude/setagent && python -m unittest discover -s tests -q

# PC（ここで GUI と exe）
cd /d C:\Users\7166700\source\my-project\set-agent
python -m unittest discover -s tests -q          # 151 tests
python -m setagent.webui.app acid                # 新 UI
python -m tools.probe_state acid                 # ウィンドウ無しで状態を検算する
python -m tools.probe_webview                    # WebView2 と bridge の疎通確認
python -m setagent.cli timeline "acid" --target 60:00 --preset one_drop --cap 32
python -m setagent.cli export  "acid" --preset one_drop --dry-run
python -m setagent.cli agent   "acid" --preset one_drop --ask "バランスどう？"

# 旧 tkinter 版（退路）
python -m setagent.gui.timeline
python -m tools.capture_gui <out.png> [playlist] [curve_key] [index:mm:ss ...]

# 配布物（テスト -> exe -> zip）
python build.py
dist\SetAgent.exe --playlist acid
dist\SetAgent.exe --classic
dist\SetAgent.exe --doctor
```

**新 UI は「スクショで確かめる」をやめろ。** WebView2 は別プロセスで描画するので
`tools/capture_gui.py` の PrintWindow は効かず、`SetForegroundWindow` は Windows に拒否され、
TOPMOST で持ち上げても Claude デスクトップのような別の常時最前面ウィンドウに負ける。
ここで時間を溶かすな。代わりに **view 自身に訊け**:

```bash
python -m tools.probe_layout acid    # 各レーンの top/height/画面内か、SVG が描けたか
python -m tools.probe_actions acid   # 実際に click / drag / change を発火して結果を読む
python -m tools.probe_agent acid     # 会話 -> 候補 -> Change Set -> ゴースト -> 適用
python -m tools.probe_trim acid      # 端ドラッグ: px -> ソース時間 ms の変換が合っているか
python -m tools.probe_curve acid     # カーブの制御点: 移動 / 追加 / 削除
```

いずれも `> out.txt 2>&1` にリダイレクトして `start /B cmd /c "..."` で投げ、
40〜60秒待ってからファイルを読め（ブリッジは60秒でタイムアウトする）。

どうしても絵が要るときだけ `python -m tools.raise_window` →
`powershell -File ..\grabscreen.ps1` → `python -m tools.raise_window release`。
（`grabscreen.ps1` は `SetProcessDPIAware` してから `CopyFromScreen` する。
PowerShell の `Add-Type` は 60秒を超えることがあるので、同じことは `raise_window.py` で ctypes でやれ）

実ライブラリ: 12 プレイリスト / 348曲。検証に使うのは `acid`（96曲、96曲すべてにフレーズ解析あり）。
期待値: 総尺 137:18 / 目標 60:00 / 差 +77:18 / 削り代 96件 合計 3:59.5。

---

## 6. 踏んだ地雷（同じ穴に落ちないこと）

- **js_api オブジェクトに公開属性で pywebview の Window を持たせるな。** pywebview は
  js_api の属性を走査して JS に公開しようとし、`.AccessibilityObject.Bounds.Empty.Empty…`
  を無限に辿って数百 KB のエラーを吐く。`api._window`（アンダースコア始まり）にしろ
- **端ドラッグはソース時間に戻して渡す。** タイムラインはセット時間（テンポ適用後）だが
  `SetRange` が取るのは曲のソース時間 ms。`deltaMs = (dx / pps) * 1000 * (set_tempo / bpm)`。
  テンポを変えた曲でこれを忘れると、見た目と実際の削り量がずれる
- **軽い操作エラーで全画面エラーに落とすな。** `apply()` は `fatal: true` が付いた
  boot / load の失敗だけカーテンを出し、それ以外（「提案がない」等）は toast にする。
  api 側で新しくエラーを返すときは、致命的なものにだけ `fatal` を付けろ
- **`Move` の第1引数は track_id（文字列）で、インデックスではない。** 他の Command は
  `e.track_id` を渡しているのに、ここだけ int を渡して黙って何も起きなかった。
  Command のシグネチャは推測せず `inspect.signature` で確認しろ
- **flex column の子に `min-height` を与えないと、中身がスクロールせず他を画面外へ押し出す。**
  ENERGY と SECTIONS（どちらも Tier 1）が丸ごと見えなくなっていた。
  `.scroll{flex:1 1 auto; min-height:330px}` と `.canvas{display:flex;flex-direction:column;
  min-height:100%}` + `.energy{flex:1 1 auto}` で、ENERGY が余った高さを吸う形にした。
  **レーンや固定高さブロックを足したら `probe_layout` で合計が viewport に収まるか必ず確認しろ**
- **pywebview の js_api は呼び出しごとに別スレッドで走る。** 復号済み master.db は SQLite
  接続で、作成スレッド以外から使うと `ProgrammingError` になる。`api.py` は全呼び出しを
  **単一ワーカースレッドに直列化**して回避している（`_SERIAL` / `_serialized`）。
  `rekordbox/` 側に `check_same_thread=False` を入れる誘惑に負けるな、変更禁止ラインだ
- **このPCは DPI 144（150%スケール）、物理1920x1200。** tkinter は DPI unaware だと
  1280x800 で描いて OS が1.5倍にボカす。`gui/timeline.py` は import 時に
  `SetProcessDpiAwareness(2)` を呼ぶようにした。**WebView2 側は何もしなくていい**
  （devicePixelRatio を自分で扱う）
- **DPI aware にすると pt 指定フォントの実ピクセルが1.5倍になり、px 直打ち座標のレイアウトが壊れる。**
  tkinter 側は実測ベース（`Canvas.bbox` / `Font.measure`）に直した
- **PyPI はクラウドから遮断されている**（プロキシ 403）が、**PC 側からは通る**。
  新しい依存は PC で入れてから `build.py` に反映しろ
- **ANLZ のファイル名は固定ではない**。再解析すると増える。**必ず DB の analysis_path を使う**
- **rekordbox 7 のローカル ANLZ は XOR マスクされていない**（6 以前と違う）
- **librosa の BPM 推定はこの音楽帯（128〜234）で信用できない**。BPM は必ず rekordbox 値
- **rekordbox XML の取り込み**: Preferences > Advanced > Database > rekordbox xml で指定 →
  **rekordbox を再起動**（起動時にしか読まない）→ 左アイコンレールで「Display rekordbox xml」をオン。
  取り込んだ曲をデッキに載せると「コレクション側に取り込むか」のダイアログが出る。
  **Yes でユーザーのライブラリが書き換わるので勝手に押さない**
- **rekordbox のフレーズ色はスキンの XML にもロケールにも無い**（rekordbox.exe 本体にある）。
  色が要るときは実機のスクショからピクセルを読め
- **`blocks()` は chorus 系のラベルを "drop" というクラス名に畳む。** `state.py` が返す
  `label` は "drop"、`group` が "chorus"。テストを書くときに間違えた
- **PowerShell をシェル経由で叩くと `$_` や `$p` が食われる**。複雑なものは `.ps1` / `.py` に書く
- **日本語を含む .bat は cmd が OEM コードページで読むので壊れる**
- **日本語 Windows のコンソールは cp932**。`cli.py` と `tools/probe_state.py` は stdout を utf-8 に付け替えている
- cmd の `findstr` に `<` や `>` を含むパターンを渡すとリダイレクトと解釈される

---

## 7. 設計上の約束（崩さないこと）

- 数値は必ず `analysis.*` から取る。LLM に暗算させない。**`webui/` も例外ではない**
  （`state.py` は reshape するだけで、自前の音楽的な数値を一つも作らない）
- 変更は必ず `Command` 経由で `History` に積む。手編集もエージェント提案も同じ道を通る
- エージェントは Draft を直接いじれない。Change Set を出すだけ
- ロックとマイルストーンの目標時刻は、提案の生成段階で守る
- **フレーズ解析が無い曲は「データなし」と明示する。中間値で埋めない。**
  UI では 45° のハッチで描く（色のチャネルを使わない）。`test_webui_state.py` が固定している
- エージェントの候補曲は `recommend.candidates` か `lib.search` が返した実在曲のみ。曲名を作らない
- LLM が落ちても壊れない。キーが無ければ決定的アドバイザに落ちる
- **他人の PC で最初の1回が全て。** 見つからない・読めないときは、黙って落ちずに理由と次の手を出す
  （新 UI の起動画面はこれを守っている。ライブラリが開けなければ理由と「もう一度ためす」を出す）
- 設定の読み書きは best-effort。壊れた settings.json でアプリが起動しないことがあってはならない
- 配布形態は単体 exe（インストール不要）を維持する。現在 21.8 MB
- **LLM キーは平文で保存しない。** `Settings.set_llm_key` が Windows の DPAPI で
  そのアカウントに紐づけて暗号化し、`dpapi:<base64>` として settings.json に入れる。
  DPAPI が使えない環境では平文に落ちるが、そのときは UI が警告を出す
- **書き出しの前に必ずプレビューを見せる。** `export_preview` は「46曲が渡り、50曲は渡らない」
  「マイルストーンとロックは rekordbox 側に概念が無いので渡らない」まで正直に言う。
  この正直さが道具の信用を作っている。黙って書き出すように変えるな

---

## 8. UI の判断基準（このフェーズで決めたこと）

**DJ が「精度・有効性」を判断できるかは UI のユーザビリティに大きく依存する。**
迷ったら「これは DJ が有効性を判断する材料になるか」で切れ。

画面に出ている情報は48項目あった。3段階に分けてある:

- **Tier 1 常時表示** — 目標との差 / 曲順と再生時間 / **フレーズ構成** / 展開の山谷 /
  区間の過不足 / 警告 / **フレーズ解析の有無**
- **Tier 2 要求したら出る** — カーブ編集 / 削り代 / エージェント / 区間の詳細 / Key
- **Tier 3 ホバー・詳細** — BPM / プリセット名 / ロックの内訳 / フレーズ構成の数値 / 凡例

旧 UI はこれが逆転していた（Tier 3 の BPM が曲ブロックの中、Tier 1 の差分が右上隅の14px）。
**新しい画面を足すときは、この分類のどこに入るかを先に決めろ。**

タイポグラフィは最低4段階（hero 56px / display / body 14px / caption 11px、字体は rekordbox と同じ Arial 系）、
テキスト色は3段階（`--ink` / `--ink-2` / `--ink-3`）。2段階に戻すな。
