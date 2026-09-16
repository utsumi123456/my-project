"""`setagent doctor` — one command that answers "why doesn't it work on my PC?".

Written for the moment a teammate says it is broken. It never raises: every check
records what it found, including the failure, so the output can be pasted into a
message and read by someone who is not sitting at that machine.
"""
from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from setagent.settings import Settings, app_home


@dataclass
class Check:
    name: str
    ok: bool | None            # None = could not tell
    detail: str = ""

    @property
    def mark(self) -> str:
        return "OK  " if self.ok else ("--  " if self.ok is None else "NG  ")


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def add(self, name: str, ok: bool | None, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.ok is False]

    def text(self) -> str:
        w = max((len(c.name) for c in self.checks), default=10)
        lines = ["Set Agent 診断", "=" * 60]
        for c in self.checks:
            lines.append(f"{c.mark}{c.name.ljust(w)}  {c.detail}")
        if self.hints:
            lines += ["", "次にやること:"] + [f"  - {h}" for h in self.hints]
        if not self.failed:
            lines += ["", "致命的な問題は無い。"]
        return "\n".join(lines)


def run(master_db: str | None = None, sample: int = 200) -> Report:
    r = Report()

    frozen = getattr(sys, "frozen", False)
    r.add("実行環境", True, f"{platform.system()} {platform.release()} / Python {platform.python_version()}"
          + (" / 単体exe" if frozen else " / ソース実行"))

    st = Settings.load()
    sp = Settings.path()
    r.add("設定ファイル", True, f"{sp}" + ("（あり）" if sp.exists() else "（未作成 — 初回起動でできる）"))
    r.add("作業フォルダ", True, str(app_home()))

    # --- locate the library -------------------------------------------------
    from setagent.rekordbox.library import (LibraryNotFound, Library, default_master_db_candidates,
                                            pending_wal_bytes, rekordbox_running)
    want = master_db or st.master_db or None
    try:
        from setagent.rekordbox.library import find_master_db
        mdb = find_master_db(want)
        size_mb = mdb.stat().st_size / 1e6
        age = (time.time() - mdb.stat().st_mtime) / 3600
        r.add("master.db", True, f"{mdb}  ({size_mb:.1f} MB / 最終更新 {age:.1f} 時間前)")
    except LibraryNotFound as ex:
        r.add("master.db", False, str(ex))
        r.hints.append("rekordbox 6 か 7 をこの PC にインストールして一度起動しろ。"
                       "場所が普通と違うなら、GUI の起動時に master.db を手で指定できる")
        for p in default_master_db_candidates():
            r.add("  探した場所", None, str(p))
        return r
    except Exception as ex:
        r.add("master.db", False, f"{type(ex).__name__}: {ex}")
        return r

    # Neither of these is a failure — the tool works fine either way. They only
    # explain "why isn't the playlist I just made showing up?", so they are notes.
    running = rekordbox_running()
    r.add("rekordbox", None,
          "起動中 — 直前の編集はまだ反映されていないかもしれない" if running
          else ("終了している" if running is False else "判定できない環境"))
    wal = pending_wal_bytes(mdb)
    if wal > 4096:
        r.add("未反映データ (WAL)", None, f"{wal // 1024} KB がまだ master.db に書かれていない")
        r.hints.append("rekordbox を終了すると WAL が master.db に取り込まれる。"
                       "作ったばかりのプレイリストが出てこないときはこれが原因")

    # --- decrypt and read ---------------------------------------------------
    try:
        t0 = time.time()
        lib = Library.open(master_db=str(mdb))
        r.add("復号と読み取り", True, f"{time.time() - t0:.1f} 秒")
    except Exception as ex:
        r.add("復号と読み取り", False, f"{type(ex).__name__}: {ex}")
        r.hints.append("master.db が壊れているか、rekordbox のバージョンが想定外だ。"
                       "rekordbox のバージョンを添えて報告しろ")
        return r

    r.add("解析データ置き場", lib.share_dir.is_dir(), str(lib.share_dir))
    if not lib.share_dir.is_dir():
        r.hints.append("share フォルダが無い。rekordbox で曲を解析すると作られる")

    try:
        pls = lib.playlists()
        tracks = lib.db.tracks()
        r.add("プレイリスト", bool(pls), f"{len(pls)} 個 / 曲 {len(tracks)} 件")
        if not pls:
            r.hints.append("プレイリストが無い。rekordbox でプレイリストを1つ作れ")
    except Exception as ex:
        r.add("プレイリスト", False, f"{type(ex).__name__}: {ex}")
        return r

    # --- phrase coverage ----------------------------------------------------
    from setagent.rekordbox.library import PhraseStatus
    ids = [t.id for t in tracks][:sample]
    counts = {s: 0 for s in PhraseStatus}
    cloud = 0
    for tid in ids:
        try:
            ta = lib.analysis(tid)
        except Exception:
            continue
        counts[ta.phrase_status] += 1
        if ta.track.is_cloud:
            cloud += 1
    present = counts[PhraseStatus.PRESENT]
    scanned = max(len(ids), 1)
    r.add("フレーズ解析", present > 0,
          f"{present}/{scanned} 曲にあり"
          + (f"（先頭 {sample} 曲を確認）" if len(tracks) > sample else "")
          + f" / クラウド保存 {cloud} 曲")
    if present == 0:
        r.hints.append("フレーズ解析が1曲も無い。rekordbox の 環境設定 > 解析 で"
                       "「フレーズ」をオンにして曲を再解析し、Set Agent の Rescan を押せ")
    elif present < scanned * 0.3:
        r.hints.append("フレーズ解析のある曲が少ない。展開の分析と再生範囲のプリセットは"
                       "解析のある曲にしか効かない。クラウド保存の曲は rekordbox が解析しない")
    return r


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Set Agent の環境診断")
    ap.add_argument("--db", help="master.db を手で指定する")
    a = ap.parse_args(argv)
    rep = run(a.db)
    print(rep.text())
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
