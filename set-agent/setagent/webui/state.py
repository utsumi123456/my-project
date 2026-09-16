"""Draft + analysis -> plain JSON for the view.

Pure functions over the existing engines. Nothing here computes a musical number
of its own: it reads `analysis.timing`, `analysis.energy`, `analysis.curve` and
`analysis.sections` and reshapes what they return.

The one thing this module *does* add is the phrase strip: rekordbox already knows
where every Intro / Up / Chorus / Down / Outro sits, and the old Canvas UI threw
that away. Phrase beats are mapped to set-time through the beat grid, clipped to
the track's play range, and scaled by the set tempo -- so a block on screen lines
up with the second it is actually heard.
"""
from __future__ import annotations

from setagent.analysis.curve import deviation, flat_segments
from setagent.analysis.energy import set_energy_curve
from setagent.analysis.phrases import blocks
from setagent.analysis.sections import describe as describe_section
from setagent.analysis.sections import sections as compute_sections
from setagent.analysis.timing import compute, fmt, trim_candidates
from setagent.rekordbox.library import PhraseStatus

# Mix presets (analysis.phrases.PRESET_CONFIG) as the DJ reads them. The keys
# stay English in code and settings; only the panel shows these.
PRESET_LABELS = {
    "full": "フル尺",
    "one_drop": "1ドロップ",
    "two_drop": "2ドロップ",
    "short": "イントロ/アウトロ短縮",
}
PRESET_HELP = {
    "full": "各曲を頭から最後まで再生する前提で尺を予測します。",
    "one_drop": "最初のドロップ（コーラス）1つだけをかける前提。ドロップの 16 小節前から入り、8 小節後で抜けます。",
    "two_drop": "ドロップ 2 つまでかける前提。2 つ目のドロップの 8 小節後で抜けます。",
    "short": "ドロップの数は変えず、イントロとアウトロだけを 8 小節ずつ残して詰めます。ドロップが見つからない曲は 1ドロップ/2ドロップ でもこの扱いになります。",
}

# rekordbox's own phrase vocabulary, collapsed to the five groups a DJ acts on.
# Colours live in the view; this only says which group a label belongs to.
PHRASE_GROUP = {
    "intro": "intro", "outro": "outro",
    "up": "up", "down": "down", "bridge": "down",
    "chorus": "chorus", "drop": "chorus",
    "verse1": "verse", "verse2": "verse", "verse3": "verse",
    "verse4": "verse", "verse5": "verse", "verse6": "verse",
}


def beat_ms(anlz, beat: int) -> float | None:
    """Start time of a 1-based beat-grid index, in track milliseconds."""
    if not anlz or not anlz.beats:
        return None
    i = max(0, min(len(anlz.beats) - 1, int(beat) - 1))
    return float(anlz.beats[i].time_ms)


def phrase_spans(anlz, play_in_ms: int, play_out_ms: int | None,
                 start_s: float, bpm: float, set_tempo: float) -> list[dict]:
    """Phrase blocks of one track, in SET-time seconds, clipped to its play range.

    Returns [] when the track has no phrase analysis -- the caller must show that
    as "no data", never as a filled block (spec: never interpolate over a gap).
    """
    s = getattr(anlz, "structure", None)
    if not s or not s.phrases:
        return []
    scale = (bpm / set_tempo) if (bpm and set_tempo) else 1.0
    out: list[dict] = []
    for b in blocks(s.phrases, s.end_beat):
        a_ms, b_ms = beat_ms(anlz, b.start_beat), beat_ms(anlz, b.end_beat)
        if a_ms is None or b_ms is None:
            continue
        lo = max(a_ms, play_in_ms)
        hi = min(b_ms, play_out_ms) if play_out_ms is not None else b_ms
        if hi <= lo:
            continue                       # block falls outside the play range
        out.append({
            "label": b.label,
            "group": PHRASE_GROUP.get(b.label, "verse"),
            "start_s": start_s + (lo - play_in_ms) / 1000.0 * scale,
            "end_s": start_s + (hi - play_in_ms) / 1000.0 * scale,
        })
    return out


