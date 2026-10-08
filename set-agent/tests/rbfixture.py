"""A small *encrypted* rekordbox 7 master.db for write-back tests.

Built from the real rekordbox 7.2.19 schema (tests/fixtures/master_schema_rb7.sql,
CREATE statements only, no library data) with SQLCipher, so pyrekordbox and
Set Agent's own decrypter both see exactly what they see on a DJ's PC.
Returns None when SQLCipher is not installed, so callers can skip.
"""
from __future__ import annotations

from pathlib import Path

SCHEMA = Path(__file__).with_name("fixtures") / "master_schema_rb7.sql"
NOW = "2026-10-08 12:00:00.000 +00:00"


def build(dirpath: Path, tracks: int = 6, playlists: dict[str, list[str]] | None = None,
          history: list[list[str]] | None = None) -> Path | None:
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except Exception:
        return None
    from tools.decrypt_masterdb import PASSPHRASE
    dirpath = Path(dirpath)
    dirpath.mkdir(parents=True, exist_ok=True)
    db = dirpath / "master.db"
    con = sqlcipher.connect(str(db))
    con.execute(f"PRAGMA key='{PASSPHRASE}'")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("insert into agentRegistry (registry_id, int_1, created_at, updated_at) "
                "values ('localUpdateCount', 100, ?, ?)", (NOW, NOW))
    keys = ["Am", "C", "Em", "G", "Dm", "F", "Bm", "D"]
    for i, k in enumerate(keys, 1):
        con.execute("insert into djmdKey (ID, ScaleName, Seq, created_at, updated_at) values (?,?,?,?,?)",
                    (str(i), k, i, NOW, NOW))
    con.execute("insert into djmdGenre (ID, Name, created_at, updated_at) values ('1','Acid',?,?)", (NOW, NOW))
    con.execute("insert into djmdArtist (ID, Name, created_at, updated_at) values ('1','DJ X',?,?)", (NOW, NOW))
    for i in range(1, tracks + 1):
        con.execute(
            "insert into djmdContent (ID, Title, ArtistID, GenreID, BPM, Length, KeyID, Rating, DJPlayCount, "
            "FolderPath, FileType, StockDate, rb_local_deleted, created_at, updated_at) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (str(i), f"Track {i}", "1", "1", 14000 + i * 100, 180 + i * 10, str((i - 1) % len(keys) + 1),
             i % 6, i, f"/music/t{i}.mp3", 1, f"2026-0{1 + i % 9}-01", NOW, NOW))
    seq = 1
    for name, ids in (playlists or {}).items():
        pid = str(1000 + seq)
        con.execute("insert into djmdPlaylist (ID, Seq, Name, Attribute, ParentID, created_at, updated_at) "
                    "values (?,?,?,?,?,?,?)", (pid, seq, name, 0, "root", NOW, NOW))
        for n, tid in enumerate(ids, 1):
            con.execute("insert into djmdSongPlaylist (ID, PlaylistID, ContentID, TrackNo, created_at, updated_at) "
                        "values (?,?,?,?,?,?)", (f"{pid}-{n}", pid, tid, n, NOW, NOW))
        seq += 1
    for h, ids in enumerate(history or [], 1):
        hid = str(5000 + h)
        con.execute("insert into djmdHistory (ID, Seq, Name, Attribute, ParentID, DateCreated, created_at, updated_at) "
                    "values (?,?,?,?,?,?,?,?)", (hid, h, f"2026-09-{h:02d}", 0, "root", f"2026-09-{h:02d}", NOW, NOW))
        for n, tid in enumerate(ids, 1):
            con.execute("insert into djmdSongHistory (ID, HistoryID, ContentID, TrackNo, created_at, updated_at) "
                        "values (?,?,?,?,?,?)", (f"{hid}-{n}", hid, tid, n, NOW, NOW))
    con.commit()
    con.close()
    nodes = "".join(f'        <NODE Id="{1000 + i:X}" ParentId="0" Attribute="0" Timestamp="1791460000000" '
                    f'Lib_Type="0" CheckType="0"/>\n' for i in range(1, seq))
    (dirpath / "masterPlaylists6.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n\n<MASTER_PLAYLIST Version="3.0.0" AutomaticSync="0">\n'
        '  <PRODUCT Name="rekordbox" Version="7.2.19" Company="AlphaTheta"/>\n  <PLAYLISTS>\n'
        f'{nodes}  </PLAYLISTS>\n</MASTER_PLAYLIST>\n', encoding="utf-8")
    return db
