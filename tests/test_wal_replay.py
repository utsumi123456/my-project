"""WAL replay against a real SQLite WAL (plaintext, identity decoder).

SQLite writes the WAL; we replay it the way SQLite would on open and check the
merged file is a valid database containing the uncheckpointed rows. The
encrypted case differs only in the page decoder, which the main-file path
already exercises on every start.
"""
import os
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from tools.decrypt_masterdb import committed_wal_frames, replay_wal

PAGE = 4096
IDENT = lambda pgno, page: page


def pages_of(path: Path) -> list[bytes]:
    raw = path.read_bytes()
    return [raw[i:i + PAGE] for i in range(0, len(raw), PAGE)]


class WalReplayTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = Path(self.dir.name) / "m.db"
        self.wal = Path(self.dir.name) / "m.db-wal"
        con = sqlite3.connect(self.db)
        con.execute(f"PRAGMA page_size={PAGE}")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT)")
        con.execute("INSERT INTO t(name) VALUES ('base')")
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
        self.base_pages = pages_of(self.db)      # what master.db looks like: no WAL content
        self.con = sqlite3.connect(self.db, isolation_level=None)
        self.con.execute("PRAGMA wal_autocheckpoint=0")   # rekordbox-like: never checkpoint

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def merged(self) -> sqlite3.Connection:
        pages, rep = replay_wal(self.base_pages, self.wal.read_bytes(), PAGE, IDENT)
        out = Path(self.dir.name) / "merged.db"
        out.write_bytes(b"".join(pages))
        return sqlite3.connect(f"file:{out}?mode=ro", uri=True), rep

    def test_no_wal_frames_leaves_pages_alone(self):
        pages, rep = replay_wal(self.base_pages, b"", PAGE, IDENT)
        self.assertEqual(pages, self.base_pages)
        self.assertEqual(rep.frames_applied, 0)

    def test_committed_edits_become_visible(self):
        self.con.execute("INSERT INTO t(name) VALUES ('added while open')")
        self.con.execute("INSERT INTO t(name) VALUES ('reordered')")
        self.assertTrue(self.wal.stat().st_size > 32)
        con, rep = self.merged()
        names = [r[0] for r in con.execute("SELECT name FROM t ORDER BY id")]
        con.close()
        self.assertEqual(names, ["base", "added while open", "reordered"])
        self.assertEqual(rep.commits, 2)
        self.assertEqual(rep.frames_applied, rep.frames_seen)
        self.assertEqual(rep.note, "")

    def test_growth_beyond_original_size(self):
        for _ in range(200):
            self.con.execute("INSERT INTO t(name) VALUES (hex(randomblob(500)))")
        con, rep = self.merged()
        n = con.execute("SELECT count(*) FROM t").fetchone()[0]
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        con.close()
        self.assertGreaterEqual(n, 201)
        self.assertGreater(rep.db_pages, len(self.base_pages))

    def test_uncommitted_tail_is_dropped(self):
        self.con.execute("INSERT INTO t(name) VALUES ('kept')")
        self.con.execute("PRAGMA cache_size=-8")     # tiny cache so dirty pages spill into the WAL
        self.con.execute("BEGIN")
        for _ in range(400):
            self.con.execute("INSERT INTO t(name) VALUES (hex(randomblob(500)))")
        # transaction still open: its frames are in the WAL without a commit frame
        frames, rep = committed_wal_frames(self.wal.read_bytes(), PAGE)
        self.assertLess(rep.frames_applied, rep.frames_seen)
        con, _ = self.merged()
        names = [r[0] for r in con.execute("SELECT name FROM t ORDER BY id")]
        con.close()
        self.con.execute("ROLLBACK")
        self.assertEqual(names, ["base", "kept"])

    def test_torn_frame_cuts_at_checksum(self):
        self.con.execute("INSERT INTO t(name) VALUES ('first')")
        self.con.execute("INSERT INTO t(name) VALUES ('second')")
        raw = bytearray(self.wal.read_bytes())
        frames, rep = committed_wal_frames(bytes(raw), PAGE)
        # corrupt one byte inside the last frame's page
        last_off = 32 + (rep.frames_seen - 1) * (24 + PAGE) + 24 + 100
        raw[last_off] ^= 0xFF
        frames2, rep2 = committed_wal_frames(bytes(raw), PAGE)
        self.assertEqual(rep2.frames_applied, rep.frames_applied - 1)
        self.assertIn("チェックサム", rep2.note)

    def test_salt_mismatch_stops_replay(self):
        self.con.execute("INSERT INTO t(name) VALUES ('x')")
        raw = bytearray(self.wal.read_bytes())
        struct.pack_into(">I", raw, 32 + 8, 0xDEADBEEF)     # first frame's salt1
        frames, rep = committed_wal_frames(bytes(raw), PAGE)
        self.assertEqual(frames, [])
        self.assertIn("salt", rep.note)


if __name__ == "__main__":
    unittest.main()
