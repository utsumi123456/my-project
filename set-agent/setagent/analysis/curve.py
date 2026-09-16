"""Target energy curve, deviation and flatness (spec B-3 / stories S2-3..S2-6).

The *actual* curve comes from phrase analysis (analysis.energy). This module adds
the DJ's *intent*: a hand-drawn target shape, four starting templates, the gap
between intent and reality, and a flatness check that answers the complaint this
whole tool exists for — "I played it safe again".

Everything here is deterministic and unit-testable. Positions are stored as a
fraction of the set (0..1) so a curve survives the set getting longer or shorter.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from setagent.analysis.energy import EnergyPoint

# --------------------------------------------------------------------- curve

Point = tuple[float, float]     # (position 0..1, energy 0..1)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass
class TargetCurve:
    """A piecewise-linear intent curve over the set, in normalised position."""
    points: list[Point] = field(default_factory=lambda: [(0.0, 0.3), (1.0, 0.3)])
    name: str = "custom"

    def __post_init__(self) -> None:
        self.normalise()

    def normalise(self) -> None:
        pts = [(_clamp(x), _clamp(y)) for x, y in self.points]
        pts.sort(key=lambda p: p[0])
        # de-duplicate identical positions, keeping the last value set there
        out: list[Point] = []
        for p in pts:
            if out and abs(out[-1][0] - p[0]) < 1e-9:
                out[-1] = p
            else:
                out.append(p)
        if not out:
            out = [(0.0, 0.3), (1.0, 0.3)]
        if out[0][0] > 0.0:
            out.insert(0, (0.0, out[0][1]))
        if out[-1][0] < 1.0:
            out.append((1.0, out[-1][1]))
        self.points = out

    def at(self, pos: float) -> float:
        """Energy at a normalised position (0..1), linearly interpolated."""
        pos = _clamp(pos)
        pts = self.points
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            if pos <= x1:
                if x1 - x0 < 1e-9:
                    return y1
                f = (pos - x0) / (x1 - x0)
                return y0 + (y1 - y0) * f
        return pts[-1][1]

    def at_time(self, time_s: float, total_s: float) -> float:
        return self.at(time_s / total_s if total_s > 0 else 0.0)

    # -- editing (used by the GUI; each call keeps the curve well-formed) --

    def move_point(self, index: int, pos: float, energy: float) -> None:
        if not 0 <= index < len(self.points):
            raise IndexError(index)
        # endpoints keep their position so the curve always spans the set
        if index == 0:
            pos = 0.0
        elif index == len(self.points) - 1:
            pos = 1.0
        self.points[index] = (_clamp(pos), _clamp(energy))
        self.name = "custom"
        self.normalise()

    def add_point(self, pos: float, energy: float) -> int:
        self.points.append((_clamp(pos), _clamp(energy)))
        self.name = "custom"
        self.normalise()
        return min(range(len(self.points)), key=lambda i: abs(self.points[i][0] - _clamp(pos)))

    def remove_point(self, index: int) -> None:
        if index in (0, len(self.points) - 1) or len(self.points) <= 2:
            return                      # never delete the endpoints
        self.points.pop(index)
        self.name = "custom"

    def nearest_point(self, pos: float, energy: float, aspect: float = 1.0) -> tuple[int, float]:
        """Index of the closest control point and its distance (position units
        scaled by `aspect` so the hit test matches what the eye sees on screen)."""
        best, best_d = 0, float("inf")
        for i, (x, y) in enumerate(self.points):
            d = ((x - pos) * aspect) ** 2 + (y - energy) ** 2
            if d < best_d:
                best, best_d = i, d
        return best, best_d ** 0.5


# ------------------------------------------------------------------ templates
# Four shapes a DJ actually plans around. Deliberately coarse: they are a
# starting point to drag from, not a prescription (spec A-8 "余地を残す").

TEMPLATES: dict[str, list[Point]] = {
    "build":     [(0.0, 0.25), (0.35, 0.45), (0.7, 0.72), (0.92, 0.95), (1.0, 0.80)],
    "peak_mid":  [(0.0, 0.25), (0.25, 0.60), (0.45, 0.95), (0.6, 0.70), (0.8, 0.85), (1.0, 0.35)],
    "peak_late": [(0.0, 0.22), (0.3, 0.45), (0.55, 0.55), (0.8, 0.95), (0.92, 0.90), (1.0, 0.40)],
    "wave":      [(0.0, 0.25), (0.2, 0.80), (0.35, 0.45), (0.55, 0.88), (0.7, 0.50), (0.88, 0.95), (1.0, 0.40)],
}

TEMPLATE_LABELS = {
    "build":     "build (右肩上がり)",
    "peak_mid":  "peak_mid (中盤ピーク)",
    "peak_late": "peak_late (後半ピーク)",
    "wave":      "wave (山谷を繰り返す)",
}


def template(name: str) -> TargetCurve:
    if name not in TEMPLATES:
        raise KeyError(name)
    return TargetCurve(points=list(TEMPLATES[name]), name=name)


# ------------------------------------------------------------------ deviation

@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    value: float            # mean signed delta (deviation) or energy range (flat)
    kind: str               # "over" | "under" | "flat"

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def _merge(spans: list[tuple[float, float, float, str]], min_duration_s: float) -> list[Segment]:
    """Merge adjacent same-kind spans and drop the ones that are too short."""
    out: list[Segment] = []
    for start, end, value, kind in spans:
        if out and out[-1].kind == kind and abs(out[-1].end_s - start) < 1e-6:
            prev = out[-1]
            span_prev = max(prev.duration_s, 1e-9)
            span_new = max(end - start, 1e-9)
            merged = (prev.value * span_prev + value * span_new) / (span_prev + span_new)
            out[-1] = Segment(prev.start_s, end, merged, kind)
        else:
            out.append(Segment(start, end, value, kind))
    return [s for s in out if s.duration_s >= min_duration_s]


def deviation(points: list[EnergyPoint], curve: TargetCurve, total_s: float,
              threshold: float = 0.18, min_duration_s: float = 45.0,
              known_only: bool = True) -> list[Segment]:
    """Stretches where the set drifts from the intended shape (S2-4).

    `threshold` is the energy gap that counts as drift; `min_duration_s` keeps
    a one-phrase blip from being reported as a problem.
    """
    usable = [p for p in points if p.known or not known_only]
    if len(usable) < 2 or total_s <= 0:
        return []
    spans: list[tuple[float, float, float, str]] = []
    for a, b in zip(usable, usable[1:]):
        if b.time_s <= a.time_s:
            continue
        mid = (a.time_s + b.time_s) / 2
        actual = (a.energy + b.energy) / 2
        delta = actual - curve.at_time(mid, total_s)
        if delta > threshold:
            spans.append((a.time_s, b.time_s, delta, "over"))
        elif delta < -threshold:
            spans.append((a.time_s, b.time_s, delta, "under"))
    return _merge(spans, min_duration_s)


def flat_segments(points: list[EnergyPoint], min_duration_s: float = 300.0,
                  span_threshold: float = 0.22, known_only: bool = True) -> list[Segment]:
    """Stretches where nothing happens (S2-6): the energy range stays inside
    `span_threshold` for at least `min_duration_s`. Reported as the longest
    non-overlapping runs, so one 20-minute plateau is one warning, not twelve.
    """
    usable = [p for p in points if p.known or not known_only]
    if len(usable) < 2:
        return []
    out: list[Segment] = []
    i = 0
    n = len(usable)
    while i < n - 1:
        lo = hi = usable[i].energy
        j = i + 1
        while j < n:
            e = usable[j].energy
            nlo, nhi = min(lo, e), max(hi, e)
            if nhi - nlo > span_threshold:
                break
            lo, hi = nlo, nhi
            j += 1
        end_idx = j - 1
        dur = usable[end_idx].time_s - usable[i].time_s
        if dur >= min_duration_s:
            out.append(Segment(usable[i].time_s, usable[end_idx].time_s, hi - lo, "flat"))
            i = end_idx            # continue from the end of this plateau
        else:
            i += 1
    return out


def describe(seg: Segment) -> str:
    from setagent.analysis.timing import fmt
    span = f"{fmt(seg.start_s)}-{fmt(seg.end_s)}"
    if seg.kind == "flat":
        return f"{span} 平坦（振れ幅 {seg.value:.2f}）"
    word = "目標より高い" if seg.kind == "over" else "目標より低い"
    return f"{span} {word}（差 {seg.value:+.2f}）"
