"""Milestone-driven playlist building (HANDOFF item: マイルストーン起点のプレイリスト生成).

The DJ marks the tracks that matter (milestones) and their rough order; this
fills the room between them with real tracks from the library, chained by BPM
and key from the track before each gap and steered toward the target curve.
Shared by the Advisor (which proposes it directly) and the LLM (through the
analysis.plan_fill_sections tool). Every number is an engine number.

Budget per section: an explicit milestone target time wins; sections without
one share whatever the set's target length still leaves. A pick never pushes a
milestone past its target (changeset._check_milestones would refuse it anyway),
so the plan stops a section when the next candidate would not fit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from setagent.agent.recommend import Slot, candidates
from setagent.analysis.sections import sections
from setagent.analysis.timing import compute, fmt, simulate
from setagent.domain.draft import Insert


@dataclass
class Pick:
    track_id: str
    title: str
    artist: str
    bpm: float
    key: str
    play_s: float
    reason: str
    at_index: int                      # index in the draft as it stands when this insert applies


@dataclass
class SectionFill:
    index: int
    start_title: str
    end_title: str | None
    actual_s: float
    target_s: float | None
    room_s: float
    picks: list[Pick] = field(default_factory=list)
    note: str = ""

    @property
    def filled_s(self) -> float:
        return sum(p.play_s for p in self.picks)

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.room_s - self.filled_s)


@dataclass
class FillPlan:
    target_s: float | None
    total_before_s: float
    total_after_s: float
    sections: list[SectionFill]
    note: str = ""

    @property
    def operations(self) -> list[dict]:
        ops = []
        for s in self.sections:
            for p in s.picks:
                ops.append({"op": "insert", "track_id": p.track_id, "at_index": p.at_index})
        return ops

    @property
    def picks(self) -> list[Pick]:
        return [p for s in self.sections for p in s.picks]

    def to_json(self) -> dict:
        return {
            "target": fmt(self.target_s) if self.target_s else None,
            "total_before": fmt(self.total_before_s),
            "total_after": fmt(self.total_after_s),
            "added_tracks": len(self.picks),
            "sections": [{
                "index": s.index, "from": s.start_title, "to": s.end_title or "END",
                "actual": fmt(s.actual_s), "target": fmt(s.target_s) if s.target_s is not None else None,
                "room": fmt(s.room_s), "filled": fmt(s.filled_s), "remaining": fmt(s.remaining_s),
                "picks": [{"track_id": p.track_id, "title": p.title, "artist": p.artist, "bpm": p.bpm,
                           "key": p.key, "play": fmt(p.play_s), "reason": p.reason, "at_index": p.at_index}
                          for p in s.picks],
                "note": s.note,
            } for s in self.sections],
            "unfilled": fmt(sum(s.remaining_s for s in self.sections)),
            "operations": self.operations,
            "note": self.note,
            "how_to_use": ("operations をそのまま set.propose_changes に渡すと、マイルストーンの間が"
                           "候補曲で埋まった案になります。候補はすべてライブラリの実在曲です"),
        }


def plan_fill(tools, section: int | None = None, per_section_limit: int = 20,
              pool: list[str] | None = None) -> FillPlan:
    d, lib = tools.draft, tools.lib
    tl = compute(d, lib)
    secs = sections(d, tl)
    target_total = d.constraints.target_length_s
    tol = tl.tolerance_s
    plan = FillPlan(target_s=target_total, total_before_s=tl.total_s, total_after_s=tl.total_s, sections=[])
    if not tl.placements:
        plan.note = "セットに曲がありません"
        return plan

    # --- budget: explicit milestone targets first, the rest share the leftover
    explicit = {s.index: (s.target_s - s.actual_s) for s in secs if s.target_s is not None}
    open_secs = [s for s in secs if s.target_s is None]
    leftover = None
    if target_total is not None:
        leftover = (target_total - tl.total_s) - sum(max(v, 0.0) for v in explicit.values())
    share = (max(leftover, 0.0) / len(open_secs)) if (open_secs and leftover is not None) else 0.0
    if target_total is None and not explicit:
        plan.note = "目標尺もマイルストーンの目標時刻もないため、埋める量を決められません。Target Time を入れてください"
        for s in secs:
            plan.sections.append(SectionFill(s.index, s.start_title, s.end_title, s.actual_s, None, 0.0))
        return plan

    used = {e.track_id for e in d.tracks}
    total_for_curve = float(target_total or tl.total_s)
    cmds: list[Insert] = []
    shift = 0                                  # inserts so far push later indices down
    for s in secs:
        room = explicit.get(s.index, share)
        sf = SectionFill(s.index, s.start_title, s.end_title, s.actual_s, s.target_s, max(room, 0.0))
        plan.sections.append(sf)
        if section is not None and s.index != section:
            sf.note = "指定外の区間"
            continue
        if room <= 0:
            sf.note = "余地なし" if room > -tol else f"予算を {fmt(-room)} 超えています（埋める側ではなく削る側）"
            continue
        prev = tl.placements[s.last_track]
        prev_bpm = prev.set_tempo
        prev_key = lib.track(prev.track_id).key
        at = s.last_track + 1 + shift
        remaining = room
        while len(sf.picks) < per_section_limit and remaining > tol:
            t_here = s.end_s + sf.filled_s
            energy = tools.curve.at_time(t_here, total_for_curve) if tools.curve else None
            cands = candidates(lib, Slot(duration_s=remaining, target_energy=energy,
                                         bpm=prev_bpm, key=prev_key or ""),
                               pool=pool, exclude=used, limit=8)
            fit = next((c for c in cands if c.play_s <= remaining + tol), None)
            if fit is None:
                sf.note = (f"残り {fmt(remaining)} に入る曲がライブラリにありません"
                           if cands or remaining < 60 else
                           f"{prev_bpm:.0f} BPM 前後で {prev_key or 'キー不明'} に繋がる曲が見つかりません")
                break
            pick = Pick(fit.track.id, fit.track.title, fit.track.artist, fit.track.bpm, fit.track.key,
                        fit.play_s, fit.reason, at)
            sf.picks.append(pick)
            cmds.append(Insert(pick.track_id, at))
            used.add(pick.track_id)
            remaining -= fit.play_s
            prev_key = fit.track.key or prev_key
            at += 1
            shift += 1
    if cmds:
        plan.total_after_s = simulate(d, lib, cmds).total_s
    if not plan.picks and not plan.note:
        plan.note = "どの区間にも埋める余地がありません"
    return plan
