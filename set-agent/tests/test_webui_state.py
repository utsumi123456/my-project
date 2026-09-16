"""The view layer must not invent musical facts (spec: UI phase, design promises).

These pin down the two things the phrase strip is allowed to do:
  * map rekordbox phrase beats to SET time through the beat grid, respecting the
    play range and the set tempo
  * return NOTHING when a track has no phrase analysis -- never a filled block,
    never an interpolated middle value
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from setagent.webui.state import PHRASE_GROUP, beat_ms, phrase_spans


@dataclass(frozen=True)
class FakeBeat:
    number: int
    tempo: float
    time_ms: int


@dataclass(frozen=True)
class FakePhrase:
    index: int
    beat: int
    label: str


class FakeStructure:
    def __init__(self, phrases, end_beat):
        self.phrases = phrases
        self.end_beat = end_beat
        self.mood = 1
        self.bank = 1


class FakeAnlz:
    """120 BPM, 4/4 -> one beat every 500 ms, 128 beats = 64 s."""
    def __init__(self, phrases, end_beat=129):
        self.beats = [FakeBeat((i % 4) + 1, 120.0, i * 500) for i in range(end_beat)]
        self.structure = FakeStructure(phrases, end_beat)


def anlz_intro_drop_outro():
    return FakeAnlz([FakePhrase(0, 1, "intro"),
                     FakePhrase(1, 33, "up"),
                     FakePhrase(2, 65, "chorus"),
                     FakePhrase(3, 113, "outro")])


class BeatMapping(unittest.TestCase):
    def test_beat_ms_is_one_based(self):
        a = anlz_intro_drop_outro()
        self.assertEqual(beat_ms(a, 1), 0.0)
        self.assertEqual(beat_ms(a, 3), 1000.0)

    def test_beat_ms_clamps_instead_of_raising(self):
        a = anlz_intro_drop_outro()
        self.assertEqual(beat_ms(a, 0), 0.0)
        self.assertEqual(beat_ms(a, 10_000), a.beats[-1].time_ms)

    def test_no_beat_grid_yields_none(self):
        a = anlz_intro_drop_outro()
        a.beats = []
        self.assertIsNone(beat_ms(a, 4))


class PhraseStrip(unittest.TestCase):
    def test_full_track_spans_cover_the_play_time(self):
        a = anlz_intro_drop_outro()
        spans = phrase_spans(a, 0, None, start_s=0.0, bpm=120.0, set_tempo=120.0)
        # blocks() folds every chorus-family label into the class name "drop"
        self.assertEqual([s["label"] for s in spans], ["intro", "up", "drop", "outro"])
        self.assertEqual([s["group"] for s in spans], ["intro", "up", "chorus", "outro"])
        self.assertAlmostEqual(spans[0]["start_s"], 0.0, places=3)
        self.assertAlmostEqual(spans[-1]["end_s"], 64.0, places=3)
        for prev, nxt in zip(spans, spans[1:]):          # contiguous, no gaps
            self.assertAlmostEqual(prev["end_s"], nxt["start_s"], places=6)

    def test_play_range_clips_and_rebases_to_set_time(self):
        a = anlz_intro_drop_outro()
        # play from beat 33 (16 s) to beat 113 (56 s), landing at 100 s in the set
        spans = phrase_spans(a, 16_000, 56_000, start_s=100.0, bpm=120.0, set_tempo=120.0)
        self.assertEqual([s["label"] for s in spans], ["up", "drop"])
        self.assertAlmostEqual(spans[0]["start_s"], 100.0, places=3)
        self.assertAlmostEqual(spans[-1]["end_s"], 140.0, places=3)   # 40 s of source

    def test_set_tempo_scales_the_strip(self):
        a = anlz_intro_drop_outro()
        slow = phrase_spans(a, 0, None, start_s=0.0, bpm=120.0, set_tempo=120.0)
        fast = phrase_spans(a, 0, None, start_s=0.0, bpm=120.0, set_tempo=240.0)
        self.assertAlmostEqual(fast[-1]["end_s"], slow[-1]["end_s"] / 2, places=3)

    def test_blocks_outside_the_play_range_are_dropped(self):
        a = anlz_intro_drop_outro()
        spans = phrase_spans(a, 32_000, 40_000, start_s=0.0, bpm=120.0, set_tempo=120.0)
        self.assertTrue(spans)
        self.assertNotIn("intro", [s["label"] for s in spans])
        self.assertNotIn("outro", [s["label"] for s in spans])

    def test_no_phrase_data_returns_empty_not_a_filler_block(self):
        a = anlz_intro_drop_outro()
        a.structure = None
        self.assertEqual(phrase_spans(a, 0, None, 0.0, 120.0, 120.0), [])
        self.assertEqual(phrase_spans(None, 0, None, 0.0, 120.0, 120.0), [])

    def test_empty_phrase_list_returns_empty(self):
        a = FakeAnlz([])
        self.assertEqual(phrase_spans(a, 0, None, 0.0, 120.0, 120.0), [])


class Grouping(unittest.TestCase):
    def test_drop_and_chorus_share_a_group(self):
        self.assertEqual(PHRASE_GROUP["drop"], PHRASE_GROUP["chorus"])

    def test_every_verse_variant_maps_to_verse(self):
        for i in range(1, 7):
            self.assertEqual(PHRASE_GROUP[f"verse{i}"], "verse")

    def test_unknown_labels_fall_back_without_raising(self):
        a = FakeAnlz([FakePhrase(0, 1, "something_new")])
        spans = phrase_spans(a, 0, None, 0.0, 120.0, 120.0)
        self.assertEqual(spans[0]["group"], "verse")


if __name__ == "__main__":
    unittest.main()


class PresetLabels(unittest.TestCase):
    """The panel shows Japanese names for the Mix presets (2026-09-16 review:
    'short' meant nothing to the DJ). Every preset the engine knows must have a
    label and a one-line help, and nothing else may be labelled."""

    def test_every_engine_preset_has_a_label_and_help(self):
        from setagent.analysis.phrases import PRESET_CONFIG
        from setagent.webui.state import PRESET_HELP, PRESET_LABELS
        engine = {k for k in PRESET_CONFIG if isinstance(PRESET_CONFIG[k], dict)} | {"full"}
        self.assertEqual(set(PRESET_LABELS), engine)
        self.assertEqual(set(PRESET_HELP), engine)
        for k, v in PRESET_LABELS.items():
            self.assertNotEqual(v, k, f"{k} still shows its internal name")
            self.assertTrue(PRESET_HELP[k].endswith("。"), f"{k}: help should be a sentence")
