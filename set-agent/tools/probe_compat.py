"""rekordbox compatibility report -- run this on any PC, any rekordbox version.

  python -m tools.probe_compat [--baseline docs/compat_baseline.json] [--write-baseline] [--sample N]
  SetAgent.exe --compat                (the same report from the packaged exe)

Set Agent reads rekordbox's library directly (encrypted master.db + -wal, the
ANLZ files with PSSI phrase data, the artwork cache). Each of those is an
assumption about a rekordbox version; this checks every one of them against
the installed rekordbox and prints PASS / FAIL per assumption with the reason,
so a newer rekordbox (or a teammate's machine) can be verified in one run
without a window. With --baseline it also compares against the numbers recorded
on the reference machine (7.2.14, 2026-09-17).

Nothing is written to rekordbox. Exit code 0 = all checks pass, 1 = a check
failed, 2 = could not even find rekordbox.
"""
from __future__ import annotations

import glob
import json
import os
import platform
import plistlib
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# What the reader (setagent/rekordbox/masterdb.py) actually selects. A missing
# table or column here breaks a query; a renamed one is what a rekordbox
# upgrade would change first.
REQUIRED = {
    "djmdContent": ["ID", "Title", "ArtistID", "KeyID", "BPM", "Length", "AnalysisDataPath", "Analysed",
                    "FolderPath", "FileType", "ImagePath", "rb_local_deleted"],
    "djmdArtist": ["ID", "Name"],
    "djmdKey": ["ID", "ScaleName"],
    "djmdPlaylist": ["ID", "Name", "Attribute", "Seq", "rb_local_deleted"],
    "djmdSongPlaylist": ["PlaylistID", "ContentID", "TrackNo", "rb_local_deleted"],
}
EXPORT_OPTIONAL = {"djmdContent": ["ComposerID", "RemixerID", "AlbumID", "GenreID", "LabelID", "FileNameL",
                                   "FileSize", "DiscNo", "TrackNo", "ReleaseYear", "DateCreated", "BitRate",
                                   "SampleRate", "Commnt", "DJPlayCount", "Rating"],
                   "djmdAlbum": ["ID", "Name"], "djmdGenre": ["ID", "Name"], "djmdLabel": ["ID", "Name"]}


class Report:
    def __init__(self):
        self.rows: list[tuple[str, bool | None, str]] = []
        self.data: dict = {}

    def add(self, name: str, ok: bool | None, detail: str = ""):
        self.rows.append((name, ok, detail))
        mark = "PASS" if ok else ("FAIL" if ok is False else "info")
        print(f"[{mark:4s}] {name}: {detail}")

    @property
    def failed(self) -> bool:
        return any(ok is False for _, ok, _ in self.rows)


