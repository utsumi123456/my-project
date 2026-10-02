# Changelog

## 1.0.0 — 2026-10-02

最初の公開版。

- BPM 検出（RhythmExtractor2013 multifeature ＋ ビート位置の回帰補正 ＋ degara 法との照合 ＋ オンセット密度による倍テンポ補正）
- Key 検出（edmm と temperley の2プロファイル投票、相対調は temperley の累積票で決定）、僅差の第2候補を表示
- Camelot / Open Key / 音名の表記切替、平滑化 3 段階（設定は Live セットに保存）
- 検出 BPM の Live テンポへの反映、`×2` / `÷2` 候補の切替
- クリップ名への `[Key BPM]` タグ書き込み
- 単一ファイルの凍結 `.amxd` として配布（Max を使わずに生成）
- 精度（rekordbox の解析値 155 曲基準）: BPM 71.6% / 候補込み 85.2%、Key 60.0% / 互換込み 78.1%
