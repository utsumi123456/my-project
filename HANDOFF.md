# Set Agent — 引き継ぎメモ

## 2026-09-16 追記 — read-only 方針で UI を 2 ビューに再編（新アカウント初日）

方針は `NEXT_ACCOUNT_HANDOFF.md` §1〜§4 のとおり（書き出し廃止・read-only・予測総尺が主役・
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
   **配布形態を変更（ユーザー指示）:** zip は廃止。`dist/` には `SetAgentTimeline.exe`（この PC で動く exe そのもの）と
   `はじめに.md` だけを置く。PyInstaller の出力は `build/exe/`。`はじめに.md` は 2 ビュー UI・自動追従・外す候補に
   合わせて書き直し、口調も です・ます に統一。
   起動スモーク: exe を起こして 20 秒後にウィンドウ「Set Agent」が出ることを確認して終了。
   実機での操作確認（サムネ・自動更新・提案）は未実施。
3. バーは 386px で 2 行に折り返す（98px）— 詰める余地あり。
4. 詳細ビューの TRACKS レーンやインスペクタにもアートワークを出すか（未着手）。

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
> 手元にあるなら `setagent_new/` に置け。無くてもこのファイルで作業は続けられる。

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
| GitHub `https://github.com/utsumi123456/my-project`（`main`） | **リモートの正本**（2026-09-16 から）。作業は PC で行い、区切りごとに push |
| PC `C:\Users\7166700\source\setagent\setagent_new\` | ソースの作業コピー。ここで編集・テスト・ビルドする |
| PC `…\setagent_new\dist\` | チームに渡すもの（`SetAgentTimeline.exe` ＋ `はじめに.md`）。git 対象外 |
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
cd /d C:\Users\7166700\source\setagent\setagent_new
python -m unittest discover -s tests -q          # 131 tests
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
dist\SetAgentTimeline.exe --playlist acid
dist\SetAgentTimeline.exe --classic
dist\SetAgentTimeline.exe --doctor
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

タイポグラフィは最低4段階（hero 38px / display / body 14px / caption 11px）、
テキスト色は3段階（`--ink` / `--ink-2` / `--ink-3`）。2段階に戻すな。
