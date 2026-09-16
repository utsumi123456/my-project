"""Energy curve derived from rekordbox phrase analysis (spec B-3).

This is a phrase-kind proxy, not loudness: each phrase label maps to an energy
level, and we sample the level along set time. It is deterministic and honest
about its basis (label -> level table below, tunable). Tracks without phrase
data contribute a flat "unknown" band that the UI greys out.
"""
from __future__ import annotations

from dataclasses import dataclass

from setagent.analysis.phrases import blocks
from setagent.analysis.timing import Timeline
from setagent.rekordbox.anlz import AnlzFile

# label -> energy in [0,1]. Drop/chorus peak; intro/outro trough.
ENERGY = {
    "intro": 0.20, "up": 0.55, "down": 0.30, "bridge": 0.45,
    "verse1": 0.45, "verse2": 0.50, "verse3": 0.55, "verse4": 0.60,
    "verse5": 0.62, "verse6": 0.64, "chorus": 0.92, "drop": 0.92, "outro": 0.22,
}
UNKNOWN = 0.5


@dataclass(frozen=True)
class EnergyPoint:
    time_s: float
    energy: float
    known: bool


def track_energy_at(a: AnlzFile, frac: float) -> float:
    """Energy at a fraction (0..1) through a track, from its phrase blocks."""
    s = a.structure
    if not s or not s.phrases:
        return UNKNOWN
    bl = blocks(s.phrases, s.end_beat)
    beat = frac * s.end_beat
    for b in bl:
        if b.start_beat <= beat < b.end_beat:
            return ENERGY.get(b.label, UNKNOWN)
    return ENERGY.get(bl[-1].label, UNKNOWN) if bl else UNKNOWN


def set_energy_curve(timeline: Timeline, anlz_by_id: dict, samples_per_track: int = 12) -> list[EnergyPoint]:
    """Sample an energy curve across the whole set, in set-time seconds."""
    pts: list[EnergyPoint] = []
    for p in timeline.placements:
        a = anlz_by_id.get(p.track_id)
        known = bool(a and a.structure and a.structure.phrases)
        span = max(p.end_s - p.start_s, 0.001)
        for i in range(samples_per_track):
            frac = i / (samples_per_track - 1)
            e = track_energy_at(a, frac) if known else UNKNOWN
            pts.append(EnergyPoint(p.start_s + frac * span, e, known))
    return pts
