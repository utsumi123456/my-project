"""Ranking tracks to drop: buried ones first, peaks and locked ones never."""
import unittest
from setagent.analysis.curve import TargetCurve
from setagent.analysis.removal import pick_removals, removal_candidates
from setagent.domain.draft import SetDraft, SetLock, SetMilestone, TrackEntry
from setagent.rekordbox.anlz import AnlzFile, Phrase, SongStructure
from setagent.rekordbox.masterdb import Track


def T(i, bpm=160.0, key="Am", length=300):
    return Track(i, i.upper() + " track", "Artist", bpm, length, key, None, 0, f"C:/m/{i}.mp3", 1)


class Lib:
    def __init__(self, *ts):
        self.m = {t.id: t for t in ts}
    def track(self, i): return self.m[i]


def anlz(label):
    """An ANLZ file whose whole structure is one phrase label."""
    return AnlzFile(structure=SongStructure(1, 512, 1, [Phrase(0, 1, 1, label)]))


def draft(*ids):
    d = SetDraft(tracks=[TrackEntry(i) for i in ids])
    d.constraints.default_overlap_bars = 0
    return d


class RemovalTest(unittest.TestCase):
    def setUp(self):
        self.lib = Lib(T("a"), T("b"), T("c"), T("d"), T("e"))

    def test_locked_and_milestone_tracks_are_never_candidates(self):
        d = draft("a", "b", "c", "d", "e")
        SetLock("b", "position", True).execute(d)
        SetMilestone("d", True, 600).execute(d)
        ids = {c.track_id for c in removal_candidates(d, self.lib, {}, None)}
        self.assertEqual(ids, {"a", "c", "e"})

    def test_without_phrase_data_it_says_so_and_still_ranks(self):
        d = draft("a", "b", "c")
        cands = removal_candidates(d, self.lib, {}, None)
        self.assertEqual(len(cands), 3)
        self.assertTrue(all(any("フレーズ解析がなく" in r for r in c.reasons) for c in cands))

    def test_bad_seam_scores_lower(self):
        lib = Lib(T("a", 160.0, "Am"), T("b"), T("c", 160.0, "Am"),
                  T("d"), T("e", 175.0, "F#m"))
        d = draft("a", "b", "c", "d", "e")
        cands = {c.track_id: c for c in removal_candidates(d, lib, {}, None)}
        # removing b leaves a|c: same BPM, same key. removing d leaves c|e: +9% BPM, far key
        self.assertGreater(cands["b"].score, cands["d"].score)
        self.assertTrue(any("BPM" in r for r in cands["d"].reasons))
        self.assertTrue(any("キー" in r for r in cands["d"].reasons))

    def test_peak_is_protected_and_buried_track_goes_first(self):
        d = draft("a", "b", "c", "d", "e")
        by = {"a": anlz("verse1"), "b": anlz("verse1"), "c": anlz("verse1"),
              "d": anlz("chorus"), "e": anlz("verse1")}
        cands = {c.track_id: c for c in removal_candidates(d, self.lib, by, None)}
        self.assertLess(cands["d"].score, cands["b"].score)
        self.assertTrue(any("山" in r for r in cands["d"].reasons))
        self.assertTrue(any("埋もれ" in r for r in cands["b"].reasons))

    def test_deviation_from_target_curve_adds_to_the_score(self):
        d = draft("a", "b", "c")
        by = {"a": anlz("chorus"), "b": anlz("chorus"), "c": anlz("chorus")}
        low = TargetCurve([(0.0, 0.3), (1.0, 0.3)])
        flat = removal_candidates(d, self.lib, by, None)
        off = removal_candidates(d, self.lib, by, low)
        self.assertGreater(off[0].score, flat[0].score)
        self.assertTrue(any("目標カーブ" in r for r in off[0].reasons))

    def test_pick_covers_the_need_and_skips_neighbours(self):
        d = draft("a", "b", "c", "d", "e")
        cands = removal_candidates(d, self.lib, {}, None)
        picked = pick_removals(cands, 550)          # two 300 s tracks
        self.assertEqual(len(picked), 2)
        idx = sorted(p.index for p in picked)
        self.assertGreater(idx[1] - idx[0], 1)

    def test_pick_returns_nothing_when_it_cannot_reach(self):
        d = draft("a", "b")
        SetLock("a", "range", True).execute(d)
        cands = removal_candidates(d, self.lib, {}, None)
        self.assertEqual(pick_removals(cands, 500), [])


if __name__ == "__main__":
    unittest.main()
