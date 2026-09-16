"""Read-only access to a *decrypted* rekordbox master.db (plain SQLite).

Decrypt first with tools/decrypt_masterdb.py (or open via pyrekordbox where
available). This module never writes.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    bpm: float                 # rekordbox value (authoritative; never re-estimate)
    length_s: int              # rekordbox Length in seconds
    key: str
    analysis_path: str | None  # '/PIONEER/USBANLZ/xxx/yyy/ANLZ0000.DAT' or None
    analysed: int
    folder_path: str = ""
    file_type: int = 0

    @property
    def is_cloud(self) -> bool:
        """rekordbox Cloud Library Sync / streaming: local re-analysis is not possible."""
        return self.folder_path.startswith("/contents_") or self.file_type == 25 or self.folder_path.startswith("spotify:")


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    track_ids: tuple[str, ...]


class MasterDB:
    def __init__(self, plain_db: Path | str):
        self.con = sqlite3.connect(f"file:{Path(plain_db)}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row

    def track(self, track_id: str) -> Track:
        r = self.con.execute(
            """select c.ID, c.Title, coalesce(a.Name,'') as Artist, c.BPM, c.Length,
                      coalesce(k.ScaleName,'') as Key, c.AnalysisDataPath, c.Analysed,
                      coalesce(c.FolderPath,'') as FolderPath, coalesce(c.FileType,0) as FileType
               from djmdContent c
               left join djmdArtist a on a.ID = c.ArtistID
               left join djmdKey k on k.ID = c.KeyID
               where c.ID = ?""", (track_id,)).fetchone()
        if r is None:
            raise KeyError(track_id)
        return Track(r["ID"], r["Title"] or "", r["Artist"], (r["BPM"] or 0) / 100.0,
                     int(r["Length"] or 0), r["Key"], r["AnalysisDataPath"] or None,
                     int(r["Analysed"] or 0), r["FolderPath"], int(r["FileType"]))

    def tracks(self, include_deleted: bool = False) -> list[Track]:
        q = "select ID from djmdContent" + ("" if include_deleted else " where rb_local_deleted=0")
        return [self.track(r["ID"]) for r in self.con.execute(q)]

    def playlists(self) -> list[Playlist]:
        out = []
        for p in self.con.execute(
                "select ID, Name from djmdPlaylist where Attribute=0 and rb_local_deleted=0 order by Seq"):
            ids = tuple(r["ContentID"] for r in self.con.execute(
                "select ContentID from djmdSongPlaylist where PlaylistID=? and rb_local_deleted=0 order by TrackNo",
                (p["ID"],)))
            out.append(Playlist(p["ID"], p["Name"], ids))
        return out

    def playlist_by_name(self, name: str) -> Playlist:
        for p in self.playlists():
            if p.name == name:
                return p
        raise KeyError(name)

    # ---- full row for rekordbox XML export (all fields rekordbox itself emits)
    EXPORT_SQL = """
        select c.ID, c.Title, coalesce(ar.Name,'') Artist, coalesce(cp.Name,'') Composer,
               coalesce(al.Name,'') Album, coalesce(g.Name,'') Genre,
               coalesce(c.FileNameL,'') FileName, coalesce(c.FileSize,0) FileSize,
               coalesce(c.Length,0) Length, coalesce(c.DiscNo,0) DiscNo,
               coalesce(c.TrackNo,0) TrackNo, coalesce(c.ReleaseYear,0) ReleaseYear,
               coalesce(c.BPM,0) BPM, coalesce(c.DateCreated,'') DateCreated,
               coalesce(c.BitRate,0) BitRate, coalesce(c.SampleRate,0) SampleRate,
               coalesce(c.Commnt,'') Commnt, coalesce(c.DJPlayCount,0) DJPlayCount,
               coalesce(c.Rating,0) Rating, coalesce(c.FolderPath,'') FolderPath,
               coalesce(rm.Name,'') Remixer, coalesce(k.ScaleName,'') Tonality,
               coalesce(lb.Name,'') Label
        from djmdContent c
        left join djmdArtist ar on ar.ID = c.ArtistID
        left join djmdArtist cp on cp.ID = c.ComposerID
        left join djmdArtist rm on rm.ID = c.RemixerID
        left join djmdAlbum  al on al.ID = c.AlbumID
        left join djmdGenre  g  on g.ID  = c.GenreID
        left join djmdKey    k  on k.ID  = c.KeyID
        left join djmdLabel  lb on lb.ID = c.LabelID
        where c.ID = ?"""

    def export_row(self, track_id: str) -> dict:
        r = self.con.execute(self.EXPORT_SQL, (track_id,)).fetchone()
        if r is None:
            raise KeyError(track_id)
        return {k: r[k] for k in r.keys()}
