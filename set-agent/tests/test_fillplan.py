# -*- coding: utf-8 -*-
"""Milestone-driven build: the fill plan, its tool, and the Advisor route."""
import unittest

from setagent.agent.advisor import Advisor
from setagent.agent.fillplan import plan_fill
from setagent.agent.tools import TOOL_DISPATCH, TOOL_SCHEMA
from setagent.rekordbox.masterdb import Track
from test_agent import FakeLib, T, draft, tools


def lib_with_spares(n=12):
    """Six set tracks plus a shelf of compatible spares (160 BPM, Am/Em/C)."""
    keys = ["Am", "Em", "C", "Am", "G", "Em"]
    spares = [T(f"s{i}", f"Spare {i}", 160.0 + (i % 3) * 2, 240 + i * 10, keys[i % len(keys)]) for i in range(n)]
    return FakeLib(*[T(c, c.upper() + " track", 160.0, 300) for c in "abcdef"], *spares)


def tools_with(lib, d):
    from setagent.agent.tools import AgentTools
    return AgentTools(draft=d, lib=lib, anlz={}, curve=None)


class FillPlanTests(unittest.TestCase):
    def test_no_budget_means_a_note_not_a_plan(self):
        p = plan_fill(tools_with(lib_with_spares(), draft(*"abc")))
        self.assertEqual(p.operations, [])
        self.assertIn("Target Time", p.note)

    def test_fills_up_to_the_target_with_real_tracks(self):
        d = draft(*"abc", target=1500)                     # 15:00 now, 25:00 wanted
        lib = lib_with_spares()
        p = plan_fill(tools_with(lib, d))
        self.assertTrue(p.picks)
        ids = {t.id for t in lib.db.tracks()}
        for pk in p.picks:
            self.assertIn(pk.track_id, ids)
            self.assertNotIn(pk.track_id, "abc")
        self.assertLessEqual(p.total_after_s, 1500 + 60 + 1)
        self.assertGreater(p.total_after_s, 1500 - 300)
        # inserts apply in order: indices climb by one each time
        ats = [o["at_index"] for o in p.operations]
        self.assertEqual(ats, list(range(3, 3 + len(ats))))

    def test_sections_get_their_own_budget_from_milestone_times(self):
        d = draft(*"abcdef", target=3000)                  # 30:00 now, 50:00 wanted
        d.tracks[3].is_milestone = True
        d.tracks[3].target_time_s = 25 * 60                # track d should start at 25:00 (now 15:00)
        p = plan_fill(tools_with(lib_with_spares(), d))
        secs = {s.index: s for s in p.sections}
        self.assertEqual(len(secs), 2)
        self.assertAlmostEqual(secs[0].room_s, 600, delta=1)      # 25:00 - 15:00
        self.assertTrue(secs[0].picks)
        self.assertLessEqual(secs[0].filled_s, 600 + 60)
        # second section shares the leftover of the total target
        self.assertGreater(secs[1].room_s, 0)
        # picks of section 0 land before track d (index 3), section 1 after the end
        first_at = [pk.at_index for pk in secs[0].picks]
        self.assertTrue(all(3 <= a < 3 + len(first_at) for a in first_at))

    def test_over_budget_section_is_left_alone(self):
        d = draft(*"abcdef", target=1500)                  # 30:00 now, 25:00 wanted
        p = plan_fill(tools_with(lib_with_spares(), d))
        self.assertEqual(p.operations, [])
        self.assertIn("超えて", p.sections[0].note)

    def test_tool_and_schema(self):
        names = {t["name"] for t in TOOL_SCHEMA}
        self.assertIn("analysis.plan_fill_sections", names)
        self.assertEqual(sorted(TOOL_DISPATCH), sorted(names))
        d = draft(*"abc", target=1500)
        out = tools_with(lib_with_spares(), d).call("analysis.plan_fill_sections", {})
        self.assertGreater(out["added_tracks"], 0)
        self.assertEqual(len(out["operations"]), out["added_tracks"])
        self.assertTrue(all(o["op"] == "insert" for o in out["operations"]))
        out2 = tools_with(lib_with_spares(), d).call("analysis.plan_fill_sections", {"playlist": "nope"})
        self.assertIn("error", out2)

    def test_advisor_builds_a_proposal_from_the_plan(self):
        d = draft(*"abc", target=1500)
        t = tools_with(lib_with_spares(), d)
        r = Advisor(t).ask("マイルストーンの間を埋めてプレイリストを作って")
        self.assertIsNotNone(r.change_set)
        self.assertTrue(all(i.op.op == "insert" for i in r.change_set.items))
        self.assertIn("実在曲", r.text)
        r2 = Advisor(t).ask("組んで")
        self.assertIsNotNone(r2.change_set)

    def test_proposal_passes_the_milestone_guard(self):
        from setagent.agent.changeset import Proposal, build_change_set
        d = draft(*"abcdef", target=3000)
        d.tracks[3].is_milestone = True
        d.tracks[3].target_time_s = 25 * 60
        t = tools_with(lib_with_spares(), d)
        p = plan_fill(t)
        cs = build_change_set(d, t.lib, {}, Proposal.from_dict({"reason": "t", "operations": p.operations}))
        self.assertEqual(len(cs.items), len(p.operations))


if __name__ == "__main__":
    unittest.main()
