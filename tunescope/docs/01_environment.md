# 01. Max × Claude 連携環境の構築（Windows）

## 結論（推奨構成）

**「ファイルベース開発 ＋ MaxMSP-MCP-Server（ライブ検証用）」の2層構成** を推奨する。

| 層 | 手段 | 役割 |
|---|---|---|
| 実装層 | Claude が `.maxpat` / `.js` / node.script 用 JS をテキストとして直接生成・編集 | パッチの本体開発。`.amxd` は JSON なので Claude が完全に読み書き可能（Sc0pe v2 の解析で実証済み） |
| 検証層 | [tiianhk/MaxMSP-MCP-Server](https://github.com/tiianhk/MaxMSP-MCP-Server)（Windows対応・Python + Max内 js で通信） | Max 上のパッチ状態の読み取り・オブジェクト操作・公式ドキュメント参照・デバッグ |

### なぜこの構成か
- **MaxMCP（signalcompose 版・C++ external）は現状 macOS 13+ 専用**。Windows 対応は「Phase 4」のロードマップ止まりで、このマシンでは使えない。
- tiianhk 版は Python + Max の js オブジェクト経由で通信するため Windows で動作する。ただしパッチ全体の生成はレイアウトが乱れやすいので、**本体はファイル直接編集、MCP はライブ検証・デバッグに限定**するのが精度が高い。
- Sc0pe v2 が実証しているとおり、**UI を jsui 1枚 + 外部 .js ファイル**に寄せれば、開発の大部分は「Claude が JS を書く → Max が自動リロード（`autowatch`）→ 目視確認」という高速ループになり、パッチ編集の必要性自体が激減する。

## セットアップ手順

### Step 1: プロジェクトフォルダ構成

```
bpm-key-detector/
├── device/
│   ├── BPMKey_1.0.0.amxd        # Max for Live デバイス本体（凍結前は .maxpat でも可）
│   ├── BPMKey_UI.js             # jsui 描画スクリプト（Sc0pe 方式）
│   └── node/
│       ├── analyzer.js          # node.script 解析エンジン（essentia.js）
│       └── package.json
├── docs/                        # 本仕様書群
└── test/                        # テスト音源・検証ログ
```

### Step 2: MaxMSP-MCP-Server の導入（Windows）

```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
git clone https://github.com/tiianhk/MaxMSP-MCP-Server.git
cd MaxMSP-MCP-Server
uv venv && uv pip install -r requirements.txt
python install.py --client claude
```

Max 側は同梱の `demo.maxpat` 内の通信サブパッチ（js ベース）を開発用パッチにコピーし、`npm install` を実行。**M4L デバイスを Max エディタで開いた状態なら、そのパッチにも接続できる**。

### Step 3: node.script 環境（解析エンジン用）

```bash
cd device/node
npm init -y
npm install essentia.js
```

Node for Max は Windows の Max 9 / Live 12 Suite に標準搭載。追加インストール不要。

### Step 4: ビルド（凍結）までのループ

1. Claude が `analyzer.js` / `BPMKey_UI.js` / パッチ JSON を編集
2. Max で開いているパッチは `autowatch = 1` で JS を自動リロード
3. MCP 経由でパッチ状態・Max コンソールのエラーを確認
4. 完成後、Max エディタで **File → Freeze Device**（依存 JS / node フォルダを .amxd に同梱）→ `.amxd` 保存
   - 凍結自体は Max の GUI 操作（自動化不可）だが、それ以外の全工程は Claude 側で完結する

## 追記（2026-09-30）: 「このセッションから自前MCPを立てる」案の評価

**結論: フルMCPサーバーの自作は不採用、ただし軽量版を第3の層として採用。**

- フル自作（パッチ解析・オブジェクト操作込み）= tiianhk 版の再実装であり、デバイス本体より工数が大きくなるため合理性なし。
- ただし解析エンジンで **node.script を常駐させる前提**なので、そこに小さな **HTTP 開発ブリッジ**（~100行）を同居させれば、Claude Code から `curl` で直接 (1) Max コンソールログ取得 (2) デバイスへのテストメッセージ送信 (3) 解析状態の照会 ができる。MCP 登録不要・Windows ネイティブ・依存ゼロ。
- 実装タイミング: M2 の実機デバッグで必要になった時点（YAGNI）。それまではファイルベース＋目視で十分。

## 補足: 検討した代替案

| 手段 | 判定 | 理由 |
|---|---|---|
| MaxMCP (signalcompose) | ✕ | macOS 専用（Windows は将来対応） |
| Producer Pal (Node for Max 製 MCP) | △ | Live のクリップ/トラック操作向け。パッチ開発用ではないが、**クリップ自動リネーム機能の実装参考**として有用 |
| ファイル直接編集のみ | ○ | 確実だが Max 側の状態が見えない。MCP 併用で補完 |