def build(draft, lib, anlz_by_id: dict, curve=None, cfg=None,
          selected: int | None = None) -> dict:
    """The whole view model, as JSON-safe primitives."""
    tl = compute(draft, lib)
    total = max(tl.total_s, 1.0)
    pts = set_energy_curve(tl, anlz_by_id)
    dev = deviation(pts, curve, total) if curve else []
    flats = flat_segments(pts)
    secs = compute_sections(draft, tl)

    tracks = []
    present = 0
    for p in tl.placements:
        e = draft.tracks[p.index]
        anlz = anlz_by_id.get(p.track_id)
        ta = lib.analysis(p.track_id)
        known = ta.phrase_status is PhraseStatus.PRESENT and bool(anlz)
        if known:
            present += 1
        tracks.append({
            "i": p.index,
            "track_id": p.track_id,
            "title": p.title,
            "bpm": round(p.original_bpm, 1),
            "set_tempo": round(p.set_tempo, 1),
            "start_s": round(p.start_s, 2),
            "end_s": round(p.end_s, 2),
            "play_s": round(p.play_s, 2),
            "preset": e.preset or "full",
            # source-time range, so the view can drag an edge and convert back
            "play_in_ms": e.play_in_ms,
            "play_out_ms": e.play_out_ms,
            "source_len_s": getattr(lib.track(p.track_id), "length_s", 0) or 0,
            "milestone_s": e.target_time_s if e.is_milestone else None,
            "locks": sorted(e.locks) if e.locks else [],
            "phrases": phrase_spans(anlz, e.play_in_ms, e.play_out_ms,
                                    p.start_s, p.original_bpm, p.set_tempo) if known else [],
            "analysis": ta.phrase_status.value,
            "estimated_overlap": p.estimated_overlap,
            "warnings": list(p.warnings),
        })

    warnings = []
    delta = tl.delta_s
    if delta is not None and abs(delta) > tl.tolerance_s:
        warnings.append({
            "level": "critical" if delta > 0 else "warning",
            "text": ("目標を %s 超過" % fmt(delta)) if delta > 0 else ("目標に %s 足りない" % fmt(-delta)),
        })
    for s in flats:
        warnings.append({"level": "warning",
                         "text": "平坦 %s–%s（振れ幅 %.2f）" % (fmt(s.start_s), fmt(s.end_s), s.value)})
    if any(p.estimated_overlap for p in tl.placements):
        warnings.append({"level": "warning", "text": "一部の繋ぎが既定のオーバーラップ値（推定）を使用"})

    trims = [{"title": c.title, "gain_s": round(c.saves_s, 1), "how": c.action,
              "track_id": c.track_id}
             for c in trim_candidates(draft, lib)]

    return {
        "playlist": draft.name,
        "total_s": round(tl.total_s, 2),
        "target_s": tl.target_s,
        "delta_s": None if delta is None else round(delta, 2),
        "tolerance_s": tl.tolerance_s,
        "tracks": tracks,
        "energy": [{"t": round(p.time_s, 2), "e": round(p.energy, 3), "known": p.known} for p in pts],
        "curve": [[round(pos, 4), round(en, 4)] for pos, en in (curve.points if curve else [])],
        "deviation": [{"start_s": round(d.start_s, 2), "end_s": round(d.end_s, 2),
                       "kind": d.kind, "value": round(d.value, 3)} for d in dev],
        "sections": [{"name": describe_section(s), "index": s.index,
                      "actual_s": round(s.end_s - s.start_s, 2),
                      "target_s": (None if s.target_start_s is None or s.target_end_s is None
                                   else round(s.target_end_s - s.target_start_s, 2)),
                      "tracks": s.last_track - s.first_track + 1,
                      "start_s": round(s.start_s, 2), "end_s": round(s.end_s, 2)}
                     for s in secs],
        "set_bpm": draft.constraints.set_bpm,
        # change points in running order, with the title the DJ recognises
        "bpm_changes": [{"i": p.index, "track_id": p.track_id, "title": p.title,
                         "bpm": draft.constraints.bpm_changes[p.track_id]}
                        for p in tl.placements if p.track_id in draft.constraints.bpm_changes],
        "trims": trims,
        "trim_total_s": round(sum(t["gain_s"] for t in trims), 1),
        "warnings": warnings,
        "analysis": {"present": present, "total": len(tracks)},
        "selected": selected,
    }
