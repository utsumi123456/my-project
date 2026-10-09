---
name: set-agent-sources
description: Set Agent（set-agent/）の実装で使った外部 GitHub ソースの一覧と、各ソースをどのファイルで何に使ったか。rekordbox の master.db・ANLZ・書き戻し・MCP ツールを触る前、依存を更新する前、rekordbox の新バージョン対応や出典を問われたときに使う。
---

# Set Agent が依拠した GitHub ソース

2026-10-09 時点で `set-agent/` のコード・docs・requirements から特定したもの。
新しいソースを取り込んだら、この表に足すこと。

## 中核（rekordbox との連携そのもの）

| ソース | 使い方 | 取り込み方 | Set Agent 側のファイル |
|---|---|---|---|
| [dylanljones/pyrekordbox](https://github.com/dylanljones/pyrekordbox) | rekordbox への書き戻し（「Set Agent」フォルダのプレイリスト作成・上書き、USN 更新、masterPlaylists6.xml の同期、起動中チェック `pyrekordbox.utils.get_rekordbox_pid`） | **依存ライブラリ**（`pyrekordbox==0.4.4`、任意依存。無ければ書き込みだけ無効） | `setagent/rekordbox/writeback.py`, `publisher.py`, `tests/test_writeback.py` |
| [davehenke/rekordbox-mcp](https://github.com/davehenke/rekordbox-mcp) | ツール群（検索・再生履歴・曲詳細・統計・セッション・プレイリスト一覧）を参考にした | **コードは取り込まず再実装**。読み取り専用の復号コピーへの SQL として、標準ライブラリだけで書き直した | `setagent/rekordbox/insights.py`, `setagent/agent/tools.py`（`lib.search` 拡張, `lib.get_play_history`, `lib.get_track_details`, `lib.get_stats`, `history.*`, `rekordbox.get_playlists`, `rekordbox.publish_preview/propose_publish`） |
| Deep Symmetry「DJ Link Ecosystem Analysis」（[Deep-Symmetry/dysentery](https://github.com/Deep-Symmetry/dysentery) の解析ドキュメント、実装は [Deep-Symmetry/crate-digger](https://github.com/Deep-Symmetry/crate-digger)） | ANLZ ファイルのレイアウト（PQTZ ビートグリッド、PSSI フレーズ構造とそのマスク解除、ムード別フレーズラベル） | **仕様として参照**し、自前パーサを実装 | `setagent/rekordbox/anlz.py` |

経緯の一次資料: `set-agent/docs/rekordbox_integration_2026-10-08.md`
（依頼文「pyrekordbox（dylanljones/pyrekordbox）と rekordbox-mcp（davehenke/rekordbox-mcp）を活用して…」）。

### 補足
- master.db の復号（`tools/decrypt_masterdb.py`）は pyrekordbox を使わない純 Python 実装。
  SQLCipher 4 の既定値（PBKDF2 256,000 回、4096 B ページ、reserve 80 B）と、
  コミュニティで周知の rekordbox 6/7 共通パスフレーズを使う。WAL リプレイも自前。
- 推薦スコアの形（`agent/recommend.py`）は Flow Map（社内仕様 C-7）由来で、GitHub ソースではない。

## 一般ライブラリ（`set-agent/requirements.txt`）

| ライブラリ | GitHub | 用途 |
|---|---|---|
| pywebview 6.2.1 | [r0x0r/pywebview](https://github.com/r0x0r/pywebview) | パネル UI（WebView2 / WKWebView） |
| sqlcipher3 | [coleifer/sqlcipher3](https://github.com/coleifer/sqlcipher3) | pyrekordbox 経由の暗号化 DB 書き込み、テスト用暗号化 DB |
| cryptography 50.0.1 | [pyca/cryptography](https://github.com/pyca/cryptography) | 自前の SQLCipher ページ復号 |
| segno 1.6.6 | [heuristicus/segno](https://github.com/heuristicus/segno) | iPhone で開くための QR コード |
| Pillow 12.3.0 | [python-pillow/Pillow](https://github.com/python-pillow/Pillow) | 画像（アートワーク等） |
| PyInstaller 6.22.2 | [pyinstaller/pyinstaller](https://github.com/pyinstaller/pyinstaller) | exe / .app のビルド（`build.py`） |
| pythonnet / clr_loader（Win） | [pythonnet/pythonnet](https://github.com/pythonnet/pythonnet) | pywebview の Windows バックエンド |
| pyobjc-*（mac） | [ronaldoussoren/pyobjc](https://github.com/ronaldoussoren/pyobjc) | WKWebView、Quartz のウィンドウ列挙、AX によるドッキング |

## CI（`.github/workflows/build.yml`）
`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`, `softprops/action-gh-release@v2`。

## 使い方の注意
- rekordbox の新バージョン対応では、まず pyrekordbox と crate-digger / Deep Symmetry ドキュメントの更新
  （master.db の鍵・スキーマ、ANLZ/PSSI の変更）を確認してから `python -m tools.probe_compat` を回す。
- pyrekordbox のバージョンを上げるときは `tests/test_writeback.py`（実スキーマの SQLCipher DB）で確認する。
- rekordbox-mcp からは**コードをコピーしない**方針（SQL 再実装・第 2 の DB スタックを持たない・書き込み権なし）を維持する。
