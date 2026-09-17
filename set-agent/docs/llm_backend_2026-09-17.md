# AI エージェントの接続方式 — API キー以外の経路の検討（2026-09-17）

## 0. 結論

**Claude Code CLI の headless モード（`claude -p`）を Set Agent から子プロセスとして呼び、
ツールは Set Agent 自身が立てるローカル MCP サーバで渡す。** 認証は CLI が持つ
claude.ai の OAuth ログイン（エンタープライズ契約の席）をそのまま使うので、API キーは不要。

この PC で実測して全経路が通ることを確認した（§3）。Claude Desktop（企業アカウントで
ログイン済み）が入っている PC なら、CLI 本体も Desktop に同梱されているため追加インストール
も追加ログインも要らない。

## 1. 要求（ユーザー提示、2026-09-17）

必須
- AI エージェントを Set Agent の一機能として使えること
- 解析データを基に、現段階で実装予定の機能（相談・提案・候補出し → Change Set）を実現できること
- 他の PC（Claude エンタープライズ契約アカウント）でも確実に導入できること

理想（優先順）
0. 実装・検証が Claude の行うアクションで完結する
1. ユーザー側が能動的な操作をせずに各 PC へ導入できる
2. 応答が 1〜30 秒に収まる
3. 高度な出力（モデルの選択）

制約: API キー方式はエンタープライズの管理者制限で取得できない可能性がある。

## 2. 候補の比較

| # | 方式 | 認証 | 必須 3 点 | 理想 0 | 理想 1 | 理想 2 | 理想 3 | 判定 |
|---|---|---|---|---|---|---|---|---|
| A | Anthropic API（現行 `llm.py`） | API キー | キーが取れなければ不可 | ○ | × キー配布が要る | ○ | ○ | 保険として残す |
| **B** | **Claude Code CLI headless（`claude -p`）＋ローカル MCP** | **claude.ai OAuth（企業の席）** | **○** | **○** | **◎ Desktop 同梱 CLI を自動検出** | **○ 4〜8 秒実測** | **○ sonnet / opus 選択可** | **採用** |
| C | Claude Agent SDK（Python） | 同上 | ○ | ○ | ○ | ○ | ○ | B と同じ経路を 100 MB の wheel で包むだけ。exe が 28→130 MB になるので不採用 |
| D | Set Agent を MCP サーバにして Claude Desktop 側で会話 | 同上 | × 「Set Agent の一機能」にならない | ○ | △ Desktop に MCP 設定が要る | ○ | ○ | 補助経路としては可 |
| E | ローカルモデル（Ollama 等） | 不要 | △ 品質・GPU 依存、社内 PC への導入可否が不明 | △ | × インストールが要る | △ | × | 不採用 |
| F | ルールベースの Advisor（既存） | 不要 | 提案の幅が限られる | ○ | ◎ | ◎ | × | フォールバックとして維持 |

B と C は同じ仕組み（SDK は CLI を内包して呼ぶ）。依存を増やさず、既存の「素の urllib、SDK なし」の
方針に沿うのは B。

## 3. この PC での実測（2026-09-17、Claude Code 2.1.273 / Desktop 同梱 2.1.271）

| 確認したこと | 結果 |
|---|---|
| CLI の認証状態 | `authMethod: claude.ai`、`subscriptionType: enterprise`、API キー無し |
| headless 呼び出し（sonnet、ツール無し、構造化出力 `--json-schema`） | 4.5 秒、`structured_output` が返る |
| Set Agent 起動時と同じクリーン環境（環境変数を空にして実行） | 4.5 秒、成功 |
| 自前の **stdio** MCP サーバ（依存なし、40 行）でツール呼び出し | 5.7 秒、`initialize → tools/list → tools/call` が到達 |
| 自前の **streamable HTTP** MCP サーバ（stdlib `http.server`、127.0.0.1） | 7.9 秒、同上。Set Agent のプロセス内で完結できる |
| opus | 5.0 秒、`claude-opus-5` で応答 |
| Desktop 同梱 `%APPDATA%\Claude\claude-code\<ver>\claude.exe` を直接呼ぶ | 同じログインで成功、3.6 秒 |
| 資格情報の置き場 | `%USERPROFILE%\.claude\.credentials.json`。どのビルドの claude.exe からも共有される |
| `--bare` | 使わない。OAuth を読まず API キー限定になる（「Not logged in」で失敗した） |
| stdin | `< /dev/null` 相当で閉じて渡す（開いたままだと 3 秒待って警告） |
| 参考コスト表示 | 1 ターン 0.006 USD 前後（席の契約内。請求されるものではなく目安） |

