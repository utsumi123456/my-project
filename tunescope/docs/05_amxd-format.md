# 05. .amxd ファイルフォーマット仕様（リバースエンジニアリング結果）

Max/Live の GUI なしで M4L デバイスを生成・凍結するために解読した仕様。
検証: Sc0pe_2.0.0（凍結・バイト単位再現に成功）、Producer Pal v2.3.0（node.script入り凍結）、
fourin_fourout（非凍結）、および TuneScope での実機ロード・動作確認（Live 12.4.6 / Max 9）。

## コンテナ（IFF風、サイズは u32 リトルエンディアン）
```
'ampf' u32le(4)  'aaaa'
'meta' u32le(4)  u32le(7)            ; 7=オーディオエフェクト系で確認（fourinは0でも可）
'ptch' u32le(N)  <ptchデータ N bytes>
```

## ptch データ
- **非凍結**: 生JSON + NUL 終端のみ（mx@c なし）。依存はデバイスと同フォルダ＋Max検索パスで解決
- **凍結**: `mx@c ヘッダ(16B) + デバイスJSON + 依存ファイル連結 + dlst フッター`

### mx@c ヘッダ（16バイト）⚠️最重要
```
'mx@c'  u32be(16)  u32be(0)  u32be(dlstオフセット)
```
- 第4フィールドは **dlst の位置（ptch データ先頭基準）**。
- 罠: Sc0pe ではこの値 0x00026774 の下位2バイトが ASCII "gt" に見えるため、
  固定タグと誤読しやすい。誤ると Live は「error -1 making directory /
  CreateDevice error 6: Device file broken」で拒否する。

### dlst フッター（チャンクは 4cc + u32be サイズ[8バイトヘッダ込] + ペイロード、BE）
```
dlst > dire × N（ファイルごと）
  dire > type  : 'JSON'(デバイス本体/maxpat) | 'TEXT'(js/html等) | 'svg '等
         fnam  : ファイル名（NUL終端 + 4バイト境界パディング）
         sz32  : ファイルサイズ（u32be）
         of32  : ptch先頭基準オフセット（u32be）
         vers  : 0
         flag  : デバイスJSON=0x11 / 通常依存=0 / **node.scriptのスクリプト=0x8**
         mdat  : HFS時刻（unix秒 + 2082844800）
```
- 先頭 dire は必ずデバイス自身（type JSON、of32=16、fnam=デバイスファイル名）
- デバイスJSON は **NUL 終端込みで sz32 に含める**
- ファイル間パディングなし（連結のみ）

### node.script を含むデバイスの凍結
- スクリプトエントリに **flag 0x8** が必須（なしだと「node.script: couldn't generate path」）
- node_modules のフォルダ同梱はせず、**esbuild で単一ファイルにバンドル**するのが実務解
  （Producer Pal も同方式: 5.2MB の単一 .mjs）
- 本プロジェクトでは worker_threads 用の第2ファイルも避けるため、ワーカーバンドルを
  文字列としてスクリプト先頭に埋め込み `new Worker(src, { eval: true })` で起動

## ツール（device/ 配下）
| ファイル | 役割 |
|---|---|
| build-amxd.js | 非凍結 amxd 生成（開発用） |
| build-frozen.js | **凍結 amxd 生成（リリース用、Max不要）** |
| parse-frozen.js | 凍結 amxd のパース・内容照合 |
| amxd-oracle.ps1 | スタンドアロンMax（未ライセンス可）で開きロード成否を自動判定 |

## 制約・注意
- スタンドアロン Max は単体起動では「saving disabled」（GUI の Freeze も不可）＝本ツール群の存在意義
- 本仕様は Live 12.4.x / Max 9 での動作確認に基づく。将来の形式変更に注意
