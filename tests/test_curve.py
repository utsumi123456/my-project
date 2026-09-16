import unittest

from setagent.analysis.curve import (TEMPLATES, Segment, TargetCurve, deviation,
                                     flat_segments, template)
from setagent.analysis.energy import EnergyPoint


def pts(*pairs, known=True):
    return [EnergyPoint(t, e, known) for t, e in pairs]


class TargetCurveTests(unittest.TestCase):
    def test_interpolates_between_control_points(self):
        c = TargetCurve([(0.0, 0.0), (1.0, 1.0)])
        self.assertAlmostEqual(c.at(0.5), 0.5)
        self.assertAlmostEqual(c.at(0.25), 0.25)

    def test_spans_the_whole_set_even_if_points_do_not(self):
        c = TargetCurve([(0.3, 0.6), (0.7, 0.9)])
        self.assertEqual(c.points[0][0], 0.0)
        self.assertEqual(c.points[-1][0], 1.0)
        self.assertAlmostEqual(c.at(0.0), 0.6)
        self.assertAlmostEqual(c.at(1.0), 0.9)

    def test_points_are_sorted_and_clamped(self):
        c = TargetCurve([(0.8, 2.0), (0.2, -1.0)])
        self.assertEqual([p[0] for p in c.points], sorted(p[0] for p in c.points))
        self.assertTrue(all(0.0 <= y <= 1.0 for _, y in c.points))

    def test_at_time_uses_total_length(self):
        c = TargetCurve([(0.0, 0.0), (1.0, 1.0)])
        self.assertAlmostEqual(c.at_time(1800, 3600), 0.5)

    def test_endpoints_keep_their_position_when_dragged(self):
        c = TargetCurve([(0.0, 0.2), (0.5, 0.5), (1.0, 0.2)])
        c.move_point(0, 0.4, 0.9)
        self.assertEqual(c.points[0][0], 0.0)
        self.assertAlmostEqual(c.points[0][1], 0.9)

    def test_endpoints_cannot_be_removed(self):
        c = TargetCurve([(0.0, 0.2), (0.5, 0.5), (1.0, 0.2)])
        c.remove_point(0); c.remove_point(len(c.points) - 1)
        self.assertEqual(len(c.points), 3)
        c.remove_point(1)
        self.assertEqual(len(c.points), 2)

    def test_editing_marks_the_curve_custom(self):
        c = template("build")
        self.assertEqual(c.name, "build")
        c.move_point(1, 0.3, 0.8)
        self.assertEqual(c.name, "custom")

    def test_four_templates_exist_and_are_well_formed(self):
        self.assertEqual(len(TEMPLATES), 4)
        for name in TEMPLATES:
            c = template(name)
            self.assertEqual(c.points[0][0], 0.0)
            self.assertEqual(c.points[-1][0], 1.0)
            self.assertTrue(all(0.0 <= y <= 1.0 for _, y in c.points))


class DeviationTests(unittest.TestCase):
    def test_matching_curve_has_no_deviation(self):
        c = TargetCurve([(0.0, 0.5), (1.0, 0.5)])
        p = pts(*[(t, 0.5) for t in range(0, 601, 60)])
        self.assertEqual(deviation(p, c, 600), [])

    def test_reports_an_over_segment(self):
        c = TargetCurve([(0.0, 0.3), (1.0, 0.3)])
        p = pts(*[(t, 0.9) for t in range(0, 601, 60)])
        segs = deviation(p, c, 600)
        self.assertEqual([s.kind for s in segs], ["over"])
        self.assertAlmostEqual(segs[0].start_s, 0)
        self.assertAlmostEqual(segs[0].end_s, 600)
        self.assertGreater(segs[0].value, 0)

    def test_reports_an_under_segment(self):
        c = TargetCurve([(0.0, 0.9), (1.0, 0.9)])
        p = pts(*[(t, 0.2) for t in range(0, 601, 60)])
        segs = deviation(p, c, 600)
        self.assertEqual([s.kind for s in segs], ["under"])
        self.assertLess(segs[0].value, 0)

    def test_short_blips_are_ignored(self):
        c = TargetCurve([(0.0, 0.3), (1.0, 0.3)])
        p = pts((0, 0.3), (10, 0.95), (20, 0.3), (600, 0.3))
        self.assertEqual(deviation(p, c, 600, min_duration_s=45), [])

    def test_unknown_points_are_skipped(self):
        c = TargetCurve([(0.0, 0.3), (1.0, 0.3)])
        p = pts(*[(t, 0.95) for t in range(0, 601, 60)], known=False)
        self.assertEqual(deviation(p, c, 600), [])


class FlatTests(unittest.TestCase):
    def test_a_long_plateau_is_reported_once(self):
        p = pts(*[(t, 0.5) for t in range(0, 601, 30)])
        segs = flat_segments(p, min_duration_s=300)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].kind, "flat")
        self.assertAlmostEqual(segs[0].start_s, 0)
        self.assertAlmostEqual(segs[0].end_s, 600)

    def test_a_moving_curve_is_not_flat(self):
        p = pts(*[(t, 0.2 + 0.8 * (t / 600)) for t in range(0, 601, 30)])
        self.assertEqual(flat_segments(p, min_duration_s=300), [])

    def test_short_plateau_is_not_reported(self):
        p = pts(*[(t, 0.5) for t in range(0, 121, 30)], )
        self.assertEqual(flat_segments(p, min_duration_s=300), [])

    def test_two_plateaus_separated_by_a_peak(self):
        flat_a = [(t, 0.3) for t in range(0, 361, 30)]
        peak = [(390, 0.95), (420, 0.95)]
        flat_b = [(t, 0.35) for t in range(450, 841, 30)]
        segs = flat_segments(pts(*flat_a, *peak, *flat_b), min_duration_s=300)
        self.assertEqual(len(segs), 2)


if __name__ == "__main__":
    unittest.main()