## 4. 採用方式の設計

```
Set Agent (pywebview, Python)
 ├─ webui/api.py  ask() ──► agent/llm.py  LLMAgent
 │                            ├─ backend 1: ClaudeCliBackend   ← 新規
 │                            ├─ backend 2: ApiBackend (現行 urllib)  ← 保険
 │                            └─ fallback : Advisor (ルールベース)
 └─ agent/mcp_server.py  ← 新規。127.0.0.1 の空きポートに streamable HTTP MCP
      tools/list  = TOOL_SCHEMA を MCP 形式に変換（名前の "." は "_" に。MCP は [A-Za-z0-9_-] のみ）
      tools/call  = AgentTools.call(...) を api の単一ワーカーで実行（SQLite はスレッド固定）
      set_propose_changes は従来どおり on_proposal に Change Set を積む（B-8 の境界は不変）

ClaudeCliBackend.ask(text):
  claude -p --model <sonnet|opus> --output-format json
         --system-prompt <SYSTEM_PROMPT> --setting-sources "" --strict-mcp-config
         --mcp-config {"mcpServers":{"setagent":{"type":"http","url":"http://127.0.0.1:<port>/mcp"}}}
         --allowedTools "mcp__setagent__*" --tools "" --max-turns 8
         --session-id <uuid>（初回） / --resume <uuid>（2 回目以降。会話が続く。実測で確認）
         <text>          (stdin は閉じる。CREATE_NO_WINDOW。timeout 60 秒)
  → result(JSON).result を本文に、積まれた Change Set と使ったツール名を Reply に。
```

CLI の探索順（見つかった最初のものを使い、設定シートで上書き可）
1. `Settings.claude_exe`（手で指定したもの）
2. `%APPDATA%\Claude\claude-code\<最新版>\claude.exe`（Claude Desktop 同梱 — 企業 PC の標準経路）
3. `%USERPROFILE%\.local\bin\claude.exe`（ネイティブインストーラ）
4. PATH 上の `claude` / `claude.cmd`（npm）

起動時に `claude auth status` を 1 回だけ実行してキャッシュ（loggedIn / subscriptionType / 版）。
設定シートに「Claude Code（企業アカウント）: 接続中 / 未ログイン / 見つかりません」を出し、
未ログインのときだけ「ログイン」ボタン（`claude auth login` をコンソールで起こす）を出す。

フォールバック順: CLI（ログイン済み）→ API キー（設定されていれば）→ Advisor。
どの段で動いているかはドロワーの status 行に常に出す（現行の `status()` を拡張）。

### 要求との対応

| 要求 | 対応 |
|---|---|
| Set Agent の一機能 | ドロワーの UI・Change Set・undo はそのまま。裏の backend が替わるだけ |
| 解析データを基に実装予定の機能 | ツール定義（`agent/tools.py`）を MCP で同じまま渡す。数値は analysis.* から（§7 の約束は維持） |
| 他 PC で確実に導入 | Claude Desktop ＋ 企業アカウントのログインがあれば追加作業なし。CLI 無し／未ログインは設定シートで理由と次の手を出す（「他人の PC で最初の 1 回が全て」） |
| 理想 0 | 実装・単体テスト（`claude` のスタブ）・実機 probe（`tools/probe_llm`）まで Claude の操作で完結 |
| 理想 1 | 能動操作は「Desktop へのログイン」だけ。既にしているなら 0 |
| 理想 2 | 実測 4〜8 秒（ツール 1 回）。ツール 3〜4 回でも 30 秒以内の見込み。timeout 60 秒で Advisor へ |
| 理想 3 | `--model sonnet|opus` を設定シートで選択（既定 sonnet。opus は遅く、席の上限を早く使う） |

