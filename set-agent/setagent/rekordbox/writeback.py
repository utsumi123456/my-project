"""Hand a finished Set Draft back to rekordbox as a real playlist (2026-10-08).

Until now Set Agent never wrote anything (B-2), and the open question in the
handoff was how a Draft gets back into rekordbox at all. This module answers it
with the narrowest write that does the job, built on pyrekordbox:

  * Only playlists inside one root folder, "Set Agent", are ever created or
    rewritten. Tracks, cues, analysis, and every playlist outside that folder
    are never touched. The folder is Set Agent's out-tray: a playlist inside it
    with the same name is rewritten, nothing else is.
  * Only when rekordbox is not running. rekordbox keeps the database open and
    would overwrite (or be confused by) a concurrent writer; pyrekordbox refuses
    too. The UI offers "write when rekordbox quits" or "quit, write, relaunch".
  * Every write is preceded by a backup of master.db (+ -wal/-shm) and
    masterPlaylists6.xml, and followed by a read-back through Set Agent's own
    decrypter. If the read-back does not show exactly the intended track order,
    the backup is restored on the spot.
  * Only on an explicit action: the DJ's button, or an agent proposal the DJ
    approves. The agent itself can preview, never write.

pyrekordbox (and its SQLCipher wheel) is optional: without it everything else
in Set Agent keeps working and `available()` says why writing is off.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator

FOLDER_NAME = "Set Agent"
KEEP_BACKUPS = 10
NAME_MAX = 120
SIDE_FILES = ("master.db-wal", "master.db-shm", "masterPlaylists6.xml")


class WriteError(Exception):
    """Anything that stopped a write. The message is meant for the DJ."""


class RekordboxRunning(WriteError):
    pass


class WriterUnavailable(WriteError):
    pass


# ------------------------------------------------------------------ helpers

def available() -> tuple[bool, str]:
    """Can this install write at all? (pyrekordbox + SQLCipher present)."""
    try:
        import pyrekordbox.db6.database  # noqa: F401
        from sqlcipher3 import dbapi2  # noqa: F401
    except Exception as ex:                                  # ImportError and broken wheels alike
        return False, (f"rekordbox への書き込みに必要な pyrekordbox を読み込めません（{type(ex).__name__}）。"
                       "分析とエージェントはそのまま使えます")
    return True, ""


def clean_name(name: str) -> str:
    """A playlist name rekordbox shows as typed: one line, no control chars."""
    s = " ".join(str(name or "").split())
    s = "".join(ch for ch in s if ch.isprintable())
    return s[:NAME_MAX].strip() or "Set Agent"


def is_live_library(master_db: Path, live: Iterable[Path]) -> bool:
    """True when `master_db` is the file a running rekordbox would hold open."""
    try:
        me = Path(master_db).resolve()
    except OSError:
        return True
    for p in live:
        try:
            if Path(p).resolve() == me:
                return True
        except OSError:
            continue
    return False


def _default_live() -> list[Path]:
    from setagent.rekordbox.library import default_master_db_candidates
    return default_master_db_candidates(include_env=False)


def _rekordbox_running() -> bool:
    from setagent.rekordbox.library import rekordbox_running
    r = rekordbox_running()
    if r is None:
        try:                                                 # pyrekordbox's own check (psutil)
            from pyrekordbox.utils import get_rekordbox_pid
            return bool(get_rekordbox_pid())
        except Exception:
            return True                                      # unknown counts as running: never guess
    return r


# ------------------------------------------------------------------ backups

@dataclass(frozen=True)
class Backup:
    id: str                 # folder name, e.g. "20261008-231502-417" (ms)
    path: Path
    created: str            # ISO time
    reason: str
    size: int

    def to_json(self) -> dict:
        return {"id": self.id, "created": self.created, "reason": self.reason,
                "size_mb": round(self.size / 1e6, 1)}


class Backups:
    """Copies of the rekordbox database taken before every write.

    Kept beside the app's settings, newest KEEP_BACKUPS only. A backup is the
    whole set of files rekordbox needs to open the library as it was."""

    def __init__(self, root: Path, keep: int = KEEP_BACKUPS):
        self.root = Path(root)
        self.keep = keep

    def take(self, master_db: Path, reason: str, prune: bool = True) -> Backup:
        master_db = Path(master_db)
        now = datetime.now()
        # millisecond ids sort in time order as plain strings, even within one second
        stamp = now.strftime("%Y%m%d-%H%M%S-") + f"{now.microsecond // 1000:03d}"
        dst = self.root / stamp
        while dst.exists():
            time.sleep(0.002)
            now = datetime.now()
            stamp = now.strftime("%Y%m%d-%H%M%S-") + f"{now.microsecond // 1000:03d}"
            dst = self.root / stamp
        dst.mkdir(parents=True)
        try:
            shutil.copy2(master_db, dst / "master.db")
            for name in SIDE_FILES:
                src = master_db.parent / name
                if src.exists():
                    shutil.copy2(src, dst / name)
            meta = {"created": datetime.now().isoformat(timespec="seconds"), "reason": reason,
                    "source": str(master_db)}
            (dst / "backup.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        except OSError as ex:
            shutil.rmtree(dst, ignore_errors=True)
            raise WriteError(f"バックアップを作れませんでした（{ex}）。書き込みは行っていません")
        if prune:
            self.prune()
        return self._load(dst)

    def _load(self, d: Path) -> Backup:
        try:
            meta = json.loads((d / "backup.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
        return Backup(d.name, d, meta.get("created", ""), meta.get("reason", ""), size)

    def list(self) -> list[Backup]:
        if not self.root.is_dir():
            return []
        out = [self._load(d) for d in self.root.iterdir()
               if d.is_dir() and (d / "master.db").is_file()]
        return sorted(out, key=lambda b: b.id, reverse=True)

    def get(self, backup_id: str) -> Backup:
        for b in self.list():
            if b.id == backup_id:
                return b
        raise WriteError(f"バックアップ {backup_id} が見つかりません")

    def prune(self) -> None:
        for b in self.list()[self.keep:]:
            shutil.rmtree(b.path, ignore_errors=True)

    def restore_into(self, b: Backup, master_db: Path) -> None:
        """Put the backup's files back. Side files the backup lacks are removed,
        so SQLite does not replay a newer WAL over the older database."""
        master_db = Path(master_db)
        shutil.copy2(b.path / "master.db", master_db)
        for name in SIDE_FILES:
            src, dst = b.path / name, master_db.parent / name
            if src.exists():
                shutil.copy2(src, dst)
            elif name != "masterPlaylists6.xml" and dst.exists():
                dst.unlink()


# ------------------------------------------------------------------ plan

@dataclass
class PublishPlan:
    """What a write would do, worked out without writing (the preview)."""
    name: str
    track_ids: list[str]                       # in Draft order, only tracks that exist
    skipped: list[dict] = field(default_factory=list)   # {track_id, title, why}
    replaces: bool = False                     # a playlist of that name already sits in the folder
    replaces_count: int = 0                    # how many tracks it has now
    folder_exists: bool = False
    source: str = ""                           # the rekordbox playlist the Draft was built from

    def to_json(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        where = f"rekordbox の「{FOLDER_NAME}」フォルダ"
        verb = (f"既存の「{self.name}」（{self.replaces_count} 曲）を上書き" if self.replaces
                else f"「{self.name}」を新しく作成")
        s = f"{where}に {verb}します（{len(self.track_ids)} 曲、Set Agent の曲順）。"
        if self.skipped:
            s += f" {len(self.skipped)} 曲はコレクションに無いため入りません。"
        return s


def plan_publish(plain_db: Path, track_ids: Iterable[str], name: str, source: str = "") -> PublishPlan:
    """Read-only: check every id against the (decrypted) collection and see
    whether the target playlist exists. Never touches the encrypted original."""
    con = sqlite3.connect(f"file:{Path(plain_db)}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        ids, skipped, seen = [], [], set()
        for tid in track_ids:
            tid = str(tid)
            r = con.execute("select ID, Title, rb_local_deleted from djmdContent where ID=?",
                            (tid,)).fetchone()
            if r is None or r["rb_local_deleted"]:
                skipped.append({"track_id": tid, "title": r["Title"] if r else "",
                                "why": "コレクションにありません"})
                continue
            if tid in seen:
                # rekordbox allows duplicates in a playlist; a set does not play one twice
                skipped.append({"track_id": tid, "title": r["Title"] or "", "why": "重複"})
                continue
            seen.add(tid)
            ids.append(tid)
        name = clean_name(name)
        folder = _folder_row(con)
        replaces, count = False, 0
        if folder is not None:
            pl = con.execute(
                "select ID from djmdPlaylist where ParentID=? and Name=? and Attribute=0 "
                "and rb_local_deleted=0", (folder, name)).fetchone()
            if pl is not None:
                replaces = True
                count = con.execute(
                    "select count(*) from djmdSongPlaylist where PlaylistID=? and rb_local_deleted=0",
                    (pl[0],)).fetchone()[0]
        return PublishPlan(name, ids, skipped, replaces, count, folder is not None, source)
    finally:
        con.close()


def plan_publish_fresh(master_db: Path, track_ids: Iterable[str], name: str, source: str = "") -> PublishPlan:
    """plan_publish against the database as it is *now* (decrypted to a temp
    file), not Set Agent's cached copy -- which predates our own last write."""
    from tools.decrypt_masterdb import decrypt
    master_db = Path(master_db)
    wal = master_db.with_name(master_db.name + "-wal")
    with tempfile.TemporaryDirectory(prefix="setagent-plan-") as d:
        plain = Path(d) / "plan.db"
        decrypt(master_db, plain, wal=wal if wal.exists() else None)
        return plan_publish(plain, track_ids, name, source)


