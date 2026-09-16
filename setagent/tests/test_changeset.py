import unittest
from dataclasses import dataclass

from setagent.agent.changeset import (ChangeSet, Op, Proposal, ProposalLog, Rejected,
                                      build_change_set, parse_mmss, snapshot)
from setagent.analysis.timing import compute
from setagent.domain.draft import History, SetDraft, SetLock, SetTargetLength, TrackEntry


@dataclass
class T:
    id: str; title: str; bpm: float; length_s: int


class Src:
    def __init__(self, *tracks): self.m = {t.id: t for t in tracks}
    def track(self, i): return self.m[i]


SRC = Src(*[T(c, c.upper(), 160.0, 300) for c in "abcdef"])
NO_ANLZ: dict = {}


def draft(*ids, target=None):
    d = SetDraft(tracks=[TrackEntry(i) for i in ids])
    d.constraints.default_overlap_bars = 0
    if target: SetTargetLength(target, 60).execute(d)
    return d


def prop(*ops, reason="test"):
    return Proposal.from_dict({"reason": reason, "operations": list(ops)})


class OpTests(unittest.TestCase):
    def test_unknown_op_is_rejected(self):
        with self.assertRaises(Rejected):
            Op.from_dict({"op": "set_colour", "track_ref": "a"})

    def test_empty_proposal_is_rejected(self):
        with self.assertRaises(Rejected):
            Proposal.from_dict({"reason": "nothing", "operations": []})

    def test_mmss_parsing(self):
        self.assertEqual(parse_mmss("45:00"), 2700)
        self.assertEqual(parse_mmss(90), 90)
        self.assertIsNone(parse_mmss(None))


class BuildTests(unittest.TestCase):
    def test_change_set_prices_the_before_and_after(self):
        d = draft(*"abcdef", target=1500)
        cs = build_change_set(d, SRC, NO_ANLZ, prop({"op": "remove", "track_ref": "c"}))
        self.assertAlmostEqual(cs.before.total_s, 1800)
        self.assertAlmostEqual(cs.after.total_s, 1500)
        self.assertTrue(any("総尺" in l for l in cs.diff_lines))

    def test_draft_is_not_touched_by_building_or_previewing(self):
        d = draft(*"abc")
        cs = build_change_set(d, SRC, NO_ANLZ, prop({"op": "remove", "track_ref": "b"}))
        cs.preview(d, SRC)
        self.assertEqual([t.track_id for t in d.tracks], ["a", "b", "c"])

    def test_locked_track_is_dropped_before_the_user_sees_it(self):
        d = draft(*"abc")
        SetLock("b", "position", True).execute(d)
        with self.assertRaises(Rejected) as ctx:
            build_change_set(d, SRC, NO_ANLZ, prop({"op": "remove", "track_ref": "b"}))
        self.assertIn("ロック", str(ctx.exception))

    def test_missing_track_is_rejected(self):
        d = draft(*"abc")
        with self.assertRaises(Rejected):
            build_change_set(d, SRC, NO_ANLZ, prop({"op": "remove", "track_ref": "zzz"}))

    def test_proposal_that_breaks_a_milestone_is_rejected(self):
        d = draft(*"abcdef")
        d.tracks[2].is_milestone = True
        d.tracks[2].target_time_s = 600          # it is exactly on target now
        with self.assertRaises(Rejected) as ctx:
            build_change_set(d, SRC, NO_ANLZ, prop({"op": "remove", "track_ref": "a"}))
        self.assertIn("目標時刻", str(ctx.exception))

    def test_proposal_that_fixes_a_milestone_is_allowed(self):
        d = draft(*"abcdef")
        d.tracks[3].is_milestone = True
        d.tracks[3].target_time_s = 600          # currently at 15:00, wants 10:00
        cs = build_change_set(d, SRC, NO_ANLZ, prop({"op": "remove", "track_ref": "a"}))
        self.assertEqual(len(cs.items), 1)


class ApprovalTests(unittest.TestCase):
    def test_partial_approval_applies_only_ticked_items(self):
        d = draft(*"abcdef")
        cs = build_change_set(d, SRC, NO_ANLZ,
                              prop({"op": "remove", "track_ref": "e"},
                                   {"op": "remove", "track_ref": "f"}))
        cs.items[1].approved = False
        h = History(d)
        h.run_all(cs.approved_commands())
        self.assertEqual([t.track_id for t in d.tracks], list("abcdf"))

    def test_ghost_preview_matches_the_applied_result(self):
        d = draft(*"abcdef")
        cs = build_change_set(d, SRC, NO_ANLZ,
                              prop({"op": "remove", "track_ref": "b"},
                                   {"op": "set_tempo", "track_ref": "c", "bpm": 176.0}))
        ghost = cs.preview(d, SRC)
        History(d).run_all(cs.approved_commands())
        self.assertAlmostEqual(ghost.total_s, compute(d, SRC).total_s)

    def test_undo_returns_to_the_pre_approval_state(self):
        d = draft(*"abcdef")
        cs = build_change_set(d, SRC, NO_ANLZ, prop({"op": "remove", "track_ref": "c"}))
        h = History(d)
        h.run_all(cs.approved_commands())
        self.assertTrue(h.undo())
        self.assertEqual([t.track_id for t in d.tracks], list("abcdef"))


class LogTests(unittest.TestCase):
    def test_rejection_rate_is_tracked(self):
        d = draft(*"abcdef")
        cs = build_change_set(d, SRC, NO_ANLZ,
                              prop({"op": "remove", "track_ref": "e"},
                                   {"op": "remove", "track_ref": "f"}))
        cs.items[1].approved = False
        log = ProposalLog()
        log.record_proposal(cs); log.record_outcome(cs)
        self.assertAlmostEqual(log.rejection_rate, 0.5)
        self.assertIn("却下率", log.summary())

    def test_a_rejected_proposal_is_recognised_next_time(self):
        d = draft(*"abcdef")
        p = {"op": "remove", "track_ref": "e"}
        cs = build_change_set(d, SRC, NO_ANLZ, prop(p))
        log = ProposalLog(); log.record_proposal(cs)
        again = build_change_set(d, SRC, NO_ANLZ, prop(p))
        self.assertTrue(log.already_seen(again))


if __name__ == "__main__":
    unittest.main()
