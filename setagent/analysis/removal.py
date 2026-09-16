"""Which tracks to drop when the set is over length (spec B-2 / B-9, 2026-09-16).

`fit_to_target` first shortens play ranges; what presets cannot reach has to
come out as whole tracks, and until now the agent only said "you decide".
This ranks the DJ's own tracks by how little the set would miss them:

  up   : buried between neighbours of the same energy (removing it leaves the
         curve as it was), pulling the curve away from the DJ's target shape,
         and a clean seam afterwards (neighbours close in BPM and Camelot key)
  down : making a peak or a bottom, a seam that would jump in BPM or key
  out  : locked, milestone (spec B-1 / B-4 -- the guards would reject anyway)

Deterministic. Numbers, not opinions; the agent turns them into a ChangeSet.
"""
from __future__ import annotations

from dataclasses import dataclass

from setagent.analysis.curve import TargetCurve
from setagent.analysis.energy import track_energy_at
from setagent.analysis.timing import Timeline, compute
from setagent.domain.draft import SetDraft

PEAK_MARGIN = 0.15          # how much a track must stand above/below both neighbours
BURIED_MARGIN = 0.08        # ... or how close it must sit to them to count as buried
BPM_JUMP = 0.08             # seam tolerance, same as recommend.Slot
KEY_JUMP = 2                # Camelot steps we accept across the new seam


@dataclass(frozen=True)
class RemovalCandidate:
    index: int
    track_id: str
    title: str
    saves_s: float
    score: float                # higher = easier to remove
    reasons: tuple[str, ...]


def _track_energy(anlz) -> float | None:
    if not (anlz and anlz.structure and anlz.structure.phrases):
        return None
    vals = [track_energy_at(anlz, i / 7) for i in range(8)]
    return sum(vals) / len(vals)


def removal_candidates(draft: SetDraft, lib, anlz_by_id: dict, curve: TargetCurve | None,
                       timeline: Timeline | None = None) -> list[RemovalCandidate]:
    from setagent.agent.recommend import key_distance     # agent imports analysis; not the reverse
    tl = timeline or compute(draft, lib)
    n = len(tl.placements)
    energies = [_track_energy(anlz_by_id.get(p.track_id)) for p in tl.placements]
    out: list[RemovalCandidate] = []
    for i, p in enumerate(tl.placements):
        e = draft.tracks[i]
        if e.locks or e.is_milestone:
            continue
        score = 0.5
        reasons: list[str] = []
        prev = tl.placements[i - 1] if i > 0 else None
        nxt = tl.placements[i + 1] if i + 1 < n else None
        ei = energies[i]
        neigh = [energies[j] for j in (i - 1, i + 1) if 0 <= j < n and energies[j] is not None]

        if ei is None:
            reasons.append("フレーズ解析がなく展開への影響は不明")
        elif neigh:
            hi = all(ei >= x + PEAK_MARGIN for x in neigh)
            lo = all(ei <= x - PEAK_MARGIN for x in neigh)
            if hi or lo:
                score -= 0.4
                reasons.append("展開の山を作っている曲" if hi else "展開の谷を作っている曲")
            elif all(abs(ei - x) <= BURIED_MARGIN for x in neigh):
                score += 0.3
                reasons.append("前後と同じ高さに埋もれ、外しても展開は変わらない")
        if ei is not None and curve is not None and tl.total_s > 0:
            mid = (p.start_s + p.end_s) / 2 / tl.total_s
            dev = ei - curve.at(mid)
            if abs(dev) >= 0.2:
                score += 0.2
                reasons.append(f"目標カーブより {abs(dev):.1f} {'高い' if dev > 0 else '低い'}")

        if prev and nxt:
            tp, tn = lib.track(prev.track_id), lib.track(nxt.track_id)
            jump = abs(prev.set_tempo - nxt.set_tempo) / max(prev.set_tempo, 1)
            if jump > BPM_JUMP:
                score -= min(0.5, jump * 2.5)          # 8% costs 0.2, 20% costs 0.5
                reasons.append(f"外すと前後の BPM が {jump:.0%} 離れる")
            kd = key_distance(tp.key, tn.key)
            if kd is not None and kd > KEY_JUMP:
                score -= 0.2
                reasons.append(f"外すと前後のキーが {kd} 歩離れる")
            elif kd is not None and kd <= 1:
                score += 0.1
                reasons.append("前後のキーはそのまま繋がる")
        # what the set actually loses: the play time minus the overlap that goes with it
        saves = p.play_s - (max(0.0, p.end_s - nxt.start_s) if nxt else 0.0)
        out.append(RemovalCandidate(i, p.track_id, p.title, round(saves, 2), round(score, 3),
                                    tuple(reasons)))
    out.sort(key=lambda c: (-c.score, -c.saves_s))
    return out


def pick_removals(cands: list[RemovalCandidate], need_s: float) -> list[RemovalCandidate]:
    """Greedy from the top until the saving covers `need_s`.

    First pass never picks two neighbours: the seam reasoning for each assumed
    the other was still there. When that alone cannot reach the target (a set
    far over length), a second pass fills the rest in rank order regardless.
    Empty when even removing every candidate would not be enough.
    """
    picked: list[RemovalCandidate] = []
    taken: set[int] = set()
    saved = 0.0
    for allow_neighbours in (False, True):
        for c in cands:
            if saved >= need_s:
                break
            if c.index in taken:
                continue
            if not allow_neighbours and (c.index - 1 in taken or c.index + 1 in taken):
                continue
            picked.append(c)
            taken.add(c.index)
            saved += c.saves_s
    return picked if saved >= need_s else []
