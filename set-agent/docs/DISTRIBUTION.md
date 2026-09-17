# 他の PC への配布手順（2026-09-17）

チームの PC に Set Agent を入れて、動くことを確かめるまでの手順。配布物は **1 ファイル**で、
インストールは不要です。

## 1. 配布物の取り方

| OS | 何を渡すか | どこから |
|---|---|---|
| Windows 10/11 | `SetAgent.exe` ＋ `はじめに.md` | この PC の `set-agent\dist\`（`python build.py` の出力）か、GitHub Actions の artifact **SetAgent-windows** |
| macOS | `SetAgent-macOS.zip`（中に `SetAgent.app`）＋ `はじめに.md` | GitHub Actions の artifact **SetAgent-macos**（Windows からは Mac 版を作れないため） |

GitHub Actions は `main` への push ごとに両 OS でビルドします（`.github/workflows/build.yml`）。
`v1.0` のようなタグを push すると GitHub Release にも同じファイルが付きます。
artifact は リポジトリ → Actions → 最新の「build set-agent」→ Artifacts から取れます。

## 2. 相手の PC に必要なもの

- **rekordbox 6 または 7** が入っていて、一度起動してライブラリ（master.db）ができていること。
  検証済みは 7.2.14。最新 7.2.17 まで、リリースノート上はライブラリ形式の変更なし（未実機）。
- Windows: WebView2 ランタイム（Windows 10/11 に標準搭載。無ければ `--classic` で旧 UI が開く）。
- macOS: 追加なし（WKWebView を使う）。**未署名アプリ**なので初回は Gatekeeper に止められる。
  Finder で右クリック →「開く」、または `xattr -dr com.apple.quarantine SetAgent.app`。
- AI エージェントを使うなら **Claude Desktop に会社のアカウントでログイン**していること
  （API キーは不要。ログインが無ければルールベースのアドバイザで全機能が動く）。

## 3. 相手の PC でやること（順に 3 つ、5 分）

1. **互換性チェック**（ウィンドウなし。rekordbox の版・DB の復号・列・フレーズ解析・アートワークを確認）

   ```
   SetAgent.exe --compat
   ```

   すべて `PASS` なら次へ。`FAIL` があれば、その行と rekordbox の版を報告してください。
   ソースからなら `python -m tools.probe_compat`。基準値（この PC、7.2.14）は `docs/compat_baseline.json`。

2. **環境診断**（設定・作業フォルダ・プレイリスト数・フレーズ解析の割合）

   ```
   SetAgent.exe --doctor
   ```

3. **起動**して `はじめに.md` の手順どおりに触る。設定シートに Claude の接続状態が出ます。

## 4. 新しい rekordbox で確かめること

rekordbox を更新した PC では、次の順で見る。どれも書き込みはしない。

1. `--compat`: 復号（鍵・方式）、必要な列、BPM×100 と Length 秒の単位、PSSI フレーズの読み取り、
   アートワークの解決。**ここが通れば読み取り系はすべて動く。**
2. `--doctor`: フレーズ解析の割合。7.2.16 以降は Spotify 曲がコレクションに入るので、
   「クラウド保存 N 曲」が増え、その曲はフレーズ解析なし（斜線）になるのが正常。
3. 起動して acid 相当の大きなプレイリストを開き、rekordbox 側で 1 曲追加 → 5 秒以内に追従することを見る
   （-wal の読み取り。`tools/probe_refresh` と同じ観点）。

## 5. 分かっている制限

- macOS 版は **実機未検証**（このセッションは Windows。CI で .app は作れるが、動作確認は Mac が必要）。
  ソースは `sys.platform` で分岐しており、master.db の場所・`pgrep` による起動検出・Claude CLI の探索は
  mac 用の分岐がある。最初の Mac ユーザーは `--compat` と `--doctor` の結果を貼ってほしい。
- 生成したプレイリストを rekordbox に戻す手段は未決（XML 書き出しは凍結中）。
- Claude Code を組織で無効にしている PC では、設定シートに「未ログイン」と出てアドバイザで動く。
