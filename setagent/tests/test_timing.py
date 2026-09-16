import unittest
from dataclasses import dataclass

from setagent.domain.draft import (History, Insert, LockedError, Move, Remove, SetDraft,
                                   SetLock, SetRange, SetTargetLength, SetTempo, SetTransition,
                                   TrackEntry)
from setagent.analysis.timing import compute, fmt, simulate, trim_candidates


@dataclass
class T:
    id: str; title: str; bpm: float; length_s: int


class Src:
    def __init__(self, *tracks): self.m = {t.id: t for t in tracks}
    def track(self, i): return self.m[i]


SRC = Src(T("a", "A", 160.0, 300), T("b", "B", 160.0, 240), T("c", "C", 170.0, 200))


def draft(*ids, overlap=0):
    d = SetDraft(tracks=[TrackEntry(i) for i in ids])
    d.constraints.default_overlap_bars = overlap
    return d


class TimingTests(unittest.TestCase):
    def test_total_is_sum_without_overlap(self):
        tl = compute(draft("a", "b"), SRC)
        self.assertAlmostEqual(tl.total_s, 540)
        self.assertEqual([p.start_s for p in tl.placements], [0, 300])

    def test_tempo_scales_duration(self):
        d = draft("a"); d.tracks[0].tempo = 176.0            # +10%
        self.assertAlmostEqual(compute(d, SRC).total_s, 300 * 160 / 176)

    def test_range_scales_duration(self):
        d = draft("a"); d.tracks[0].play_in_ms = 60_000; d.tracks[0].play_out_ms = 180_000
        self.assertAlmostEqual(compute(d, SRC).total_s, 120)

    def test_overlap_subtracts_bars_at_set_tempo(self):
        d = draft("a", "b", overlap=8)                         # 8 bars @160 = 12 s
        tl = compute(d, SRC)
        self.assertAlmostEqual(tl.placements[1].start_s, 288)
        self.assertAlmostEqual(tl.total_s, 528)
        self.assertTrue(tl.placements[0].estimated_overlap)
        self.assertIn("estimate", tl.warnings[-1])

    def test_removing_track_shifts_following(self):
        d = draft("a", "b", "c"); h = History(d)
        before = compute(d, SRC).placements[2].start_s
        h.run(Remove("b"))
        self.assertAlmostEqual(compute(d, SRC).placements[1].start_s, before - 240)
        h.undo()
        self.assertEqual(len(d.tracks), 3)

    def test_target_warning(self):
        d = draft("a", "b"); d.constraints.target_length_s = 480; d.constraints.tolerance_s = 30
        self.assertIn("over target by 1:00", compute(d, SRC).warnings)
        self.assertEqual(fmt(compute(d, SRC).delta_s), "1:00")

    def test_simulate_does_not_mutate(self):
        d = draft("a", "b")
        tl = simulate(d, SRC, [SetTempo("a", 176.0)])
        self.assertLess(tl.total_s, 540)
        self.assertIsNone(d.tracks[0].tempo)

    def test_locks_block_commands_atomically(self):
        d = draft("a", "b"); h = History(d)
        h.run(SetLock("a", "tempo", True))
        with self.assertRaises(LockedError):
            h.run_all([SetTempo("b", 170.0), SetTempo("a", 170.0)])
        self.assertIsNone(d.tracks[1].tempo)   # nothing applied

    def test_trim_candidates_sorted_and_respect_locks(self):
        d = draft("a", "b"); h = History(d); h.run(SetLock("a", "all", True))
        cands = trim_candidates(d, SRC, presets={"a": (0, 100_000), "b": (0, 100_000)})
        self.assertTrue(all(c.track_id == "b" for c in cands))
        self.assertEqual(cands[0].action, "range->one_drop")
        self.assertGreater(cands[0].saves_s, cands[-1].saves_s)

    def test_bpm_jump_warning(self):
        d = draft("a", "c")
        d.tracks[1].tempo = 180.0
        self.assertTrue(any("BPM jump" in w for w in compute(d, SRC).placements[1].warnings))

    def test_checkpoint_restore(self):
        d = draft("a", "b"); h = History(d); h.checkpoint("v1")
        h.run(Move("b", 0)); h.run(Insert("c", 1))
        h.restore("v1")
        self.assertEqual([t.track_id for t in d.tracks], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
