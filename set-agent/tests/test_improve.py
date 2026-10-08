"""Improved versions at an intervention level the DJ picks (agent.improve)."""
import unittest

from setagent.agent.improve import LEVELS, from_track_ids, improve, is_rough, rough_count, _info
from setagent.agent.tools import AgentTools
from setagent.domain.draft import SetDraft, SetTargetLength, TrackEntry
from tests.test_agent import FakeLib, T

# a chain in Am/Em/C with two clashes (F#, Eb) and one tempo cliff (128)
LIB = FakeLib(T("a", "A", 160, 300, "Am"), T("b", "B", 160, 300, "F#"), T("c", "C", 160, 300, "Em"),
              T("d", "D", 160, 300, "C"), T("e", "E", 128, 300, "Am"), T("f", "F", 160, 300, "Em"),
              T("g", "G", 160, 300, "Eb"), T("h", "H", 160, 300, "Am"),
              # library-only tracks the standard level may add
              T("p", "Pool Am", 160, 300, "Am"), T("q", "Pool Em", 161, 300, "Em"), T("r", "Pool C", 159, 300, "C"))


def make(ids, target=None, locks=(), milestones=()):
    d = SetDraft(name="t", tracks=[TrackEntry(i) for i in ids])
    d.constraints.default_overlap_bars = 0
    if target:
        SetTargetLength(target, 30).execute(d)
    for e in d.tracks:
        if e.track_id in locks:
            e.locks.add("position")
        if e.track_id in milestones:
            e.is_milestone = True
    return AgentTools(draft=d, lib=LIB, anlz={}, curve=None)


IDS = list("abcdefgh")


class ImproveTests(unittest.TestCase):
    def info(self, ids):
        return {t: _info(LIB, t, {}) for t in ids}

    def test_light_keeps_the_tracks_and_smooths(self):
        t = make(IDS)
        r = improve(t, "light")
        self.assertEqual(sorted(r.track_ids), sorted(IDS))
        self.assertEqual(r.counts["add"] + r.counts["remove"], 0)
        self.assertLessEqual(r.after["rough"], r.before["rough"])
        self.assertLess(r.after["rough"], r.before["rough"])

    def test_light_never_moves_a_locked_or_milestone_track(self):
        t = make(IDS, locks={"c"}, milestones={"f"})
        for level in LEVELS:
            r = improve(t, level)
            self.assertEqual(r.track_ids.index("c"), 2, level)
            self.assertEqual(r.track_ids.index("f"), 5, level)

    def test_light_is_capped(self):
        r = improve(make(IDS), "light")
        self.assertLessEqual(r.counts["move"], 2 * 2)       # at most 2 swaps on 8 tracks

    def test_standard_over_target_removes_until_inside(self):
        t = make(IDS, target=25 * 60, locks={"a"})
        r = improve(t, "standard")
        self.assertTrue(r.after["within"], r.after)
        self.assertIn("a", r.track_ids)
        self.assertGreater(r.counts["remove"], 0)
        self.assertEqual(r.counts["add"], 0)

    def test_standard_under_target_adds_real_library_tracks(self):
        t = make(list("acdf"), target=35 * 60)
        r = improve(t, "standard")
        added = [c.track_id for c in r.changes if c.kind == "add"]
        self.assertTrue(added)
        self.assertTrue(set(added) <= {"b", "e", "g", "h", "p", "q", "r"})
        self.assertGreater(r.after["total_s"], r.before["total_s"])

    def test_bold_rebuilds_but_keeps_the_set(self):
        r = improve(make(IDS), "bold")
        self.assertEqual(sorted(r.track_ids), sorted(IDS))
        self.assertLessEqual(r.after["rough"], improve(make(IDS), "light").after["rough"])

    def test_one_swap_is_reported_as_one_move(self):
        t = make(IDS)
        ids = list(IDS)
        ids[2], ids[3] = ids[3], ids[2]
        r = from_track_ids(t, ids)
        self.assertEqual(r.counts, {"add": 0, "remove": 0, "move": 1})

    def test_rough_detection(self):
        info = self.info(["a", "b", "e"])
        self.assertTrue(is_rough(info["a"], info["b"]))      # Am -> F# : key clash
        self.assertTrue(is_rough(info["a"], info["e"]))      # 160 -> 128 : tempo cliff
        self.assertEqual(rough_count(["a", "b", "e"], info), 2)

    def test_empty(self):
        self.assertEqual(improve(make([]), "light").note, "empty playlist")


if __name__ == "__main__":
    unittest.main()