def _folder_row(con) -> str | None:
    r = con.execute(
        "select ID from djmdPlaylist where ParentID='root' and Name=? and Attribute=1 "
        "and rb_local_deleted=0 order by Seq limit 1", (FOLDER_NAME,)).fetchone()
    return r[0] if r else None


# ------------------------------------------------------------------ write

@dataclass
class PublishResult:
    ok: bool
    name: str = ""
    playlist_id: str = ""
    folder_id: str = ""
    tracks: int = 0
    replaced: bool = False
    backup_id: str = ""
    restored: bool = False                    # verification failed and the backup went back
    error: str = ""
    at: str = ""
    elapsed_s: float = 0.0

    def to_json(self) -> dict:
        return asdict(self)


@contextmanager
def _rekordbox_db(master_db: Path, allow_running: bool) -> Iterator:
    """pyrekordbox's database, with its "is rekordbox running" commit guard kept
    unless the target is not the live library (a copy, a test fixture)."""
    ok, why = available()
    if not ok:
        raise WriterUnavailable(why)
    from pyrekordbox.db6 import database as rbdb
    from tools.decrypt_masterdb import PASSPHRASE
    saved = rbdb.get_rekordbox_pid
    if allow_running:
        rbdb.get_rekordbox_pid = lambda *a, **k: 0
    db = None
    try:
        db = rbdb.Rekordbox6Database(master_db, key=PASSPHRASE)
        yield db
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
            try:
                db.engine.dispose()                       # release the file; lets SQLite checkpoint
            except Exception:
                pass
        rbdb.get_rekordbox_pid = saved


