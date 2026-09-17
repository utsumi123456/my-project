"""The deterministic plan for landing a set inside its target length.

Shared by the rule-based Advisor (which turns it into a proposal directly) and
the LLM (which reads it through `analysis.plan_fit_to_target` and then decides
what to propose). One engine, so the two paths cannot disagree about how much a
range cut saves or which tracks are safe to drop (spec §7: numbers come from
analysis.*, never from the model).

Ranges first (cheap, reversible), then whole tracks from analysis.removal for
what ranges cannot reach. Honest about the part neither can cover.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from setagent.analysis.phrases import preset_range
from setagent.analysis.removal import RemovalCandidate, pick_removals, removal_candidates
from setagent.analysis.timing import compute, fmt
from setagent.rekordbox.library import PhraseStatus


@dataclass
class FitPlan:
    target_s: float | None
    total_s: float
    over_s: float                     # <= 0 means already inside
    tolerance_s: float
    already_fits: bool
    range_ops: list[dict] = field(default_factory=list)
    range_saves_s: float = 0.0
    removals: list[RemovalCandidate] = field(default_factory=list)
    removal_saves_s: float = 0.0
    no_phrase_tracks: int = 0
    track_count: int = 0

    @property
    def operations(self) -> list[dict]:
        return self.range_ops + [{"op": "remove", "track_ref": c.track_id} for c in self.removals]

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.over_s - self.range_saves_s - self.removal_saves_s)

    @property
    def reaches_target(self) -> bool:
        return self.already_fits or self.remaining_s <= 0.0

    def to_json(self, max_removals: int = 60) -> dict:
        """What the LLM sees. Every number here is an engine number."""
        shown = self.removals[:max_removals]
        return {
            "target": fmt(self.target_s) if self.target_s else None,
            "total": fmt(self.total_s),
            "over": fmt(self.over_s) if self.over_s > 0 else "0:00",
            "already_fits": self.already_fits,
            "reaches_target": self.reaches_target,
            "range_cuts": {"count": len(self.range_ops), "saves": fmt(self.range_saves_s),
                           "note": "one_drop に詰める曲。可逆で、曲は残る"},
            "removals": {"count": len(self.removals), "saves": fmt(self.removal_saves_s),
                         "tracks": [{"index": c.index, "track_id": c.track_id, "title": c.title,
                                     "saves": fmt(c.saves_s), "reasons": list(c.reasons)} for c in shown],
                         "note": "展開と繋ぎへの影響が小さい順。ロックとマイルストーンは含まない"},
            "remaining_after_plan": fmt(self.remaining_s),
            "no_phrase_tracks": self.no_phrase_tracks,
            "operations": self.operations,
            "how_to_use": ("この operations をそのまま set.propose_changes に渡すと目標に収まります。"
                           "曲を残したいときは、その remove を外して残りを渡してください（届かない分は正直に言う）"),
        }


def plan_fit(tools, target_s: float | None = None) -> FitPlan:
    d = tools.draft
    if target_s:
        d.constraints.target_length_s = target_s
    tl = compute(d, tools.lib)
    plan = FitPlan(target_s=tl.target_s, total_s=tl.total_s, over_s=0.0,
                   tolerance_s=tl.tolerance_s, already_fits=True, track_count=len(d.tracks))
    if tl.target_s is None:
        plan.already_fits = False
        return plan
    over = tl.total_s - tl.target_s
    plan.over_s = over
    plan.already_fits = over <= tl.tolerance_s
    if plan.already_fits:
        return plan

    saved = 0.0
    for c in tools.get_trim_candidates(limit=60):
        if c["action"] != "range->one_drop":
            continue
        ta = tools.lib.analysis(c["track_id"])
        r = preset_range(ta.anlz, "one_drop", tools.cfg) if ta.anlz else None
        if not r:
            continue
        plan.range_ops.append({"op": "set_range", "track_ref": c["track_id"], "preset": "one_drop",
                               "play_in": r.play_in_ms, "play_out": r.play_out_ms})
        mm, ss = c["saves"].lstrip("-").split(":")
        saved += int(mm) * 60 + int(ss)
        if saved >= over:
            break
    plan.range_saves_s = saved
    if saved >= over:
        return plan

    plan.no_phrase_tracks = sum(
        1 for e in d.tracks
        if tools.lib.analysis(e.track_id).phrase_status is not PhraseStatus.PRESENT)
    remaining = over - saved
    cands = removal_candidates(d, tools.lib, tools.anlz, tools.curve, tl)
    plan.removals = pick_removals(cands, remaining)
    plan.removal_saves_s = sum(c.saves_s for c in plan.removals)
    return plan


def scored_removals(tools, limit: int = 30) -> list[dict]:
    """analysis.removal_candidates — every removable track, easiest first."""
    tl = compute(tools.draft, tools.lib)
    cands = removal_candidates(tools.draft, tools.lib, tools.anlz, tools.curve, tl)
    cands = sorted(cands, key=lambda c: -c.score)[:limit]
    return [{"index": c.index, "track_id": c.track_id, "title": c.title, "saves": fmt(c.saves_s),
             "score": round(c.score, 2), "reasons": list(c.reasons)} for c in cands]
