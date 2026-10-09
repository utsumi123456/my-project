"""Following rekordbox's selection: parse the browser status line, match it to a playlist."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from setagent.rekordbox import selection as S


class ParseTests(unittest.TestCase):
    def test_japanese(self):
        st = S.parse("22 トラック, 1 時間 37 分, 175.9 MB")
        self.assertEqual((st.tracks, st.minutes), (22, 97))
        self.assertAlmostEqual(st.size_mib, 175.9)
        self.assertAlmostEqual(st.size_step, 0.1)

    def test_english_gb(self):
        st = S.parse("96 tracks, 10 hr 55 min, 1.5 GB")
        self.assertEqual((st.tracks, st.minutes), (96, 655))
        self.assertAlmostEqual(st.size_mib, 1536.0)

    def test_minutes_only(self):
        st = S.parse("1 トラック, 8 分, 20.6 MB")
        self.assertEqual((st.tracks, st.minutes), (1, 8))

    def test_not_a_status_line(self):
        self.assertIsNone(S.parse("PERFORMANCE"))
        self.assertIsNone(S.parse(""))


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        con = sqlite3.connect(Path(self.tmp.name) / "p.db")
        con.executescript("""
          create table djmdPlaylist (ID, Name, ParentID, Attribute, rb_local_deleted default 0);
          create table djmdSongPlaylist (ID, PlaylistID, ContentID, rb_local_deleted default 0);
          create table djmdContent (ID, Length, FileSize);
          insert into djmdPlaylist values ('1','acid','root',0,0),('2','house','root',0,0),
            ('9','Set Agent','root',1,0),('3','acid (標準)','9',0,0);
          insert into djmdContent values ('a',300,10485760),('b',360,10485760),('c',100,5242880);
          insert into djmdSongPlaylist values ('s1','1','a',0),('s2','1','b',0),('s3','2','c',0),
            ('s4','3','a',0),('s5','3','b',0);
        """)
        self.fp = S.Fingerprints.build(con)
        con.close()                 # Windows cannot delete an open database in tearDown

    def tearDown(self):
        self.tmp.cleanup()

    def test_unique(self):
        hits = self.fp.match(S.parse("1 トラック, 1 分, 5.0 MB"))
        self.assertEqual([h[0] for h in hits], ["2"])

    def test_identical_copy_prefers_the_djs_own_playlist(self):
        st = S.parse("2 トラック, 11 分, 20.0 MB")
        self.assertEqual([h[0] for h in self.fp.match(st)], ["1", "3"])
        # ...unless the copy is what is already shown
        self.assertEqual(self.fp.match(st, prefer="3")[0][0], "3")

    def test_no_match_keeps_what_is_shown(self):
        self.assertEqual(self.fp.match(S.parse("4025 トラック, 242 時間 40 分, 30.1 GB")), [])

    def test_read_without_a_source_says_why(self):
        orig = S.status_text
        S.status_text = lambda: (None, "no_permission")
        try:
            self.assertEqual(S.read(self.fp)["why"], "no_permission")
        finally:
            S.status_text = orig
        S.status_text = lambda: ("2 トラック, 11 分, 20.0 MB", "ok")
        try:
            r = S.read(self.fp)
            self.assertEqual((r["playlist_id"], r["ambiguous"]), ("1", True))
        finally:
            S.status_text = orig


class FakeAX:
    """A stand-in for rekordbox's accessibility tree, with a clock that ticks per call."""

    def __init__(self, tree, cost=0.01):
        self.tree, self.cost, self.t, self.calls = tree, cost, 0.0, 0

    def clock(self):
        return self.t

    def attr(self, e, a):
        self.calls += 1
        self.t += self.cost
        return {"AXRole": e.get("role"), "AXValue": e.get("value"), "AXChildren": e.get("kids")}[a]


def node(role, *kids, value=None):
    return {"role": role, "value": value, "kids": list(kids)}


def rekordbox_window(rows=2000, status="96 トラック, 10 時間 55 分, 1.5 GB"):
    """Track list first (as in rekordbox's tree), the status line further along."""
    table = node("AXTable", *[node("AXRow", node("AXCell", node("AXStaticText", value=f"Track {i}")),
                                   node("AXCell", node("AXStaticText", value="128.00")))
                              for i in range(rows)])
    browser = node("AXGroup", node("AXScrollArea", table),
                   node("AXGroup", node("AXStaticText", value=status)))
    return node("AXWindow", node("AXGroup", node("AXStaticText", value="PERFORMANCE")), browser)


class WalkTests(unittest.TestCase):
    def test_finds_the_status_line_past_a_long_track_list(self):
        ax = FakeAX([rekordbox_window(rows=5000)])
        el, text = S.find_status(ax.tree, ax.attr, deadline=1.5, clock=ax.clock)
        self.assertEqual(text, "96 トラック, 10 時間 55 分, 1.5 GB")
        self.assertLess(ax.calls, 40)          # the table is never entered

    def test_a_track_title_that_looks_like_a_status_line_is_not_read(self):
        win = rekordbox_window(rows=3)
        win["kids"][1]["kids"][0]["kids"][0]["kids"][0]["kids"][0]["kids"][0]["value"] = "12 tracks, 8 min, 1.0 GB"
        ax = FakeAX([win])
        self.assertEqual(S.find_status(ax.tree, ax.attr, 1.5, ax.clock)[1], "96 トラック, 10 時間 55 分, 1.5 GB")

    def test_too_slow_says_busy_not_found(self):
        ax = FakeAX([rekordbox_window()], cost=1.0)
        with self.assertRaises(S.WalkTimeout):
            S.find_status(ax.tree, ax.attr, deadline=1.5, clock=ax.clock)

    def test_no_status_line(self):
        ax = FakeAX([node("AXWindow", node("AXGroup", node("AXStaticText", value="PERFORMANCE")))])
        self.assertEqual(S.find_status(ax.tree, ax.attr, 1.5, ax.clock), (None, None))

    def test_read_passes_the_poll_budget(self):
        seen = []
        orig = S.status_text
        S.status_text = lambda budget=S.WALK_BOOT_S: (seen.append(budget), (None, "busy"))[1]
        try:
            self.assertEqual(S.read(None, budget=S.WALK_POLL_S)["why"], "busy")
            S.read(None)
        finally:
            S.status_text = orig
        self.assertEqual(seen, [S.WALK_POLL_S, S.WALK_BOOT_S])


if __name__ == "__main__":
    unittest.main()
