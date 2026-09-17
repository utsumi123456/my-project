# -*- coding: utf-8 -*-
"""The shared fit plan, its two tools, and the compact tool outputs."""
import json
import unittest

from setagent.agent.fitplan import plan_fit, scored_removals
from setagent.agent.mcp_server import TEXT_CAP, _tool_text
from setagent.agent.tools import TOOL_DISPATCH, TOOL_SCHEMA
from test_agent import draft, tools


class FitPlanTests(unittest.TestCase):
    def test_no_target_is_reported_not_planned(self):
        p = plan_fit(tools(draft(*"abcdef")))
        self.assertIsNone(p.target_s)
        self.assertFalse(p.already_fits)
        self.assertEqual(p.operations, [])

    def test_inside_target_needs_nothing(self):
        p = plan_fit(tools(draft(*"abc", target=1500)))
        self.assertTrue(p.already_fits)
        self.assertTrue(p.reaches_target)
        self.assertEqual(p.to_json()["over"], "0:00")

    def test_over_target_removes_whole_tracks_and_reaches(self):
        t = tools(draft(*"abcdef", target=1500))            # 30:00 vs 25:00, no phrase data
        p = plan_fit(t)
        self.assertGreater(p.over_s, 0)
        self.assertEqual(p.range_ops, [])                    # nothing to trim without phrases
        self.assertTrue(p.removals)
        self.assertTrue(all(o["op"] == "remove" for o in p.operations))
        self.assertTrue(p.reaches_target)
        j = p.to_json()
        self.assertEqual(j["total"], "30:00")
        self.assertEqual(j["target"], "25:00")
        self.assertEqual(j["removals"]["count"], len(p.removals))
        self.assertEqual(j["operations"], p.operations)
        self.assertIn("set.propose_changes", j["how_to_use"])

    def test_locked_tracks_are_never_removed(self):
        from setagent.domain.draft import SetLock
        d = draft(*"abcdef", target=1500)
        for e in d.tracks[:4]:
            e.locks.add("position")
        p = plan_fit(tools(d))
        for c in p.removals:
            self.assertNotIn(c.track_id, [e.track_id for e in d.tracks[:4]])

    def test_plan_tool_accepts_a_target_and_proposal_reaches_it(self):
        t = tools(draft(*"abcdef"))
        out = t.call("analysis.plan_fit_to_target", {"target": "20:00"})
        self.assertEqual(out["target"], "20:00")
        self.assertTrue(out["reaches_target"])
        sim = t.call("analysis.simulate", {"operations": out["operations"]})
        self.assertTrue(sim["within_target"])
        r = t.call("set.propose_changes", {"reason": "test", "operations": out["operations"]})
        self.assertTrue(r["accepted"])

    def test_removal_candidates_tool_is_scored_and_bounded(self):
        out = tools(draft(*"abcdef", target=1500)).call("analysis.removal_candidates", {"limit": 3})
        self.assertLessEqual(len(out), 3)
        self.assertEqual(out, sorted(out, key=lambda c: -c["score"]))
        for c in out:
            for k in ("index", "track_id", "title", "saves", "reasons"):
                self.assertIn(k, c)

    def test_advisor_and_tool_agree(self):
        from setagent.agent.advisor import Advisor
        t = tools(draft(*"abcdef", target=1500))
        r = Advisor(t).ask("25:00 に収めて")
        plan = t.call("analysis.plan_fit_to_target", {})
        self.assertIsNotNone(r.change_set)
        self.assertEqual(len(r.change_set.items), len(plan["operations"]))

    def test_dispatch_and_schema_include_the_new_tools(self):
        names = {t["name"] for t in TOOL_SCHEMA}
        self.assertIn("analysis.plan_fit_to_target", names)
        self.assertIn("analysis.removal_candidates", names)
        self.assertEqual(sorted(TOOL_DISPATCH), sorted(names))


class CompactOutputTests(unittest.TestCase):
    def test_draft_and_summary_omit_defaults(self):
        t = tools(draft(*"abcdef", target=1500))
        d = t.get_draft()
        self.assertEqual(d["track_count"], 6)
        for tr in d["tracks"]:
            self.assertNotIn("locks", tr)
            self.assertNotIn("is_milestone", tr)
            self.assertNotIn("target_time", tr)
            self.assertNotIn("play_in_ms", tr)
        s = t.get_set_summary()
        for tr in s["tracks"]:
            self.assertNotIn("set_tempo", tr)          # same as bpm -> omitted
            self.assertNotIn("warnings", tr)
        self.assertEqual(s["total"], "30:00")

    def test_long_lists_are_cut_not_broken(self):
        big = {"total": "1:00", "tracks": [{"i": i, "title": "x" * 200} for i in range(400)]}
        r = _tool_text(big)
        text = r["content"][0]["text"]
        self.assertLessEqual(len(text), TEXT_CAP)
        out = json.loads(text)                        # still valid JSON
        self.assertEqual(out["total"], "1:00")
        self.assertLess(len(out["tracks"]), 400)
        self.assertIn("truncated", out)
        lst = _tool_text([{"t": "y" * 300} for _ in range(300)])
        out = json.loads(lst["content"][0]["text"])
        self.assertIn("truncated", out[-1])


if __name__ == "__main__":
    unittest.main()
