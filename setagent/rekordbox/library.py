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
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, timeout=10, errors="replace").stdout
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
        """Copy first, then decrypt the copy.

        rekordbox may be writing while we read. Copying is one short read of the
        whole file instead of a long one interleaved with its writes, and it means
        a failure leaves the previous cache intact rather than a half-written one.
        """
        from tools.decrypt_masterdb import decrypt      # pure-python; no pyrekordbox needed
        snap = self.cache_dir / "master_snapshot.db"
        try:
            shutil.copy2(self.master_db, snap)
            src = snap
        except OSError:
            src = self.master_db                        # copy failed: read in place
        try:
            decrypt(src, self.plain_db)
        finally:
            if src is snap:
                try:
                    snap.unlink()
                except OSError:
                    pass

    def _staleness_warnings(self) -> list[str]:
        out: list[str] = []
        wal = pending_wal_bytes(self.master_db)
        running = rekordbox_running()
        if running:
            out.append("rekordbox が起動している。直前の編集はまだ master.db に書かれていない"
                       "ことがある — rekordbox を終了してから Rescan すると確実だ")
        elif wal > 4096:
            out.append(f"master.db-wal に未反映のデータが {wal // 1024} KB ある。"
                       "rekordbox を一度起動して終了すると取り込まれる")
        return out

    # ---- rekordbox path -> local file
    def anlz_dat_path(self, t: Track) -> Path | None:
        if not t.analysis_path:
            return None
        return self.share_dir / t.analysis_path.lstrip("/")

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
            from tools.decrypt_masterdb import decrypt
            decrypt(self.master_db, self.plain_db)
            self.db = MasterDB(self.plain_db)
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
