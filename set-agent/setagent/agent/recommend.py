"""Candidate tracks for a gap in the set (spec B-9, first stage).

Two-stage by design: this half is deterministic and works with no LLM at all.
It scores real rows from the user's library; the LLM (when present) may only
re-order and explain them. Nothing here can invent a title.

The scoring shape is borrowed from Flow Map (spec C-7): BPM, key and length are
*floors* — a candidate that fails them is out, not merely penalised — and the
remaining weight goes on how well the track fits the energy the slot wants.
"""
from __future__ import annotations

from dataclasses import dataclass

from setagent.analysis.energy import UNKNOWN, track_energy_at
from setagent.rekordbox.masterdb import Track

# Camelot wheel: rekordbox ScaleName ("Am", "F#m", "Ab") -> (number, 'A'=minor/'B'=major)
_MINOR = {"Abm": 1, "G#m": 1, "Ebm": 2, "D#m": 2, "Bbm": 3, "A#m": 3, "Fm": 4, "Cm": 5,
          "Gm": 6, "Dm": 7, "Am": 8, "Em": 9, "Bm": 10, "F#m": 11, "Gbm": 11, "Dbm": 12, "C#m": 12}
_MAJOR = {"B": 1, "F#": 2, "Gb": 2, "Db": 3, "C#": 3, "Ab": 4, "G#": 4, "Eb": 5, "D#": 5,
          "Bb": 6, "A#": 6, "F": 7, "C": 8, "G": 9, "D": 10, "A": 11, "E": 12}


def camelot(key: str) -> tuple[int, str] | None:
    k = (key or "").strip()
    if not k:
        return None
    if k in _MINOR:
        return _MINOR[k], "A"
    if k in _MAJOR:
        return _MAJOR[k], "B"
    return None


def key_distance(a: str, b: str) -> int | None:
    """Steps on the Camelot wheel. 0 = same, 1 = neighbour or relative major/minor."""
    ca, cb = camelot(a), camelot(b)
    if not ca or not cb:
        return None
    na, la = ca
    nb, lb = cb
    if la == lb:
        return min((na - nb) % 12, (nb - na) % 12)
    return 1 if na == nb else 1 + min((na - nb) % 12, (nb - na) % 12)


@dataclass(frozen=True)
class Slot:
    """The hole to fill: how long, how energetic, next to what."""
    duration_s: float                    # how much room there is
    target_energy: float | None = None
    bpm: float | None = None             # the set tempo around the gap
    key: str = ""                        # the key of the track before the gap
    bpm_tolerance: float = 0.08          # 8% — a nudge on the platter, not a jump
    max_key_distance: int = 2
    length_slack: float = 0.5            # a track may be 50% longer than the gap


@dataclass(frozen=True)
class Candidate:
    track: Track
    score: float
    play_s: float
    reason: str


def _energy_of(anlz) -> float | None:
    if not anlz or not anlz.structure or not anlz.structure.phrases:
        return None
    # mean of the middle of the track: what it feels like once it is running
    return sum(track_energy_at(anlz, f) for f in (0.35, 0.5, 0.65)) / 3


def candidates(lib, slot: Slot, pool: list[str] | None = None,
               exclude: set[str] | None = None, limit: int = 5) -> list[Candidate]:
    """Real tracks that fit the slot, best first. `pool` limits the search to
    specific track ids (e.g. one playlist); by default the whole library."""
    exclude = exclude or set()
    ids = pool if pool is not None else [t.id for t in lib.db.tracks()]
    out: list[Candidate] = []
    for tid in ids:
        if tid in exclude:
            continue
        try:
            t = lib.track(tid)
        except KeyError:
            continue
        if t.bpm <= 0 or t.length_s <= 0:
            continue

        # --- floors -------------------------------------------------------
        if slot.bpm:
            if abs(t.bpm - slot.bpm) / slot.bpm > slot.bpm_tolerance:
                continue
        kd = key_distance(slot.key, t.key) if slot.key else None
        if kd is not None and kd > slot.max_key_distance:
            continue
        set_tempo = slot.bpm or t.bpm
        play_s = t.length_s * (t.bpm / set_tempo)
        if play_s > slot.duration_s * (1 + slot.length_slack):
            continue

        # --- weights ------------------------------------------------------
        reasons: list[str] = []
        score = 0.0
        if slot.bpm:
            near = 1 - abs(t.bpm - slot.bpm) / (slot.bpm * slot.bpm_tolerance)
            score += 0.25 * max(near, 0.0)
            reasons.append(f"{t.bpm:.0f} BPM")
        if kd is not None:
            score += 0.25 * (1.0 if kd == 0 else 0.7 if kd == 1 else 0.4)
            reasons.append("同キー" if kd == 0 else f"キー{kd}歩" if kd else "")
        elif t.key:
            reasons.append(t.key)

        e = _energy_of(lib.analysis(tid).anlz)
        if slot.target_energy is not None and e is not None:
            score += 0.35 * max(0.0, 1 - abs(e - slot.target_energy) / 0.5)
            reasons.append(f"エネルギー {e:.2f}")
        elif e is None:
            reasons.append("解析なし")

        fit = 1 - abs(play_s - slot.duration_s) / max(slot.duration_s, 1)
        score += 0.15 * max(fit, 0.0)

        from setagent.analysis.timing import fmt
        reasons.append(f"区間に入れると {fmt(play_s)}")
        out.append(Candidate(t, round(score, 4), play_s,
                             " / ".join(r for r in reasons if r)))
    out.sort(key=lambda c: -c.score)
    return out[:limit]