## 5. リスクと対処

- **組織の管理者が Claude Code を無効にしている PC** — `auth status` が loggedIn=false や
  エラーになる → 明示して Advisor へ。本 PC の org では有効（この検証自体がその上で動いている）。
- **席の利用上限（rate limit）** — 応答 JSON の `is_error` と本文で判別できる。上限時は Advisor に落ち、
  本文に「上限のため」と出す。
- **CLI の版差** — 使うフラグ（`-p --output-format json --mcp-config --strict-mcp-config
  --allowedTools --tools --system-prompt --setting-sources --max-turns`）は 2.1 系で確認。起動時に
  `--version` を読み、想定より古ければ status に出す。
- **ユーザーの CLAUDE.md・hooks・プラグインの混入** — `--setting-sources ""` と `--system-prompt` で遮断
  （実測で確認。応答に他プロジェクトの文脈は出ていない）。
- **コンソールの点滅** — GUI exe から子プロセスを起こすときは `CREATE_NO_WINDOW`（HANDOFF の地雷）。
- **セッションファイルの蓄積** — 会話継続に `--resume` を使うため persistence は許す。cwd を
  `%LOCALAPPDATA%\SetAgent\claude` にしているので、セッションは `~/.claude/projects/` のその cwd 用の
  フォルダにだけ溜まる。消えていれば（`No conversation found`）新しいセッションで自動的にやり直す。
- **送信内容** — 曲名・BPM・キー・尺がプロンプトとツール結果として Anthropic へ渡る。個人の API キーより
  企業契約の経路のほうが管理上は望ましい。音声ファイルや master.db 本体は送らない。

## 6. 検証結果（2026-09-17 実装）

- 単体テスト 175 件 OK（新規 18 件 `tests/test_llm_cli.py`: `tests/fake_claude.py` が CLI を偽装し、
  ToolServer のプロトコル・ワーカースレッドでのツール実行・引数組み立て・`--resume`・失敗時の Advisor 降格・
  timeout・セッション消失時の再開を固定）。
- `python -m tools.probe_llm acid`（実 CLI、Desktop 同梱 2.1.271、企業アカウント、sonnet）:
  1 ターン目「収まっていますか」7.1 秒、ツール 1 回、137:18 / 60:00 / 77:18 超過を正しく引用。
  2 ターン目「提案を 1 件」36.5 秒、ツール 3 回（trim_candidates → sections → propose_changes）、
  Change Set 4 件（137:18 → 106:16）。`--resume` で 1 ターン目の文脈（「その分」）が通じた。
- 2 ターン目は理想 2（30 秒）を 6 秒超えた。ツール回数と推論量に比例する。`--max-turns 8` のまま様子見。

### 当初の検証計画

1. 単体テスト: `claude` を偽装するスタブスクリプト（引数を記録し、固定 JSON を返す）で
   backend の引数組み立て・JSON 解釈・timeout・フォールバックを固定。MCP サーバは `http.client` で
   `initialize / tools/list / tools/call` を直接叩いてテスト。
2. `tools/probe_llm acid`: 実 CLI で `ask("60:00 に収めて")` → Change Set が返り、ツールが 2 回以上
   呼ばれ、30 秒以内であることを確認。
3. `tools/probe_agent acid`: ドロワー → 提案 → チェック → 適用 → undo が CLI backend でも同じ。
4. exe: `python build.py` → 設定シートに「Claude Code（企業アカウント）: 接続中」が出ること。

## 7. 検証に使ったもの

- `docs/mcp_http_min_probe.py` — streamable HTTP MCP サーバ最小実装（stdlib のみ）。§3 の HTTP 行はこれで通した。実装のたたき台になる
- stdio 版の最小実装（40 行）も同じ手順で通ったが、採用は HTTP 版なのでリポジトリには残していない
