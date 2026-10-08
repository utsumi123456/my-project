"""Write-back into rekordbox (A): only the Set Agent folder, only when rekordbox
is closed, always backed up and read back. Runs against a real SQLCipher
master.db built from the rekordbox 7 schema (tests/rbfixture.py)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from setagent.rekordbox import writeback as wb
from tests import rbfixture
from tools.decrypt_masterdb import decrypt

HAVE, WHY = wb.available()


def plain(master: Path, d: Path) -> sqlite3.Connection:
    out = d / f"plain-{len(list(d.glob('plain-*')))}.db"
    wal = master.with_name("master.db-wal")
    decrypt(master, out, wal=wal if wal.exists() else None)
    return sqlite3.connect(out)


@unittest.skipUnless(HAVE, WHY)
class WritebackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.master = rbfixture.build(self.d / "rb", playlists={"acid": ["1", "2", "3"]})
        self.backups = wb.Backups(self.d / "backups", keep=3)
        # not the live library: the running-guard is waived, as for a copy
        self.writer = wb.Writer(self.backups, running=lambda: False, live=[])

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, ids, name="acid 60"):
        con = plain(self.master, self.d)
        con.close()
        return wb.plan_publish(sorted(self.d.glob("plain-*.db"))[-1], ids, name, source="acid")

    def test_creates_folder_and_playlist_in_draft_order(self):
        p = self.plan(["3", "1", "5"])
        self.assertFalse(p.replaces)
        self.assertFalse(p.folder_exists)
        r = self.writer.publish(self.master, p)
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.tracks, 3)
        self.assertTrue(r.backup_id)
        con = plain(self.master, self.d)
        folder = con.execute("select ID, ParentID, Attribute from djmdPlaylist where Name='Set Agent'").fetchone()
        self.assertEqual((folder[1], folder[2]), ("root", 1))
        pl = con.execute("select ID, ParentID from djmdPlaylist where Name='acid 60'").fetchone()
        self.assertEqual(pl[1], folder[0])
        order = [r[0] for r in con.execute(
            "select ContentID from djmdSongPlaylist where PlaylistID=? order by TrackNo", (pl[0],))]
        self.assertEqual(order, ["3", "1", "5"])
        # rekordbox lists playlists from masterPlaylists6.xml too; both must know it
        xml = (self.master.parent / "masterPlaylists6.xml").read_text(encoding="utf-8")
        self.assertIn(f'Id="{int(pl[0]):X}"', xml)
        self.assertIn(f'Id="{int(folder[0]):X}"', xml)

    def test_rewrites_same_name_and_never_touches_other_playlists(self):
        self.assertTrue(self.writer.publish(self.master, self.plan(["1", "2"])).ok)
        p2 = self.plan(["4", "2", "6"])
        self.assertTrue(p2.replaces)
        self.assertEqual(p2.replaces_count, 2)
        r = self.writer.publish(self.master, p2)
        self.assertTrue(r.ok, r.error)
        self.assertTrue(r.replaced)
        con = plain(self.master, self.d)
        self.assertEqual(con.execute("select count(*) from djmdPlaylist where Name='acid 60' "
                                     "and rb_local_deleted=0").fetchone()[0], 1)
        self.assertEqual(con.execute("select count(*) from djmdPlaylist where Name='Set Agent'").fetchone()[0], 1)
        got = [r[0] for r in con.execute(
            "select s.ContentID from djmdSongPlaylist s join djmdPlaylist p on p.ID=s.PlaylistID "
            "where p.Name='acid 60' and s.rb_local_deleted=0 order by s.TrackNo")]
        self.assertEqual(got, ["4", "2", "6"])
        # the DJ's own playlist is untouched
        mine = [r[0] for r in con.execute(
            "select ContentID from djmdSongPlaylist where PlaylistID='1001' order by TrackNo")]
        self.assertEqual(mine, ["1", "2", "3"])

    def test_missing_and_duplicate_tracks_are_skipped_in_the_plan(self):
        p = self.plan(["1", "999", "1", "2"])
        self.assertEqual(p.track_ids, ["1", "2"])
        self.assertEqual({s["why"] for s in p.skipped}, {"コレクションにありません", "重複"})
        self.assertIn("入りません", p.describe())

    def test_refuses_while_rekordbox_runs_on_the_live_library(self):
        w = wb.Writer(self.backups, running=lambda: True, live=[self.master])
        before = self.master.read_bytes()
        r = w.publish(self.master, self.plan(["1"]))
        self.assertFalse(r.ok)
        self.assertIn("rekordbox が起動しています", r.error)
        self.assertEqual(r.backup_id, "")                  # refused before anything happened
        self.assertEqual(self.master.read_bytes(), before)

    def test_verification_failure_restores_the_backup(self):
        before = self.master.read_bytes()
        orig = wb.read_playlist
        wb.read_playlist = lambda *a: ["nope"]
        try:
            r = self.writer.publish(self.master, self.plan(["1", "2"]))
        finally:
            wb.read_playlist = orig
        self.assertFalse(r.ok)
        self.assertTrue(r.restored)
        self.assertEqual(self.master.read_bytes(), before)

    def test_restore_is_itself_backed_up_and_keeps_the_target(self):
        r1 = self.writer.publish(self.master, self.plan(["1"]))
        for ids in (["2"], ["3"], ["4"]):                  # push r1's backup to the oldest slot
            self.assertTrue(self.writer.publish(self.master, self.plan(ids)).ok)
        ids = [b.id for b in self.backups.list()]
        self.assertEqual(len(ids), 3)
        oldest = ids[-1]
        out = self.writer.restore(self.master, oldest)
        self.assertTrue(out["ok"])
        self.assertIn(out["safety_backup"], [b.id for b in self.backups.list()])
        self.assertTrue(r1.ok)

    def test_metadata_edits_are_written_and_read_back(self):
        plan = wb.MetadataPlan("tags", [
            {"track_id": "1", "comment": "opener", "comment_mode": "append"},
            {"track_id": "2", "rating": 9, "color": "aqua"},
            {"track_id": "3", "color": "beige"},                      # not a rekordbox colour: dropped
        ])
        r = self.writer.publish(self.master, plan)
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.tracks, 2)
        self.assertTrue(r.backup_id)
        con = plain(self.master, self.d)
        got = dict((i, (c, rt, col)) for i, c, rt, col in con.execute(
            "select ID, coalesce(Commnt,''), Rating, coalesce(ColorID,'') from djmdContent where ID in ('1','2','3')"))
        self.assertEqual(got["1"][0], "opener")
        self.assertEqual(got["2"][1:], (5, "6"))                       # rating clamped to 5, aqua = 6
        self.assertEqual(got["3"][2], "")

    def test_metadata_refused_while_rekordbox_runs(self):
        w = wb.Writer(self.backups, running=lambda: True, live=[self.master])
        r = w.publish(self.master, wb.MetadataPlan("t", [{"track_id": "1", "rating": 3}]))
        self.assertFalse(r.ok)
        self.assertEqual(r.backup_id, "")

    def test_clean_name(self):
        self.assertEqual(wb.clean_name("  a\tb\nc "), "a b c")
        self.assertEqual(wb.clean_name(""), "Set Agent")
        self.assertEqual(len(wb.clean_name("x" * 500)), wb.NAME_MAX)


class GuardTests(unittest.TestCase):
    def test_is_live_library(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "master.db"; a.write_bytes(b"x")
            b = Path(d) / "copy.db"; b.write_bytes(b"x")
            self.assertTrue(wb.is_live_library(a, [a]))
            self.assertFalse(wb.is_live_library(b, [a]))


if __name__ == "__main__":
    unittest.main()
