import unittest
from dataclasses import dataclass

from setagent.agent.advisor import Advisor, Intervention
from setagent.agent.recommend import Slot, camelot, candidates, key_distance
from setagent.agent.tools import TOOL_DISPATCH, TOOL_SCHEMA, AgentTools
from setagent.analysis.curve import template
from setagent.domain.draft import SetDraft, SetLock, SetTargetLength, TrackEntry
from setagent.rekordbox.masterdb import Track


def T(i, title, bpm, length, key="Am"):
    return Track(i, title, "Artist " + i, bpm, length, key, None, 0, "C:/m/%s.mp3" % i, 1)


class FakeAnalysis:
    def __init__(self, track): self.track = track; self.anlz = None; self.reason = ""
    @property
    def phrase_status(self):
        from setagent.rekordbox.library import PhraseStatus
        return PhraseStatus.NO_ANALYSIS


class FakeDB:
    def __init__(self, m): self.m = m
    def tracks(self, include_deleted=False): return list(self.m.values())
    def playlist_by_name(self, name): raise KeyError(name)


class FakeLib:
    def __init__(self, *ts):
        self.m = {t.id: t for t in ts}
        self.db = FakeDB(self.m)
    def track(self, i): return self.m[i]
    def analysis(self, i): return FakeAnalysis(self.m[i])


LIB = FakeLib(*[T(c, c.upper() + " track", 160.0, 300) for c in "abcdef"],
              T("x", "Spare one", 160.0, 280, "Am"),
              T("y", "Wrong tempo", 100.0, 280, "Am"),
              T("z", "Wrong key", 160.0, 280, "C#"),
              T("w", "Far too long", 160.0, 1800, "Am"))


def draft(*ids, target=None):
    d = SetDraft(tracks=[TrackEntry(i) for i in ids])
    d.constraints.default_overlap_bars = 0
    if target: SetTargetLength(target, 60).execute(d)
    return d


def tools(d):
    return AgentTools(draft=d, lib=LIB, anlz={}, curve=None)


class KeyTests(unittest.TestCase):
    def test_camelot_mapping(self):
        self.assertEqual(camelot("Am"), (8, "A"))
        self.assertEqual(camelot("C"), (8, "B"))
        self.assertIsNone(camelot(""))

    def test_relative_major_minor_is_one_step(self):
        self.assertEqual(key_distance("Am", "C"), 1)

    def test_same_key_is_zero(self):
        self.assertEqual(key_distance("Am", "Am"), 0)

    def test_unknown_key_returns_none_not_a_guess(self):
        self.assertIsNone(key_distance("Am", "???"))


class RecommendTests(unittest.TestCase):
    def test_only_real_library_tracks_come_back(self):
        got = candidates(LIB, Slot(duration_s=300, bpm=160.0, key="Am"), limit=5)
        self.assertTrue(all(c.track.id in LIB.m for c in got))

    def test_bpm_floor_excludes_a_distant_tempo(self):
        got = candidates(LIB, Slot(duration_s=300, bpm=160.0, key="Am"))
        self.assertNotIn("y", [c.track.id for c in got])

    def test_key_floor_excludes_a_clashing_key(self):
        got = candidates(LIB, Slot(duration_s=300, bpm=160.0, key="Am", max_key_distance=1))
        self.assertNotIn("z", [c.track.id for c in got])

    def test_length_floor_excludes_a_track_that_cannot_fit(self):
        got = candidates(LIB, Slot(duration_s=300, bpm=160.0, key="Am"))
        self.assertNotIn("w", [c.track.id for c in got])

    def test_excluded_ids_are_skipped(self):
        got = candidates(LIB, Slot(duration_s=300, bpm=160.0, key="Am"), exclude={"x"})
        self.assertNotIn("x", [c.track.id for c in got])

    def test_every_candidate_carries_a_reason_and_a_slot_length(self):
        got = candidates(LIB, Slot(duration_s=300, bpm=160.0, key="Am"))
        self.assertTrue(got)
        self.assertTrue(all(c.reason and c.play_s > 0 for c in got))


class ToolTests(unittest.TestCase):
    def test_dispatch_table_and_schema_agree(self):
        self.assertEqual(sorted(TOOL_DISPATCH), sorted(t["name"] for t in TOOL_SCHEMA))

    def test_summary_uses_engine_numbers(self):
        s = tools(draft(*"abcdef", target=1500)).get_set_summary()
        self.assertEqual(s["total"], "30:00")
        self.assertEqual(s["delta"], "5:00")
        self.assertFalse(s["within_target"])

    def test_simulate_does_not_touch_the_draft(self):
        d = draft(*"abcdef")
        t = tools(d)
        out = t.simulate([{"op": "remove", "track_ref": "a"}])
        self.assertEqual(out["total_after"], "25:00")
        self.assertEqual(len(d.tracks), 6)

    def test_propose_changes_never_applies(self):
        d = draft(*"abcdef")
        t = tools(d)
        out = t.propose_changes("test", [{"op": "remove", "track_ref": "a"}])
        self.assertTrue(out["accepted"])
        self.assertEqual(len(d.tracks), 6)

    def test_locked_proposal_is_refused_with_a_reason(self):
        d = draft(*"abcdef")
        SetLock("a", "position", True).execute(d)
        out = tools(d).propose_changes("test", [{"op": "remove", "track_ref": "a"}])
        self.assertFalse(out["accepted"])
        self.assertIn("ロック", out["reason"])

    def test_unknown_tool_returns_an_error_not_an_exception(self):
        self.assertIn("error", tools(draft("a")).call("set.do_whatever"))

    def test_play_history_admits_it_is_unavailable(self):
        self.assertFalse(tools(draft("a")).get_play_history()["available"])


