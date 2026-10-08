# rekordbox との統合（2026-10-08）: 書き戻し・ドッキング・履歴

依頼: pyrekordbox（dylanljones/pyrekordbox）と rekordbox-mcp（davehenke/rekordbox-mcp）を
活用して、Set Agent を rekordbox の中に埋め込む。A（書き戻し）＋ B（ドッキング）＋ C（MCP 統合）を
Set Agent の設計思想に沿って実装した。

rekordbox にはプラグイン API がない。プロセスに入り込む方式（S6 overlay の DLL 注入＋D3D12 Present
フック）は更新のたびに壊れ、ライブラリと規約のリスクもあるので採らない。代わりに次の 3 つを組み合わせて、
「rekordbox の一部として使える」状態にした。

## 設計思想との整合

| 原則（spec） | この実装での扱い |
|---|---|
| B-2 Set Agent は rekordbox に書かない | **狭めて維持**。書くのは root の「Set Agent」フォルダ内のプレイリストだけ。曲・キュー・解析・他のプレイリストには触れない |
| B-8 エージェントは提案だけ | `rekordbox.propose_publish` は確認カードを出すだけ。書き込むのは DJ のボタン |
| B-7 LLM なしでも全機能 | 書き込み・ドッキング・履歴はすべてルールベースのアドバイザでも使える（「rekordbox に書き込んで」「履歴」） |
| 初回の他人の PC で壊れない | pyrekordbox は任意依存。無ければ書き込みだけが無効になり、理由を表示（`writeback.available()`） |
| 数値はツールから | 履歴・統計もツール（SQL）の値だけを返す |

## A. 書き戻し（`setagent/rekordbox/writeback.py`, `publisher.py`）

- 書き込み先: root の **Set Agent** フォルダ（無ければ作る）。同名のプレイリストがあれば中身を置き換え、
  無ければ作る。既定名は「元のプレイリスト名 (目標尺)」（例: `acid (60:00)`）。元のプレイリストとは名前が
  違うので、rekordbox のサイドバーでも Set Agent の一覧でも区別できる。
- 入るのは **曲順だけ**。再生範囲・テンポ・マイルストーンは Set Agent の中に残る（シートに明記）。
- 手順: rekordbox が対象の master.db を開いていないことを確認 → **バックアップ**（master.db・-wal・-shm・
  masterPlaylists6.xml を `app_home()/backups/<ms 付き時刻>/`、新しい 10 件）→ pyrekordbox で書き込み
  （USN 更新と masterPlaylists6.xml の同期は pyrekordbox が行う）→ **Set Agent 自身の復号器で読み戻し**、
  曲順が完全一致しなければ **その場でバックアップに戻す**。
- 起動中の扱い（`publisher.Publisher`）: 「今すぐ」（閉じているとき）／「rekordbox を閉じたら書き込む」
  （2 回続けて終了を確認してから。予約はこのプロセスの間だけ、ファイルに残さない）／「rekordbox を終了して
  書き込む」（終了 → 書き込み → 同じ rekordbox を再起動）。rekordbox が終了を拒んだら（未保存の確認ダイアログ
  など）書き込まず、強制終了は 2 回目の明示的な確認の後だけ。書き込みに失敗しても rekordbox は再起動する。
- 起動中かどうかは「rekordbox が使うその master.db か」で判定する。`SETAGENT_MASTER_DB` でコピーを
  指したときは対象外（開発・検証用）。
- 復元: 設定 →「rekordbox への書き込み」から任意のバックアップに戻せる。戻す直前の状態もバックアップする。
- `rbrestart` を Windows/macOS 両対応にし、`quit_app()` / `launch()` に分けた（macOS は osascript と `open -a`）。

## B. ドッキング（`setagent/webui/dock.py`）

- モード: **side**（rekordbox の右か左に付ける。画面に余地が無ければ inside）／**inside**（rekordbox の
  右端の内側に重ねる）／**split**（rekordbox を縮めて並べる。1 ウィンドウにつき 1 回だけ動かし、DJ が後で
  動かしても追いかけない）／**off**（従来の自由なパネル）。既定は side。設定から変更。
- 前面: rekordbox か Set Agent が最前面のときだけパネルを浮かせる（macOS は NSFloatingWindowLevel）。
  他のアプリの上には出ない。rekordbox が閉じる・隠れると通常のウィンドウに戻る。
- パネルを 40px 以上ドラッグするとドッキング解除（トースト）。ドック中に幅を変えるとその幅を覚える。
  OS による配置の微調整（メニューバー回避など）はドラッグと見なさない（配置後 2 tick は基準を取り直す）。
