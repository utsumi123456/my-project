"""Library import — works on any teammate's PC, not only the author's.

Discovery order (spec B-11, team-distribution requirement):
  1. explicit path given by the user
  2. rekordbox 6/7 default:  %APPDATA%\\Pioneer\\rekordbox\\master.db (Windows)
                              ~/Library/Pioneer/rekordbox/master.db (macOS)
  3. (fallback) a rekordbox XML export chosen by the user  [not implemented yet]

The encrypted master.db is decrypted into the app's own cache directory and
opened read-only. The original is never touched. `rescan()` re-reads the DB
and the ANLZ files so that phrase data generated later in rekordbox
(Preferences > Analysis > Phrase, then re-analyse) shows up without restart.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from setagent.rekordbox.anlz import AnlzFile, load_track_analysis
from setagent.rekordbox.masterdb import MasterDB, Playlist, Track


class PhraseStatus(str, Enum):
    PRESENT = "present"          # PSSI parsed, phrases > 0
    ABSENT = "absent"            # analysis files exist but no phrase section
    NO_ANALYSIS = "no_analysis"  # DB has no analysis path, or files missing (cloud/streaming, missing drive)


@dataclass
class TrackAnalysis:
    track: Track
    anlz: AnlzFile | None
    phrase_status: PhraseStatus
    reason: str = ""

    @property
    def has_beatgrid(self) -> bool:
        return bool(self.anlz and self.anlz.beats)


def rekordbox_running() -> bool | None:
    """True/False on Windows and macOS; None where we cannot tell.

    It matters because rekordbox keeps recent edits in master.db-wal, which this
    reader does not merge — a set built while rekordbox is open can be missing
    the playlist the DJ just made.
    """
    try:
        if sys.platform.startswith("win"):
            # CREATE_NO_WINDOW: the windowed exe has no console, so without it
            # every poll (5 s) flashed a console window for the child process.
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, timeout=10, errors="replace",
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return "rekordbox.exe" in out.lower()
        if sys.platform == "darwin":
            out = subprocess.run(["pgrep", "-x", "rekordbox"], capture_output=True,
                                 text=True, timeout=10).stdout
            return bool(out.strip())
    except Exception:
        return None
    return None


def pending_wal_bytes(master_db: Path) -> int:
    wal = master_db.with_name(master_db.name + "-wal")
    try:
        return wal.stat().st_size
    except OSError:
        return 0


def default_master_db_candidates() -> list[Path]:
    c: list[Path] = []
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            c.append(Path(appdata) / "Pioneer" / "rekordbox" / "master.db")
    elif sys.platform == "darwin":
        c.append(Path.home() / "Library" / "Pioneer" / "rekordbox" / "master.db")
    # allow tests / non-standard installs
    env = os.environ.get("SETAGENT_MASTER_DB")
    if env:
        c.insert(0, Path(env))
    return c


class LibraryNotFound(FileNotFoundError):
    """Auto-detection failed. The GUI turns this into "pick the file yourself"."""
    def __init__(self, tried: list[Path]):
        self.tried = tried
        super().__init__("rekordbox の master.db が見つからない。探した場所: "
                         + ", ".join(map(str, tried)))


def find_master_db(explicit: Path | str | None = None) -> Path:
    cands = [Path(explicit)] if explicit else default_master_db_candidates()
    for p in cands:
        if p.is_file():
            return p
    raise LibraryNotFound(cands)


@dataclass
class Library:
    master_db: Path                  # encrypted original (read-only)
    share_dir: Path                  # <rekordbox>/share  (ANLZ files live under share/PIONEER/USBANLZ)
    cache_dir: Path
    db: MasterDB = field(init=False)
    _analysis: dict[str, TrackAnalysis] = field(default_factory=dict, init=False)
    plain_db: Path = field(init=False)
    warnings: list[str] = field(default_factory=list, init=False)
    wal_replay: object = field(default=None, init=False)   # WalReplay from the last decrypt

    @classmethod
    def open(cls, master_db: Path | str | None = None, cache_dir: Path | str | None = None,
             plain_db: Path | str | None = None) -> "Library":
        """plain_db: use an already-decrypted copy (tests / sandbox). Otherwise decrypt."""
        mdb = find_master_db(master_db)
        cache = Path(cache_dir) if cache_dir else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SetAgent" / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        lib = cls(mdb, mdb.parent / "share", cache)
        lib.plain_db = Path(plain_db) if plain_db else cache / "master_plain.db"
        if not plain_db:
            lib._decrypt()
        lib.db = MasterDB(lib.plain_db)
        lib.warnings = lib._staleness_warnings()
        return lib

    # ---- reading the encrypted DB
    def _decrypt(self) -> None:
        """Snapshot master.db and its -wal, then decrypt the snapshot with the WAL replayed.

        rekordbox never checkpoints while it is open (measured 2026-09-16), so
        the WAL is where every edit of the current session lives; without it
        the set on screen is hours old. Copying first keeps our read short and
        leaves the previous cache intact if anything fails.

        Order matters: master.db first, then the WAL. If rekordbox checkpoints
        in between, the WAL we copy may belong to a newer database than the
        snapshot; applying it would mix two generations of pages. Detect that
        by re-checking master.db after the WAL copy and start over.
        """
        from tools.decrypt_masterdb import decrypt      # pure-python; no pyrekordbox needed
        wal_src = self.master_db.with_name(self.master_db.name + "-wal")
        snap = self.cache_dir / "master_snapshot.db"
        snap_wal = self.cache_dir / "master_snapshot.db-wal"
        src, wal = self.master_db, wal_src
        for _ in range(3):
            try:
                before = self.master_db.stat()
                shutil.copy2(self.master_db, snap)
                if wal_src.exists():
                    shutil.copy2(wal_src, snap_wal)
                else:
                    snap_wal.unlink(missing_ok=True)
                after = self.master_db.stat()
            except OSError:
                break                                   # copy failed: read in place
            if (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size):
                src, wal = snap, snap_wal
                break
        try:
            res = decrypt(src, self.plain_db, wal=wal)
        finally:
            for p in (snap, snap_wal):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        self.wal_replay = res.wal

    def _staleness_warnings(self) -> list[str]:
        rep = self.wal_replay
        if rep is None or not rep.note:
            return []
        return [f"master.db-wal を途中までしか読めませんでした（{rep.note}）。"
                "rekordbox の直前の編集が抜けている可能性があります。もう一度反映してください"]

    # ---- rekordbox path -> local file
    def anlz_dat_path(self, t: Track) -> Path | None:
        if not t.analysis_path:
            return None
        return self.share_dir / t.analysis_path.lstrip("/")

    def artwork_path(self, track_id: str) -> Path | None:
        rel = self.db.image_path(track_id)
        if not rel:
            return None
        p = self.share_dir / rel.lstrip("/")
        return p if p.is_file() else None

    # ---- analysis with phrase status
    def analysis(self, track_id: str) -> TrackAnalysis:
        if track_id in self._analysis:
            return self._analysis[track_id]
        t = self.db.track(track_id)
        dat = self.anlz_dat_path(t)
        if dat is None:
            ta = TrackAnalysis(t, None, PhraseStatus.NO_ANALYSIS, "no analysis path in rekordbox DB")
        elif not any(dat.with_suffix(x).exists() for x in (".DAT", ".EXT", ".2EX")):
            ta = TrackAnalysis(t, None, PhraseStatus.NO_ANALYSIS, f"analysis file missing: {dat.name}")
        else:
            a = load_track_analysis(dat)
            if a.has_phrases:
                ta = TrackAnalysis(t, a, PhraseStatus.PRESENT)
            elif t.is_cloud:
                ta = TrackAnalysis(t, a, PhraseStatus.ABSENT,
                                   "cloud/streaming track: rekordbox does not generate phrase data for it")
            else:
                ta = TrackAnalysis(t, a, PhraseStatus.ABSENT,
                                   "no phrase data — enable Phrase in rekordbox analysis settings and re-analyse")
        self._analysis[track_id] = ta
        return ta

    def rescan(self) -> None:
        """Re-decrypt the DB and drop cached analyses (the 'rescan' button)."""
        if self.plain_db.parent == self.cache_dir:
            self._decrypt()
            self.db = MasterDB(self.plain_db)
            self.warnings = self._staleness_warnings()
        self._analysis.clear()

    def phrase_summary(self, track_ids: list[str]) -> dict[PhraseStatus, int]:
        out = {s: 0 for s in PhraseStatus}
        for i in track_ids:
            out[self.analysis(i).phrase_status] += 1
        return out

    # ---- TrackSource protocol for the timing engine
    def track(self, track_id: str) -> Track:
        return self.db.track(track_id)

    def playlists(self) -> list[Playlist]:
        return self.db.playlists()