class AdvisorTests(unittest.TestCase):
    def test_off_says_nothing(self):
        a = Advisor(tools(draft(*"abcdef")), level=Intervention.OFF)
        self.assertIsNone(a.ask("バランスどう？").change_set)
        self.assertEqual(a.notices(), [])

    def test_length_question_is_answered_from_the_engine(self):
        a = Advisor(tools(draft(*"abcdef", target=1500)))
        self.assertIn("30:00", a.ask("今のセット何分？").text)

    def test_balance_question_reports_problems(self):
        a = Advisor(tools(draft(*"abcdef", target=1500)))
        self.assertIn("・", a.ask("バランスどう？").text)

    def test_fit_request_produces_a_change_set_when_it_can(self):
        a = Advisor(tools(draft(*"abcdef", target=1500)))
        r = a.ask("20:00に収めて")          # no phrase data -> it must say so, not invent
        self.assertIsNone(r.change_set)
        self.assertIn("フレーズ解析が無い", r.text)
        self.assertIn("曲を外す", r.text)
        self.assertIn("3 曲分", r.text)      # arithmetic, not a shrug

    def test_already_within_target_is_said_plainly(self):
        a = Advisor(tools(draft(*"abc", target=900)))
        self.assertIn("収まっている", a.ask("15:00に収めて").text)

    def test_unparsed_request_admits_it(self):
        a = Advisor(tools(draft(*"abc")))
        self.assertIn("解釈できない", a.ask("ヴァイブスを上げてくれ").text)

    def test_fill_returns_real_tracks_only(self):
        a = Advisor(tools(draft(*"abcdef")))
        r = a.ask("何か足したい")
        self.assertTrue(all(c["track_id"] in LIB.m for c in r.candidates))

    def test_insert_candidate_is_a_proposal_not_an_edit(self):
        d = draft(*"abcdef")
        a = Advisor(tools(d))
        r = a.insert_candidate("x", 2)
        self.assertIsNotNone(r.change_set)
        self.assertEqual(len(d.tracks), 6)

    def test_a_rejected_proposal_is_not_shown_again(self):
        d = draft(*"abcdef")
        a = Advisor(tools(d))
        first = a.insert_candidate("x", 2)
        a.log.record_outcome(first.change_set)
        again = a.insert_candidate("x", 2)
        self.assertIsNone(again.change_set)

    def test_proactive_raises_at_most_one_notice(self):
        a = Advisor(tools(draft(*"abcdef", target=600)), level=Intervention.PROACTIVE)
        self.assertLessEqual(len(a.notices()), 1)

    def test_passive_never_raises_a_notice(self):
        a = Advisor(tools(draft(*"abcdef", target=600)), level=Intervention.PASSIVE)
        self.assertEqual(a.notices(), [])




class LLMFallbackTests(unittest.TestCase):
    def setUp(self):
        import os
        self.saved = {k: os.environ.pop(k, None) for k in ("SETAGENT_LLM_KEY", "ANTHROPIC_API_KEY")}

    def tearDown(self):
        import os
        for k, v in self.saved.items():
            if v is not None: os.environ[k] = v

    def test_no_key_means_unavailable_and_everything_still_works(self):
        from setagent.agent.llm import LLMAgent, LLMConfig
        t = tools(draft(*"abcdef", target=1500))
        a = LLMAgent(t, Advisor(t), cfg=LLMConfig.from_env())
        self.assertFalse(a.available)
        self.assertIn("未設定", a.status())
        self.assertIn("30:00", a.ask("今のセット何分？").text)

    def test_off_silences_the_llm_path_too(self):
        from setagent.agent.llm import LLMAgent, LLMConfig
        t = tools(draft(*"abc"))
        a = LLMAgent(t, Advisor(t, level=Intervention.OFF), cfg=LLMConfig(api_key="x"))
        self.assertIn("オフ", a.ask("バランスどう？").text)

    def test_unreachable_endpoint_falls_back_with_a_note(self):
        from setagent.agent.llm import LLMAgent, LLMConfig
        t = tools(draft(*"abcdef", target=1500))
        cfg = LLMConfig(api_key="x", endpoint="http://127.0.0.1:9/none", timeout_s=1)
        r = LLMAgent(t, Advisor(t), cfg=cfg).ask("今のセット何分？")
        self.assertIn("ルールベース", r.text)
        self.assertIn("30:00", r.text)

    def test_system_prompt_states_the_hard_rules(self):
        from setagent.agent.llm import SYSTEM_PROMPT
        for phrase in ("数値はツールから取る", "実在曲だけ", "自分で適用はできない"):
            self.assertIn(phrase, SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
