import unittest
from dataclasses import dataclass

from setagent.analysis.sections import milestones, sections, skeleton
from setagent.analysis.timing import compute
from setagent.domain.draft import SetDraft, SetTargetLength, TrackEntry


@dataclass
class T:
    id: str; title: str; bpm: float; length_s: int


class Src:
    def __init__(self, *tracks): self.m = {t.id: t for t in tracks}
    def track(self, i): return self.m[i]


# six 5-minute tracks, no overlap -> 30:00 total, each starts on a 5-minute mark
SRC = Src(*[T(c, c.upper(), 160.0, 300) for c in "abcdef"])


def draft(*ids):
    d = SetDraft(tracks=[TrackEntry(i) for i in ids])
    d.constraints.default_overlap_bars = 0
    return d


class MilestoneTests(unittest.TestCase):
    def test_no_milestones_gives_one_section(self):
        d = draft(*"abcdef")
        tl = compute(d, SRC)
        self.assertEqual(milestones(d, tl), [])
        secs = sections(d, tl)
        self.assertEqual(len(secs), 1)
        self.assertEqual(secs[0].track_count, 6)
        self.assertAlmostEqual(secs[0].actual_s, 1800)

    def test_milestone_delta_against_target_time(self):
        d = draft(*"abcdef")
        d.tracks[3].is_milestone = True
        d.tracks[3].target_time_s = 2700        # wants it at 45:00, actually at 15:00
        tl = compute(d, SRC)
        ms = milestones(d, tl)
        self.assertEqual(len(ms), 1)
        self.assertAlmostEqual(ms[0].actual_s, 900)
        self.assertAlmostEqual(ms[0].delta_s, -1800)

    def test_milestone_without_target_has_no_delta(self):
        d = draft(*"abc")
        d.tracks[1].is_milestone = True
        ms = milestones(d, compute(d, SRC))
        self.assertIsNone(ms[0].delta_s)


class SectionTests(unittest.TestCase):
    def test_split_at_milestone(self):
        d = draft(*"abcdef")
        d.tracks[2].is_milestone = True
        secs = sections(d, compute(d, SRC))
        self.assertEqual(len(secs), 2)
        self.assertEqual((secs[0].first_track, secs[0].last_track), (0, 1))
        self.assertEqual((secs[1].first_track, secs[1].last_track), (2, 5))

    def test_section_budget_and_slack(self):
        d = draft(*"abcdef")
        d.tracks[2].is_milestone = True
        d.tracks[2].target_time_s = 900          # section 0 budget = 0..15:00, actual 10:00
        secs = sections(d, compute(d, SRC))
        self.assertAlmostEqual(secs[0].target_s, 900)
        self.assertAlmostEqual(secs[0].actual_s, 600)
        self.assertAlmostEqual(secs[0].delta_s, -300)

    def test_room_for_tracks_uses_average_play_time(self):
        d = draft(*"abcdef")
        d.tracks[2].is_milestone = True
        d.tracks[2].target_time_s = 1200         # 10 min of slack, tracks average 5 min
        secs = sections(d, compute(d, SRC))
        self.assertEqual(secs[0].room_for_tracks, 2)

    def test_room_is_negative_when_over_budget(self):
        d = draft(*"abcdef")
        d.tracks[2].is_milestone = True
        d.tracks[2].target_time_s = 300          # wants 5 min, actually 10 min
        secs = sections(d, compute(d, SRC))
        self.assertEqual(secs[0].room_for_tracks, -1)

    def test_last_section_budget_comes_from_the_set_target(self):
        d = draft(*"abcdef")
        d.tracks[3].is_milestone = True
        d.tracks[3].target_time_s = 900
        SetTargetLength(2400).execute(d)         # 40:00 overall
        secs = sections(d, compute(d, SRC))
        self.assertAlmostEqual(secs[-1].target_s, 1500)

    def test_section_without_targets_has_no_delta(self):
        d = draft(*"abcdef")
        d.tracks[3].is_milestone = True          # no target time, no set target
        secs = sections(d, compute(d, SRC))
        self.assertIsNone(secs[-1].delta_s)
        self.assertIsNone(secs[-1].room_for_tracks)


class SkeletonTests(unittest.TestCase):
    def test_skeleton_always_includes_a_starting_point(self):
        d = draft(*"abcdef")
        self.assertEqual(len(skeleton(d, compute(d, SRC))), 1)

    def test_skeleton_lists_milestones_in_order(self):
        d = draft(*"abcdef")
        d.tracks[2].is_milestone = True
        d.tracks[4].is_milestone = True
        sk = skeleton(d, compute(d, SRC))
        self.assertEqual([m.index for m in sk], [0, 2, 4])

    def test_first_track_not_duplicated_when_it_is_a_milestone(self):
        d = draft(*"abc")
        d.tracks[0].is_milestone = True
        self.assertEqual([m.index for m in skeleton(d, compute(d, SRC))], [0])


if __name__ == "__main__":
    unittest.main()
