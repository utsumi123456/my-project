import unittest

from setagent.rekordbox.anlz import AnlzFile, Beat, Phrase, SongStructure
from setagent.analysis.energy import UNKNOWN, set_energy_curve, track_energy_at


def anlz(phr, end_beat, bpm=160.0):
    a = AnlzFile(beats=[Beat((i % 4) + 1, bpm, int(i * 60000 / bpm)) for i in range(end_beat)])
    a.structure = SongStructure(1, end_beat, 0, [Phrase(i + 1, b, 0, lab) for i, (b, lab) in enumerate(phr)])
    return a


class Src:
    def __init__(self, m): self.m = m
    def track(self, i):
        from dataclasses import make_dataclass
        return self.m[i]


class EnergyTests(unittest.TestCase):
    def test_chorus_higher_than_intro(self):
        a = anlz([(1, "intro"), (65, "chorus")], 129)
        self.assertLess(track_energy_at(a, 0.05), track_energy_at(a, 0.95))

    def test_no_phrases_is_unknown(self):
        self.assertEqual(track_energy_at(AnlzFile(), 0.5), UNKNOWN)

    def test_curve_marks_known_vs_unknown(self):
        from setagent.analysis.timing import Placement, Timeline
        pl = (Placement(0, "a", "A", 0, 100, 100, 160, 160, False, ()),
              Placement(1, "b", "B", 100, 200, 100, 160, 160, False, ()))
        tl = Timeline(pl, 200, 200, 60, ())
        a = anlz([(1, "intro"), (33, "chorus")], 65)
        curve = set_energy_curve(tl, {"a": a})           # b has no anlz
        self.assertTrue(any(p.known for p in curve))
        self.assertTrue(any(not p.known for p in curve))
        self.assertTrue(all(0 <= p.energy <= 1 for p in curve))


if __name__ == "__main__":
    unittest.main()