def rekordbox_version() -> tuple[str, str]:
    """(version, where) from the installed program; '' if not found."""
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for d in sorted(glob.glob(os.path.join(base, "rekordbox", "rekordbox *"))):
                m = re.search(r"rekordbox (\d+(?:\.\d+)+)", d)
                exe = os.path.join(d, "rekordbox.exe")
                if m and os.path.isfile(exe):
                    return m.group(1), exe
    elif sys.platform == "darwin":
        for app in sorted(glob.glob("/Applications/rekordbox*/rekordbox*.app")) + \
                   sorted(glob.glob("/Applications/rekordbox*.app")):
            try:
                with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
                    v = plistlib.load(f).get("CFBundleShortVersionString", "")
                if v:
                    return v, app
            except Exception:
                continue
    return "", ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sample = 200
    baseline_path = None
    write_baseline = "--write-baseline" in argv
    if "--sample" in argv:
        sample = int(argv[argv.index("--sample") + 1])
    if "--baseline" in argv:
        baseline_path = Path(argv[argv.index("--baseline") + 1])
    elif not write_baseline:
        default = Path(__file__).resolve().parent.parent / "docs" / "compat_baseline.json"
        baseline_path = default if default.exists() else None

    r = Report()
    r.add("実行環境", None, f"{platform.system()} {platform.release()} / Python {platform.python_version()}"
          + (" / 単体exe" if getattr(sys, "frozen", False) else ""))
    ver, where = rekordbox_version()
    r.add("rekordbox の版", bool(ver) or None, f"{ver or '見つかりません'}  {where}")
    r.data["rekordbox_version"] = ver

    from setagent.rekordbox.library import (Library, LibraryNotFound, PhraseStatus, find_master_db,
                                            pending_wal_bytes, rekordbox_running)
    try:
        mdb = find_master_db()
    except LibraryNotFound as ex:
        r.add("master.db", False, str(ex))
        return 2
    r.add("master.db", True, f"{mdb} ({mdb.stat().st_size / 1e6:.1f} MB)")
    r.add("rekordbox 起動中", None, str(rekordbox_running()))
    r.add("-wal の未反映分", None, f"{pending_wal_bytes(mdb) // 1024} KB")

    # --- decrypt (+ WAL replay) ------------------------------------------------
    try:
        t0 = time.time()
        lib = Library.open(master_db=str(mdb))
        dt = time.time() - t0
        wr = lib.wal_replay
        frames = getattr(wr, "frames_applied", getattr(wr, "frames", None)) if wr else None
        r.add("復号（ページ HMAC 検証つき）", True, f"{dt:.1f} 秒" + (f" / WAL {frames} フレーム" if frames is not None else ""))
    except Exception as ex:
        r.add("復号", False, f"{type(ex).__name__}: {ex}  ← 暗号鍵か方式が変わった可能性")
        return 1

    # --- schema --------------------------------------------------------------
    con = sqlite3.connect(str(lib.plain_db))
    try:
        ok = con.execute("pragma integrity_check").fetchone()[0]
        r.add("integrity_check", ok == "ok", str(ok))
        tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
        r.data["tables"] = len(tables)
        r.add("テーブル数", None, str(len(tables)))
        missing = []
        for table, cols in REQUIRED.items():
            if table not in tables:
                missing.append(table + " (テーブルなし)")
                continue
            have = {row[1] for row in con.execute(f"pragma table_info({table})")}
            missing += [f"{table}.{c}" for c in cols if c not in have]
        r.add("読み取りに必要な列", not missing, "すべてあり" if not missing else "無い: " + ", ".join(missing))
        opt_missing = []
        for table, cols in EXPORT_OPTIONAL.items():
            if table not in tables:
                opt_missing.append(table)
                continue
            have = {row[1] for row in con.execute(f"pragma table_info({table})")}
            opt_missing += [f"{table}.{c}" for c in cols if c not in have]
        r.add("XML 書き出し用の列（凍結中・参考）", None, "すべてあり" if not opt_missing else "無い: " + ", ".join(opt_missing))
        # values still mean what we think: BPM is x100, Length is seconds
        row = con.execute("select BPM, Length from djmdContent where BPM > 0 and Length > 0 limit 1").fetchone()
        if row:
            bpm_ok = 4000 <= row[0] <= 30000
            r.add("BPM の単位（x100）", bpm_ok, f"BPM 列の値 {row[0]} → {row[0] / 100:.2f}")
            r.add("Length の単位（秒）", 30 <= row[1] <= 7200, f"Length 列の値 {row[1]}")
    finally:
        con.close()

    # --- content ----------------------------------------------------------------
    pls = lib.playlists()
    tracks = lib.db.tracks()
    r.data.update(playlists=len(pls), tracks=len(tracks))
    r.add("プレイリスト / 曲", bool(pls) and bool(tracks), f"{len(pls)} / {len(tracks)}")

    # --- ANLZ / phrases / artwork ------------------------------------------------
    ids = [t.id for t in tracks][:sample]
    counts = {s: 0 for s in PhraseStatus}
    art_found = art_total = 0
    parse_err = 0
    for tid in ids:
        try:
            ta = lib.analysis(tid)
            counts[ta.phrase_status] += 1
        except Exception:
            parse_err += 1
        p = lib.artwork_path(tid)
        if p is not None:
            art_total += 1
            if Path(p).is_file():
                art_found += 1
    present = counts[PhraseStatus.PRESENT]
    r.data.update(sample=len(ids), phrase_present=present, phrase_absent=counts[PhraseStatus.ABSENT],
                  no_analysis=counts[PhraseStatus.NO_ANALYSIS], parse_errors=parse_err,
                  artwork_found=art_found, artwork_refs=art_total)
    r.add("ANLZ の読み取り", parse_err == 0, f"{len(ids)} 曲中 解析エラー {parse_err}")
    r.add("フレーズ解析（PSSI）", present > 0,
          f"あり {present} / なし {counts[PhraseStatus.ABSENT]} / 解析ファイルなし {counts[PhraseStatus.NO_ANALYSIS]}")
    r.add("アートワークの解決", art_total == 0 or art_found >= art_total * 0.9,
          f"{art_found}/{art_total} 件のファイルが実在")

    # --- baseline comparison ---------------------------------------------------------
    if write_baseline:
        out = Path(__file__).resolve().parent.parent / "docs" / "compat_baseline.json"
        out.write_text(json.dumps(r.data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"baseline written: {out}")
    elif baseline_path:
        try:
            base = json.loads(baseline_path.read_text(encoding="utf-8"))
            diffs = []
            for k in ("tables",):
                if base.get(k) is not None and r.data.get(k) != base.get(k):
                    diffs.append(f"{k}: {base.get(k)} → {r.data.get(k)}")
            r.add(f"基準（rekordbox {base.get('rekordbox_version', '?')}）との差", None,
                  "テーブル数など変化なし" if not diffs else "; ".join(diffs))
        except Exception as ex:
            r.add("基準との比較", None, f"読めませんでした: {ex}")

    print()
    print("結果:", "すべて PASS" if not r.failed else "FAIL があります — rekordbox の版を添えて報告してください")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
