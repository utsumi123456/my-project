# -*- coding: utf-8 -*-
"""Target BPM defaults and change-point labelling (feedback 2026-09-17)."""
import unittest

from setagent.webui.api import median_bpm
from setagent.webui.state import build
from test_agent import LIB, draft


class MedianBpmTests(unittest.TestCase):
    def test_median_is_rounded_and_ignores_missing(self):
        self.assertEqual(median_bpm([138.0, 160.0, 174.0]), 160.0)
        self.assertEqual(median_bpm([140.0, 150.0]), 145.0)
        self.assertEqual(median_bpm([139.6, 140.2, 0, None]), 140.0)
        self.assertIsNone(median_bpm([]))
        self.assertIsNone(median_bpm([0, None]))


class ChangePointViewTests(unittest.TestCase):
    def test_change_points_carry_the_bpm_they_change_from(self):
        d = draft(*"abcdef")
        d.constraints.set_bpm = 140.0
        d.constraints.bpm_changes = {"b": 150.0, "d": 170.0}
        st = build(d, LIB, {})
        self.assertEqual(st["set_bpm"], 140.0)
        cps = st["bpm_changes"]
        self.assertEqual([(c["i"], c["from_bpm"], c["bpm"]) for c in cps],
                         [(1, 140.0, 150.0), (3, 150.0, 170.0)])

    def test_first_change_point_without_set_bpm_has_no_from(self):
        d = draft(*"abc")
        d.constraints.bpm_changes = {"c": 170.0}
        cps = build(d, LIB, {})["bpm_changes"]
        self.assertEqual(cps[0]["from_bpm"], None)


if __name__ == "__main__":
    unittest.main()