- 畳む（⇥）: 64px の帯に、予測時間と超過/不足だけを縦書きで出す。幅 300px 未満では CSS が自動でこの表示に
  切り替わる。帯は rekordbox の縁に沿う。
- 取得するのは幾何情報だけ。macOS は Quartz CGWindowList（権限不要）、Windows は EnumWindows＋DWM の
  可視フレーム。split で rekordbox を動かすときだけ、macOS はアクセシビリティ許可を求める。

## C. MCP 統合（`setagent/rekordbox/insights.py`, `agent/tools.py`）

rekordbox-mcp のツールを、Set Agent の読み取り専用の復号コピーへの SQL として再実装した（標準ライブラリだけ、
第 2 の DB スタックなし、書き込み権なし）。claude -p 用の自前 MCP サーバは `TOOL_SCHEMA` から自動で公開する。

| 追加・拡張したツール | 内容 |
|---|---|
| `lib.search`（拡張） | `compatible_with`（Camelot ±1 と平行調）・`genre`・`rating_min`・`unplayed`・`sort` |
| `lib.get_play_history`（実装） | 再生回数・セッション数・最後にかけた日・**直後／直前によくかけた曲** |
| `lib.get_track_details` | タグ・レーティング・再生回数・Camelot |
| `lib.get_stats` | 曲数・総時間・BPM 分布・ジャンル/キー上位・未再生数 |
| `history.get_sessions` / `history.get_session_tracks` | 過去のセッションとその曲順 |
| `rekordbox.get_playlists` | フォルダのパス付き一覧 |
| `rekordbox.publish_preview` / `rekordbox.propose_publish` | 書き込みの事前確認／確認カード |

履歴の共起（`HistoryIndex`）は `recommend.candidates` と `plan_fill_sections` のタイブレーカーにも使う
（直前の曲の後に DJ が実際にかけた曲に +0.1×min(回数,3)/3、理由に「過去のセットで直後にかけた N 回」）。
床（BPM・キー・尺）は変えないので、未再生の曲が不利になることはない。

## 検証（2026-10-08、MacBook-Pro / macOS 26.6 / rekordbox 7.2.19）

- テスト 249 件 OK（既存 216 ＋ 新規 33）。新規: `test_writeback`（rekordbox 7.2.19 の実スキーマで作った **SQLCipher 暗号化 DB**
  に対して: 作成・上書き・他プレイリスト不変・欠落/重複・起動中拒否・検証失敗時の復元・復元のバックアップ）、
  `test_publisher`（予約・取消・終了→書込→再起動・終了拒否で書かない・失敗しても再起動）、`test_dock`
  （配置計算と追従ループ: 追従・前面・ドラッグ解除・OS の微調整・split 1 回・許可なし・畳む・幅）。
- `tools.eval_agent acid`（実 Claude、企業アカウント・sonnet）**8/8 PASS**（新シナリオ publish / history を含む、
  平均 7.9 秒）。
- 実ライブラリの **コピー** に対して、`tools.webui_live` で本物の UI と API を通しで操作: 新規作成（96 曲）→
  エージェントの「60:00 に収めて」を適用（11 曲）→ 上書き。独立に復号して曲順一致・元の acid は 96 曲のまま・
  `integrity_check` ok・masterPlaylists6.xml にも反映を確認。
- ドッキング: 実機の rekordbox（1512×873、画面幅いっぱい）に対して inside に吸着（x=1052, 460×873）。
  Finder を前面にするとレベル 0、rekordbox を前面にするとレベル 3 に切り替わることを確認。
- PyInstaller の macOS バンドル（`dist/SetAgent-macOS.zip`、35 MB）に sqlcipher3・pyrekordbox を同梱し、
  バンドルからの起動とドッキングを確認。**macOS 版が実機で動いたのはこれが初めて。**

## 未検証・注意

- 本物のライブラリへの書き込みはまだ行っていない（rekordbox が起動中で、DJ の作業を止めないため）。初回は
  「rekordbox を終了して書き込む」か、rekordbox を閉じてから「書き込む」を DJ が押す。
- Windows 側（EnumWindows/DWM、SetWindowPos、taskkill 経路）はこの Mac では実行できない。Windows 機で
  `python -m unittest`、`--doctor`（「rekordbox へのドッキング」「rekordbox への書き込み」行）、ドッキングの
  目視確認をする。
- rekordbox の Cloud Library Sync を使っている場合、Set Agent フォルダのプレイリストも同期される
  （pyrekordbox が USN を正しく進めるため）。