def read_playlist(master_db: Path, playlist_id: str) -> list[str]:
    """Track ids of a playlist, read back through Set Agent's own decrypter."""
    from tools.decrypt_masterdb import decrypt
    master_db = Path(master_db)
    wal = master_db.with_name(master_db.name + "-wal")
    with tempfile.TemporaryDirectory(prefix="setagent-verify-") as d:
        plain = Path(d) / "verify.db"
        decrypt(master_db, plain, wal=wal if wal.exists() else None)
        con = sqlite3.connect(f"file:{plain}?mode=ro", uri=True)
        try:
            return [r[0] for r in con.execute(
                "select ContentID from djmdSongPlaylist where PlaylistID=? and rb_local_deleted=0 "
                "order by TrackNo", (str(playlist_id),))]
        finally:
            con.close()


class Writer:
    """Creates or rewrites one playlist inside the Set Agent folder.

    running:  () -> bool, "is rekordbox open?" -- injectable for tests.
    live:     the paths rekordbox itself uses; the running-guard applies to these.
    """

    def __init__(self, backups: Backups, *, running: Callable[[], bool] | None = None,
                 live: Iterable[Path] | None = None, log: Callable[[str], None] | None = None):
        self.backups = backups
        self.running = running or _rekordbox_running
        self.live = list(live) if live is not None else _default_live()
        self.log = log or (lambda s: None)

    def guard(self, master_db: Path) -> bool:
        """Raise RekordboxRunning if writing now would race rekordbox.
        Returns True when the target is not the live library (guard waived)."""
        live = is_live_library(master_db, self.live)
        if live and self.running():
            raise RekordboxRunning("rekordbox が起動しています。終了してから書き込みます")
        return not live

    def publish(self, master_db: Path, plan: PublishPlan) -> PublishResult:
        t0 = time.monotonic()
        master_db = Path(master_db)
        res = PublishResult(False, plan.name, at=datetime.now().isoformat(timespec="seconds"))
        if not plan.track_ids:
            res.error = "書き込める曲がありません"
            return res
        try:
            waived = self.guard(master_db)
            b = self.backups.take(master_db, f"書き込み前: {plan.name}")
            res.backup_id = b.id
            self.log(f"backup {b.id}")
            folder_id, pl_id, replaced = self._write(master_db, plan, waived)
            res.folder_id, res.playlist_id, res.replaced = folder_id, pl_id, replaced
            got = read_playlist(master_db, pl_id)
            if got != list(plan.track_ids):
                self.backups.restore_into(b, master_db)
                res.restored = True
                raise WriteError(f"書き込み後の確認で曲順が一致しませんでした（{len(got)}/{len(plan.track_ids)} 曲）。"
                                 "バックアップに戻しました")
            res.ok, res.tracks = True, len(got)
        except WriteError as ex:
            res.error = str(ex)
        except Exception as ex:                               # pyrekordbox / SQLCipher failure
            res.error = f"書き込みに失敗しました: {type(ex).__name__}: {ex}"
            if res.backup_id and not res.restored:
                try:
                    self.backups.restore_into(self.backups.get(res.backup_id), master_db)
                    res.restored = True
                    res.error += "。バックアップに戻しました"
                except Exception as ex2:
                    res.error += f"。バックアップへの復元にも失敗しました（{ex2}）。設定の「バックアップ」から戻してください"
        res.elapsed_s = round(time.monotonic() - t0, 2)
        return res

    def _write(self, master_db: Path, plan: PublishPlan, waived: bool) -> tuple[str, str, bool]:
        with _rekordbox_db(master_db, allow_running=waived) as db:
            folder = None
            for p in db.get_playlist(ParentID="root", Name=FOLDER_NAME):
                if p.Attribute == 1 and not p.rb_local_deleted:
                    folder = p
                    break
            if folder is None:
                folder = db.create_playlist_folder(FOLDER_NAME)
            target = None
            for p in db.get_playlist(ParentID=str(folder.ID), Name=plan.name):
                if p.Attribute == 0 and not p.rb_local_deleted:
                    target = p
                    break
            replaced = target is not None
            if target is None:
                target = db.create_playlist(plan.name, parent=folder)
            else:
                for song in sorted(list(target.Songs), key=lambda s: s.TrackNo or 0, reverse=True):
                    db.remove_from_playlist(target, song)
            for tid in plan.track_ids:
                db.add_to_playlist(target, tid)
            db.commit()
            return str(folder.ID), str(target.ID), replaced

    def restore(self, master_db: Path, backup_id: str) -> dict:
        """Put a backup back. Takes a backup of the current state first, so a
        restore is itself undoable."""
        master_db = Path(master_db)
        self.guard(master_db)
        b = self.backups.get(backup_id)
        safety = self.backups.take(master_db, f"復元前: {backup_id} に戻す直前", prune=False)
        self.backups.restore_into(b, master_db)
        self.backups.prune()                       # only now: the restored one may be the oldest
        return {"ok": True, "restored": b.id, "safety_backup": safety.id}
