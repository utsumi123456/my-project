"""Time management engine (spec B-2). Deterministic; no LLM anywhere.

play_time = (play_out - play_in) * (original_bpm / set_tempo)
total     = sum(play_time) - sum(overlaps)

Overlaps are expressed in bars of the *outgoing* track at its set tempo:
    overlap_s = bars * 4 * 60 / set_tempo
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from setagent.domain.draft import Command, SetDraft
import copy


class TrackInfo(Protocol):
    id: str
    title: str
    bpm: float
    length_s: int


class TrackSource(Protocol):
    def track(self, track_id: str) -> TrackInfo: ...


@dataclass(frozen=True)
class Placement:
    index: int
    track_id: str
    title: str
    start_s: float
    end_s: float
    play_s: float
    set_tempo: float
    original_bpm: float
    estimated_overlap: bool     # True when overlap used the default (not user-set)
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Timeline:
    placements: tuple[Placement, ...]
    total_s: float
    target_s: int | None
    tolerance_s: int
    warnings: tuple[str, ...]

    @property
    def delta_s(self) -> float | None:
        return None if self.target_s is None else self.total_s - self.target_s

    @property
    def within_target(self) -> bool | None:
        d = self.delta_s
        return None if d is None else abs(d) <= self.tolerance_s


def fmt(seconds: float) -> str:
    s = int(round(seconds)); sign = "-" if s < 0 else ""
    s = abs(s); return f"{sign}{s // 60}:{s % 60:02d}"


def compute(draft: SetDraft, src: TrackSource) -> Timeline:
    placements: list[Placement] = []
    warnings: list[str] = []
    cursor = 0.0
    for i, e in enumerate(draft.tracks):
        t = src.track(e.track_id)
        w: list[str] = []
        bpm = t.bpm or 0.0
        if bpm <= 0:
            w.append("no BPM in rekordbox; tempo scaling disabled")
        set_tempo = e.tempo or bpm or 1.0
        out_ms = e.play_out_ms if e.play_out_ms is not None else t.length_s * 1000
        src_len_s = max(0.0, (out_ms - e.play_in_ms) / 1000.0)
        play_s = src_len_s * (bpm / set_tempo) if bpm > 0 else src_len_s
        # BPM jump check vs previous track (set tempos)
        if i > 0 and placements and abs(set_tempo - placements[-1].set_tempo) / max(placements[-1].set_tempo, 1) > 0.08:
            w.append(f"BPM jump {placements[-1].set_tempo:.1f} -> {set_tempo:.1f}")
        start = cursor
        end = start + play_s
        est = False
        if i < len(draft.tracks) - 1:
            tr = draft.transition_after(i)
            est = not tr.explicit
            overlap_s = tr.overlap_bars * 4 * 60.0 / set_tempo
            overlap_s = min(overlap_s, play_s)
            cursor = end - overlap_s
        else:
            cursor = end
        placements.append(Placement(i, t.id, t.title, start, end, play_s, set_tempo, bpm, est, tuple(w)))
    total = placements[-1].end_s if placements else 0.0
    c = draft.constraints
    if c.target_length_s is not None:
        d = total - c.target_length_s
        if d > c.tolerance_s: warnings.append(f"over target by {fmt(d)}")
        elif d < -c.tolerance_s: warnings.append(f"under target by {fmt(-d)}")
    if any(p.estimated_overlap for p in placements[:-1]):
        warnings.append("some transitions use the default overlap (estimate)")
    return Timeline(tuple(placements), total, c.target_length_s, c.tolerance_s, tuple(warnings))


def simulate(draft: SetDraft, src: TrackSource, cmds: list[Command]) -> Timeline:
    """What-if: apply commands to a copy and compute. The real draft is untouched."""
    d = copy.deepcopy(draft)
    for c in cmds:
        c.check(d); c.apply(d)
    return compute(d, src)


@dataclass(frozen=True)
class TrimCandidate:
    track_id: str
    title: str
    action: str          # e.g. "range->one_drop", "tempo +3%"
    saves_s: float
    cmd: Command


def trim_candidates(draft: SetDraft, src: TrackSource, presets: dict[str, tuple[int, int | None]] | None = None) -> list[TrimCandidate]:
    """Deterministic list of 'what would save time' (spec B-2). presets maps
    track_id -> (play_in_ms, play_out_ms) for a shorter preset when known."""
    from setagent.domain.draft import SetRange, SetTempo
    base = compute(draft, src).total_s
    out: list[TrimCandidate] = []
    for e in draft.tracks:
        t = src.track(e.track_id)
        if presets and e.track_id in presets and not e.locked("range"):
            pin, pout = presets[e.track_id]
            cmd = SetRange(e.track_id, pin, pout, "one_drop")
            saves = base - simulate(draft, src, [cmd]).total_s
            if saves > 1: out.append(TrimCandidate(e.track_id, t.title, "range->one_drop", saves, cmd))
        if t.bpm > 0 and not e.locked("tempo"):
            cur = e.tempo or t.bpm
            cmd = SetTempo(e.track_id, round(cur * 1.03, 2))
            saves = base - simulate(draft, src, [cmd]).total_s
            if saves > 1: out.append(TrimCandidate(e.track_id, t.title, "tempo +3%", saves, cmd))
    return sorted(out, key=lambda c: -c.saves_s)
