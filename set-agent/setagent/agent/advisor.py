"""The agent that works with no LLM at all (spec B-7 acceptance, S4-1/S4-2/S4-6).

An LLM is a nice front end. It is not the product. Every answer and every proposal
below is produced from the analysis engines by rules you can read, so the tool is
useful on a laptop with no network, no key and no account — and so the LLM path
has something correct to imitate.

`Advisor.ask()` returns a Reply: prose for the panel, optionally a ChangeSet for
the user to approve, optionally a list of real candidate tracks.

Voice (2026-09-16): plain, polite assistant Japanese (です・ます). The DJ decides;
the agent reports numbers and offers options. No orders, no bravado.
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
BUILD_WORDS = ("埋めて", "生成", "組んで", "組み立て", "作って", "build", "generate")
FULL_WORDS = ("フル", "full", "丸ごと")

OFF_TEXT = "エージェントはオフになっています。分析とタイムラインはそのまま使えます。"


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
            return Reply(OFF_TEXT)
        t = text.strip()
        low = t.lower()

        def has(words):
            return any(w in t or w in low for w in words)

        if has(FIT_WORDS):
            return self.fit_to_target(_mmss(t))
        if has(FULL_WORDS) and selected_index is not None:
            return self.play_full(selected_index)
        if has(BUILD_WORDS):
            return self.build_from_milestones()
        if has(FILL_WORDS):
            return self.fill_gap(t, selected_index)
        if has(BALANCE_WORDS):
            return self.critique()
        if has(SECTION_WORDS):
            return self.section_report()
        if has(PEAK_WORDS) or has(TIME_WORDS):
            return self.set_report()
        return Reply(
            "その言い方はまだ解釈できません。できることは、"
            "尺とピークを答える／区間の余白を出す／バランスを見る／"
            "目標尺に収める案を出す／区間に合う曲を探す、です。"
            "曲を選んだ状態で「フルでかけたい」も受け付けます。")

    # -------------------------------------------------------------- answers
    def set_report(self) -> Reply:
        s = self.tools.get_set_summary()
        line = f"今のセットは {s['total']} です"
        if s["target"]:
            line += f"。目標 {s['target']} に対して {s['delta']}"
        if s["peak_at"]:
            line += f"。ピークは {s['peak_at']} 付近です"
        cov = s["phrase_coverage"]
        return Reply(line + f"\n（フレーズ解析の範囲: {cov}）", used_tools=["analysis.get_set_summary"])

    def section_report(self) -> Reply:
        d = self.tools.get_sections()
        if not d["sections"]:
            return Reply("区間がまだありません。曲を選んで M キーでマイルストーンにすると骨組みができます。",
                         used_tools=["analysis.get_sections"])
        lines = []
        for s in d["sections"]:
            row = f"[{s['index']}] {s['from']} → {s['to']}  {s['tracks']}曲 {s['actual']}"
            if s["target"]:
                row += f" / 目標 {s['target']}（{s['delta']}）"
            if s["room_for_tracks"]:
                r = s["room_for_tracks"]
                row += f"  → {'あと' + str(r) + '曲入ります' if r > 0 else str(-r) + '曲分オーバーです'}"
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
            lines.append(f"尺が目標から {s['delta']} ずれています")
        for f in e["flat"][:2]:
            lines.append(f"{f['from']}〜{f['to']} が平坦です（振れ幅 {f['range']}）。"
                         "展開が止まって聞こえやすい区間です")
        if e["has_target_curve"]:
            over = [d for d in e["deviation"] if d["kind"] == "over"][:1]
            under = [d for d in e["deviation"] if d["kind"] == "under"][:1]
            for d in over + under:
                lines.append(f"{d['from']}〜{d['to']} は目標より"
                             f"{'高め' if d['kind'] == 'over' else '低め'}です")
        else:
            lines.append("目標カーブがまだありません。テンプレートを当てると、意図とのズレを出せます")
        if s["peak_at"]:
            lines.append(f"ピークは {s['peak_at']} です。狙いどおりの位置かご確認ください")
        if not lines:
            lines.append("大きな問題は見当たりません")
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
            return Reply(f"この案は出せません。{ex}")
        if self.log.already_seen(cs):
            return Reply("同じ案は一度却下されています。別の案を出すには条件を追加してください。")
        self.log.record_proposal(cs)
        self._last = cs
        body = "\n".join(f"・{i.op.describe(self.tools.title_of)}" for i in cs.items)
        diff = "\n".join(f"  {l}" for l in cs.diff_lines)
        return Reply(f"{reason}\n{body}\n{diff}", change_set=cs,
                     used_tools=["set.propose_changes"])

    def fit_to_target(self, target_s: int | None = None) -> Reply:
        """S4-2 + S1-6: cut just enough to land inside the target.

        The plan itself lives in agent/fitplan.py (shared with the LLM's
        analysis.plan_fit_to_target tool); this only puts words around it.
        """
        from setagent.agent.fitplan import plan_fit
        plan = plan_fit(self.tools, target_s)
        if plan.target_s is None:
            return Reply("目標尺が設定されていません。上の Target に mm:ss で入力してください。")
        if plan.already_fits:
            return Reply(f"すでに収まっています（{fmt(plan.total_s)} / 目標 {fmt(plan.target_s)}）。")
        over, ops, saved = plan.over_s, plan.range_ops, plan.range_saves_s

        if ops and saved >= over:
            return self._propose(f"目標の {fmt(plan.target_s)} を {fmt(over)} 超えています。"
                                 f"{len(ops)}曲を one_drop に詰めると収まります。", ops, "目標尺に収める")

        # ranges alone cannot get there: whole tracks to drop
        remaining = over - saved
        why = ""
        if plan.no_phrase_tracks:
            why = (f"{plan.track_count}曲中 {plan.no_phrase_tracks}曲にフレーズ解析がない"
                   "（クラウド保存の曲は rekordbox が解析しません）ため、範囲の自動短縮には限りがあります。")
        head = f"目標を {fmt(over)} 超えています。"
        if ops:
            head += f"one_drop で詰められるのは {fmt(saved)} までで、残り {fmt(remaining)} は範囲では消せません。"
        else:
            head += "範囲の短縮だけでは届きません。"
        head += why

        picked = plan.removals
        tl = compute(self.tools.draft, self.tools.lib)
        if picked:
            shown = picked[:8]
            lines = [f"・{c.title[:28]}（{fmt(c.saves_s)}）: " + "／".join(c.reasons) for c in shown]
            if len(picked) > len(shown):
                lines.append(f"・ほか {len(picked) - len(shown)} 曲（下の一覧に含まれています）")
            reason = (head + f"\n曲を外す候補として、展開と繋ぎへの影響が小さい順に {len(picked)} 曲を選びました。"
                      "\n" + "\n".join(lines))
            reply = self._propose(reason, ops + [{"op": "remove", "track_ref": c.track_id} for c in picked],
                                  "目標尺に収める（範囲と曲の削除）")
            if reply.change_set is not None:
                reply.text += "\n外す曲は候補です。チェックを外して適用すれば、その曲は残ります。"
            return reply

        avg = tl.total_s / max(len(tl.placements), 1)
        need = int(remaining // avg) + 1
        tail = (f"\n残りを消すには曲を外す必要があります。1曲平均 {fmt(avg)} なので、およそ {need} 曲分です。"
                "ロックとマイルストーンを除くと外せる曲が足りないため、候補は出せません。"
                "ロックを見直すか、目標尺のほうを調整してください。")
        if ops:
            reply = self._propose(head + "まず詰められる分だけ出します。", ops, "できる範囲で詰める")
            reply.text += tail
            return reply
        return Reply(head + tail)

    def build_from_milestones(self) -> Reply:
        """マイルストーン起点のプレイリスト生成: fill the room between the DJ's
        anchor tracks with real tracks (agent/fillplan.py), as one proposal."""
        from setagent.agent.fillplan import plan_fill
        plan = plan_fill(self.tools)
        if not plan.picks:
            return Reply(plan.note or "埋める余地がありません。", used_tools=["analysis.plan_fill_sections"])
        lines = []
        for s in plan.sections:
            if not s.picks:
                continue
            lines.append(f"[{s.index}] {s.start_title[:16]} → {(s.end_title or 'END')[:16]}: "
                         f"{len(s.picks)}曲 {fmt(s.filled_s)}（余地 {fmt(s.room_s)}）")
            for p in s.picks[:6]:
                lines.append(f"　・{p.title[:28]} — {p.reason}")
            if len(s.picks) > 6:
                lines.append(f"　・ほか {len(s.picks) - 6} 曲")
            if s.note:
                lines.append(f"　{s.note}")
        reason = (f"マイルストーンの間を {len(plan.picks)} 曲で埋めます（{fmt(plan.total_before_s)} → "
                  f"{fmt(plan.total_after_s)}）。候補はすべてライブラリの実在曲で、直前の曲の BPM・キーに繋がる順です。\n"
                  + "\n".join(lines))
        reply = self._propose(reason, plan.operations, "マイルストーンの間を埋める")
        reply.used_tools = ["analysis.plan_fill_sections", "set.propose_changes"]
        return reply

    def play_full(self, index: int) -> Reply:
        """'this one full' — and then what it costs (the E-5 dialogue)."""
        e = self.tools.draft.tracks[index]
        title = self.tools.title_of(e.track_id)
        ops = [{"op": "set_range", "track_ref": e.track_id, "preset": "full",
                "play_in": 0, "play_out": None}]
        sim = self.tools.simulate(ops)
        reply = self._propose(f"{title[:28]} をフル尺にします。総尺は {sim['total_after']} になります。",
                              ops, "フルでかける")
        if sim.get("within_target") is False:
            reply.text += "\n目標を超えます。「60:00 に収めて」のように指示すると、削り代の案を出します。"
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
            return Reply("条件に合う曲がライブラリにありません。BPM の幅かキーの条件を緩めてみてください。",
                         used_tools=["recommend.candidates"])
        head = (f"{fmt(want)} の枠に入る候補です（{after + 1} 曲目の次）。"
                "いずれもライブラリにある曲です:")
        body = "\n".join(f"{i + 1}. {c['title'][:34]} — {c['reason']}"
                         for i, c in enumerate(cands))
        return Reply(f"{head}\n{body}\n候補をダブルクリックすると挿入案になります。",
                     candidates=cands, used_tools=["recommend.candidates"])

    def insert_candidate(self, track_id: str, at_index: int) -> Reply:
        title = self.tools.title_of(track_id)
        return self._propose(f"{title[:28]} を {at_index + 1} 番目に入れます。",
                             [{"op": "insert", "track_id": track_id, "at_index": at_index}],
                             "候補を挿入")

    # -------------------------------------------------------------- notices
    def notices(self) -> list[str]:
        """S4-7: at most one, only in `proactive`, only from analysis warnings."""
        if self.level is not Intervention.PROACTIVE:
            return []
        tl = compute(self.tools.draft, self.tools.lib)
        if tl.within_target is False:
            return [f"尺が目標から {fmt(tl.delta_s)} ずれています。「収めて」と指示すると案を出します。"]
        flats = flat_segments(self.tools._points(tl))
        if flats:
            f = flats[0]
            return [f"{fmt(f.start_s)}〜{fmt(f.end_s)} が平坦です。「何か足したい」で候補を出します。"]
        for m in milestones(self.tools.draft, tl):
            if m.delta_s is not None and abs(m.delta_s) > tl.tolerance_s:
                return [f"{m.title[:20]} が目標時刻から {fmt(abs(m.delta_s))} ずれています。"]
        return []
