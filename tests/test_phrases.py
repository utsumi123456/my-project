import copy
import unittest

from setagent.rekordbox.anlz import AnlzFile, Beat, Phrase, SongStructure
from setagent.analysis.phrases import PRESET_CONFIG, drop_blocks, preset_range, blocks


def grid(n_beats, bpm=160.0):
    step = 60000 / bpm
    return [Beat((i % 4) + 1, bpm, int(i * step)) for i in range(n_beats)]


def anlz(phr, end_beat, mood=1, bpm=160.0):
    a = AnlzFile(beats=grid(end_beat, bpm))
    a.structure = SongStructure(mood, end_beat, 0, [Phrase(i + 1, b, 0, lab) for i, (b, lab) in enumerate(phr)])
    return a


class PhraseTests(unittest.TestCase):
    def test_blocks_merge_consecutive_choruses(self):
        a = anlz([(1, "intro"), (33, "up"), (65, "chorus"), (97, "chorus"), (161, "outro")], 225)
        bl = blocks(a.structure.phrases, 225)
        self.assertEqual([(b.label, b.bars) for b in bl], [("intro", 8), ("up", 8), ("drop", 24), ("outro", 16)])

    def test_one_drop_lead_in_and_tail(self):
        a = anlz([(1, "intro"), (129, "chorus"), (257, "verse1"), (385, "outro")], 513)
        r = preset_range(a, "one_drop")
        # 16-bar lead-in before beat 129 -> beat 65; 8-bar tail after 257 -> 289
        self.assertEqual((r.start_beat, r.end_beat), (65, 289))
        self.assertEqual(r.play_in_ms, a.beats[64].time_ms)

    def test_two_drop_spans_second_block(self):
        a = anlz([(1, "intro"), (65, "chorus"), (129, "verse1"), (193, "chorus"), (257, "outro")], 321)
        r1, r2 = preset_range(a, "one_drop"), preset_range(a, "two_drop")
        self.assertLess(r1.end_beat, r2.end_beat)
        self.assertEqual(r2.end_beat, 257 + 32)

    def test_short_drops_are_ignored(self):
        a = anlz([(1, "intro"), (65, "chorus"), (73, "verse1"), (193, "chorus"), (257, "outro")], 321)
        self.assertEqual([b.start_beat for b in drop_blocks(a)], [193])   # 2-bar chorus skipped

    def test_no_drop_falls_back_to_short_with_note(self):
        a = anlz([(1, "intro"), (33, "verse1"), (289, "outro")], 321, mood=2)
        r = preset_range(a, "one_drop")
        self.assertIn("fell back", r.note)
        self.assertEqual((r.start_beat, r.end_beat), (1, 321))

    def test_max_drop_cap(self):
        a = anlz([(1, "intro"), (33, "chorus"), (1033, "outro")], 1065)
        cfg = copy.deepcopy(PRESET_CONFIG); cfg["max_drop_bars"] = 32
        r = preset_range(a, "one_drop", cfg)
        self.assertEqual(r.end_beat, 33 + 32 * 4 + 8 * 4)
        self.assertIn("capped", r.note)

    def test_no_phrases_returns_full_with_note(self):
        a = AnlzFile(beats=grid(100))
        r = preset_range(a, "one_drop")
        self.assertEqual(r.preset, "full"); self.assertIn("no phrase", r.note)

    def test_no_beatgrid_returns_none(self):
        self.assertIsNone(preset_range(AnlzFile(), "full"))


if __name__ == "__main__":
    unittest.main()
