"""The agent that works with no LLM at all (spec B-7 acceptance, S4-1/S4-2/S4-6).

An LLM is a nice front end. It is not the product. Every answer and every proposal
below is produced from the analysis engines by rules you can read, so the tool is
useful on a laptop with no network, no key and no account — and so the LLM path
has something correct to imitate.

`Advisor.ask()` returns a Reply: prose for the panel, optionally a ChangeSet for
the user to approve, optionally a list of real candidate tracks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from setagent.agent.changeset import ChangeSet, ProposalLog, Proposal, Rejected, build_change_set
from setagent.agent.tools import AgentTools
from setagent.analysis.curve import flat_segments
from setagent.analysis.sections import milestones, sections
from setagent.analysis.timing import compute, fmt
from setagent.rekordbox.library import PhraseStatus


class Intervention(str, Enum):
    """B-10 / S4-7. `off` means silent: no proposals, no notices, nothing."""
    OFF = "off"
    PASSIVE = "passive"          # answers when asked; proposes only when asked
    PROACTIVE = "proactive"      # may raise at most one notice per turn


@dataclass
class Reply:
    text: str
    change_set: ChangeSet | None = None
    candidates: list[dict] = field(default_factory=list)
    used_tools: list[str] = field(default_factory=list)


TIME_WORDS = ("何分", "尺", "長さ", "総尺", "length", "how long", "total")
PEAK_WORDS = ("ピーク", "山", "peak", "climax")
SECTION_WORDS = ("区間", "骨組み", "セクション", "section", "milestone", "マイルストーン")
BALANCE_WORDS = ("バランス", "どう", "どうか", "評価", "balance", "review", "flow")
FIT_WORDS = ("収めて", "収める", "縮めて", "短く", "削って", "fit", "trim", "shorten")
FILL_WORDS = ("足したい", "埋めたい", "追加", "候補", "add", "fill", "suggest", "recommend")
FULL_WORDS = ("フル", "full", "丸ごと")


def _mmss(text: str) -> int | None:
    m = re.search(r"(\d{1,3}):(\d{2})", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"(\d{1,3})\s*分", text)
    return int(m.group(1)) * 60 if m else None


@dataclass
class Advisor:
    tools: AgentTools
    log: ProposalLog = field(default_factory=ProposalLog)
    level: Intervention = Intervention.PASSIVE
    _last: ChangeSet | None = None

    # ------------------------------------------------------------------ api
    def ask(self, text: str, selected_index: int | None = None) -> Reply:
        if self.level is Intervention.OFF:
            return Reply("エージェントはオフだ。分析とタイムラインはそのまま使える")
        t = text.strip()
        low = t.lower()

        def has(words):
            return any(w in t or w in low for w in words)

        if has(FIT_WORDS):
            return self.fit_to_target(_mmss(t))
        if has(FULL_WORDS) and selected_index is not None:
            return self.play_full(selected_index)
        if has(FILL_WORDS):
            return self.fill_gap(t, selected_index)
        if has(BALANCE_WORDS):
            return self.critique()
        if has(SECTION_WORDS):
            return self.section_report()
        if has(PEAK_WORDS) or has(TIME_WORDS):
            return self.set_report()
        return Reply(
            "その言い方はまだ解釈できない。私にできるのは、"
            "尺とピークを答える／区間の余白を出す／バランスを見る／"
            "目標尺に収める案を出す／区間に合う曲を探す、あたりだ。"
            "選んだ曲について「フルでかけたい」も通る")

    # -------------------------------------------------------------- answers
    def set_report(self) -> Reply:
        s = self.tools.get_set_summary()
        line = f"今のセットは {s['total']}"
        if s["target"]:
            line += f"、目標 {s['target']} に対して {s['delta']}"
        if s["peak_at"]:
            line += f"。ピークは {s['peak_at']} 付近だ"
        cov = s["phrase_coverage"]
        return Reply(line + f"\n（フレーズ解析の範囲: {cov}）", used_tools=["analysis.get_set_summary"])

    def section_report(self) -> Reply:
        d = self.tools.get_sections()
        if not d["sections"]:
            return Reply("区間が無い。曲を選んで M キーでマイルストーンにすれば骨組みができる",
                         used_tools=["analysis.get_sections"])
        lines = []
        for s in d["sections"]:
            row = f"[{s['index']}] {s['from']} → {s['to']}  {s['tracks']}曲 {s['actual']}"
            if s["target"]:
                row += f" / 目標 {s['target']}（{s['delta']}）"
            if s["room_for_tracks"]:
                r = s["room_for_tracks"]
                row += f"  → {'あと' + str(r) + '曲入る' if r > 0 else str(-r) + '曲分オーバー'}"
            lines.append(row)
        for m in d["milestones"]:
            if m["delta"]:
                lines.append(f"* {m['title'][:24]} は {m['at']}（目標 {m['target']} / {m['delta']}）")
        return Reply("\n".join(lines), used_tools=["analysis.get_sections"])

    def critique(self) -> Reply:
        """The honest read. Says what is wrong before it says what is fine."""
        s = self.tools.get_set_summary()
        e = self.tools.get_energy_curve()
        lines: list[str] = []
        if s["target"] and s["within_target"] is False:
            lines.append(f"尺が目標から {s['delta']} ずれている")
        for f in e["flat"][:2]:
            lines.append(f"{f['from']}〜{f['to']} が平坦だ（振れ幅 {f['range']}）。"
                         "そつなく終わるのはここだ")
        if e["has_target_curve"]:
            over = [d for d in e["deviation"] if d["kind"] == "over"][:1]
            under = [d for d in e["deviation"] if d["kind"] == "under"][:1]
            for d in over + under:
                lines.append(f"{d['from']}〜{d['to']} は目標より"
                             f"{'高い' if d['kind'] == 'over' else '低い'}")
        else:
            lines.append("目標カーブがまだ無い。テンプレートを当てれば、意図とのズレを出せる")
        if s["peak_at"]:
            lines.append(f"ピークは {s['peak_at']}。狙いどおりか、ここだけは自分で決めろ")
        if not lines:
            lines.append("大きな破綻は見当たらない")
        return Reply("\n".join(f"・{l}" for l in lines),
                     used_tools=["analysis.get_set_summary", "analysis.get_energy_curve"])

    # ------------------------------------------------------------ proposals
    def _propose(self, reason: str, ops: list[dict], title: str = "") -> Reply:
        try:
            cs = build_change_set(self.tools.draft, self.tools.lib, self.tools.anlz,
                                  Proposal.from_dict({"reason": reason, "operations": ops,
                                                      "title": title}),
                                  self.tools.curve)
        except Rejected as ex:
            self.log.record_drop()
            return Reply(f"その案は出せない。{ex}")
        if self.log.already_seen(cs):
            return Reply("同じ案は一度却下されている。別の手を考えるなら条件を足せ")
        self.log.record_proposal(cs)
        self._last = cs
        body = "\n".join(f"・{i.op.describe(self.tools.title_of)}" for i in cs.items)
        diff = "\n".join(f"  {l}" for l in cs.diff_lines)
        return Reply(f"{reason}\n{body}\n{diff}", change_set=cs,
                     used_tools=["set.propose_changes"])

    def fit_to_target(self, target_s: int | None = None) -> Reply:
        """S4-2 + S1-6: cut just enough to land inside the target, and be honest
        about the part that presets cannot reach."""
        d = self.tools.draft
        if target_s:
            d.constraints.target_length_s = target_s
        tl = compute(d, self.tools.lib)
        if tl.target_s is None:
            return Reply("目標尺が決まっていない。上の Target に mm:ss で入れろ")
        over = tl.total_s - tl.target_s
        if over <= tl.tolerance_s:
            return Reply(f"すでに収まっている（{fmt(tl.total_s)} / 目標 {fmt(tl.target_s)}）")

        from setagent.analysis.phrases import preset_range
        ops: list[dict] = []
        saved = 0.0
        for c in self.tools.get_trim_candidates(limit=60):
            if c["action"] != "range->one_drop":
                continue
            ta = self.tools.lib.analysis(c["track_id"])
            r = preset_range(ta.anlz, "one_drop", self.tools.cfg) if ta.anlz else None
            if not r:
                continue
            ops.append({"op": "set_range", "track_ref": c["track_id"], "preset": "one_drop",
                        "play_in": r.play_in_ms, "play_out": r.play_out_ms})
            mm, ss = c["saves"].lstrip("-").split(":")
            saved += int(mm) * 60 + int(ss)
            if saved >= over:
                break

        if ops and saved >= over:
            return self._propose(f"目標の {fmt(tl.target_s)} を {fmt(over)} 超えている。"
                                 f"{len(ops)}曲を one_drop に詰めれば収まる", ops, "目標尺に収める")

        # presets alone cannot get there — say by how much, and why
        remaining = over - saved
        avg = tl.total_s / max(len(tl.placements), 1)
        need = int(remaining // avg) + 1
        no_phrase = sum(1 for e in d.tracks
                        if self.tools.lib.analysis(e.track_id).phrase_status is not PhraseStatus.PRESENT)
        why = ""
        if no_phrase:
            why = (f"\n{len(d.tracks)}曲中 {no_phrase}曲にフレーズ解析が無い"
                   "（クラウド保存の曲は rekordbox が解析しない）ので、範囲を自動で詰められない")
        head = f"目標を {fmt(over)} 超えている。"
        if ops:
            head += f"one_drop で詰められるのは {fmt(saved)} 分まで、残り {fmt(remaining)} は範囲では消せない"
        else:
            head += "範囲の短縮では届かない"
        tail = (f"{why}\n残りを消すなら曲を外すしかない。1曲平均 {fmt(avg)} なので、"
                f"およそ {need} 曲分だ。どれを外すかはお前が決めろ — "
                "外したい曲を選んで Delete、または目標尺のほうを見直せ")
        if ops:
            reply = self._propose(head + "。まず詰められる分だけ出す", ops, "できる範囲で詰める")
            reply.text += tail
            return reply
        return Reply(head + tail)

    def play_full(self, index: int) -> Reply:
        """'this one full' — and then what it costs (the E-5 dialogue)."""
        e = self.tools.draft.tracks[index]
        title = self.tools.title_of(e.track_id)
        ops = [{"op": "set_range", "track_ref": e.track_id, "preset": "full",
                "play_in": 0, "play_out": None}]
        sim = self.tools.simulate(ops)
        reply = self._propose(f"{title[:28]} をフル尺にする。総尺は {sim['total_after']} になる",
                              ops, "フルでかける")
        if sim.get("within_target") is False:
            reply.text += "\n目標を超える。「60:00に収めて」と言えば、削り代の案を出す"
        return reply

    def fill_gap(self, text: str, selected_index: int | None) -> Reply:
        """S4-6 / B-9: real tracks for a real hole, with a reason each."""
        want = _mmss(text)
        after = selected_index
        target_e = None
        tl = compute(self.tools.draft, self.tools.lib)
        if want is None:
            flats = flat_segments(self.tools._points(tl))
            if flats:
                f = flats[0]
                want = int(min(f.duration_s, 600))
                after = next((p.index for p in tl.placements if p.end_s >= f.start_s), None)
                target_e = 0.85
            else:
                want = 360
        if after is None:
            after = len(self.tools.draft.tracks) - 1
        cands = self.tools.recommend_candidates(fmt(want), target_energy=target_e,
                                                after_index=after, limit=5)
        if not cands:
            return Reply("条件に合う曲がライブラリに無い。BPM の幅かキーの条件を緩めろ",
                         used_tools=["recommend.candidates"])
        head = (f"{fmt(want)} の枠に入る候補だ（{after + 1} 曲目の次）。"
                "どれもお前のライブラリの実在曲だ:")
        body = "\n".join(f"{i + 1}. {c['title'][:34]} — {c['reason']}"
                         for i, c in enumerate(cands))
        return Reply(f"{head}\n{body}\n選んだらダブルクリックで挿入案にする",
                     candidates=cands, used_tools=["recommend.candidates"])

    def insert_candidate(self, track_id: str, at_index: int) -> Reply:
        title = self.tools.title_of(track_id)
        return self._propose(f"{title[:28]} を {at_index + 1} 番目に入れる",
                             [{"op": "insert", "track_id": track_id, "at_index": at_index}],
                             "候補を挿入")

    # -------------------------------------------------------------- notices
    def notices(self) -> list[str]:
        """S4-7: at most one, only in `proactive`, only from analysis warnings."""
        if self.level is not Intervention.PROACTIVE:
            return []
        tl = compute(self.tools.draft, self.tools.lib)
        if tl.within_target is False:
            return [f"尺が目標から {fmt(tl.delta_s)} ずれている。「収めて」と言えば案を出す"]
        flats = flat_segments(self.tools._points(tl))
        if flats:
            f = flats[0]
            return [f"{fmt(f.start_s)}〜{fmt(f.end_s)} が平坦だ。「何か足したい」で候補を出す"]
        for m in milestones(self.tools.draft, tl):
            if m.delta_s is not None and abs(m.delta_s) > tl.tolerance_s:
                return [f"{m.title[:20]} が目標時刻から {fmt(abs(m.delta_s))} ずれている"]
        return []
