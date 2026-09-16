"""Mix-tendency presets → play range, derived from rekordbox phrase analysis (spec B-5).

Definitions are data (PRESET_CONFIG) so they can be tuned per genre without code
changes. Initial values were chosen after inspecting real jungle/hardcore/dnb
tracks (TAD-6, 2026-09); treat them as a starting point, not a truth.

Vocabulary
  drop block : a run of consecutive "chorus" phrases (both high and mid/low moods).
  lead-in    : bars kept *before* the first drop so the DJ can mix in.
  tail       : bars kept *after* the drop block so the DJ can mix out.
"""
from __future__ import annotations

from dataclasses import dataclass

from setagent.rekordbox.anlz import AnlzFile, Phrase

PRESET_CONFIG = {
    "drop_labels": {"chorus"},
    "min_drop_bars": 8,        # shorter chorus blocks are ignored (jungle/hardcore emit 2-4 bar "chorus")
    "max_drop_bars": None,     # cap a very long drop (dnb: one chorus block can be the whole track); None = no cap
    "one_drop": {"lead_in_bars": 16, "tail_bars": 8},
    "two_drop": {"lead_in_bars": 16, "tail_bars": 8},
    "short":    {"intro_keep_bars": 8, "outro_keep_bars": 8},
}


@dataclass(frozen=True)
class Block:
    label: str
    start_beat: int
    end_beat: int          # exclusive

    @property
    def bars(self) -> float:
        return (self.end_beat - self.start_beat) / 4


@dataclass(frozen=True)
class RangeResult:
    preset: str
    play_in_ms: int
    play_out_ms: int
    start_beat: int
    end_beat: int
    note: str = ""


def blocks(phrases: list[Phrase], end_beat: int, drop_labels=None) -> list[Block]:
    """Merge consecutive phrases with the same class (drop / other) into blocks."""
    drop_labels = drop_labels or PRESET_CONFIG["drop_labels"]
    out: list[Block] = []
    for i, p in enumerate(phrases):
        nxt = phrases[i + 1].beat if i + 1 < len(phrases) else end_beat
        cls = "drop" if p.label in drop_labels else p.label
        if out and out[-1].label == cls and out[-1].end_beat == p.beat:
            out[-1] = Block(cls, out[-1].start_beat, nxt)
        else:
            out.append(Block(cls, p.beat, nxt))
    return out


def drop_blocks(a: AnlzFile, cfg: dict | None = None) -> list[Block]:
    """Drop blocks that are long enough to count (cfg['min_drop_bars'])."""
    cfg = cfg or PRESET_CONFIG
    s = a.structure
    if not s:
        return []
    return [b for b in blocks(s.phrases, s.end_beat, cfg["drop_labels"])
            if b.label == "drop" and b.bars >= cfg.get("min_drop_bars", 0)]


def beat_to_ms(a: AnlzFile, beat: int) -> int:
    """beat is 1-based grid index (phrase.beat convention)."""
    if not a.beats:
        raise ValueError("no beat grid")
    i = min(max(beat, 1), len(a.beats)) - 1
    return a.beats[i].time_ms


def preset_range(a: AnlzFile, preset: str, cfg: dict | None = None) -> RangeResult | None:
    """Return the play range for a preset, or None when phrase data is missing
    (caller keeps 'full' and shows a warning). Never guesses without phrases."""
    cfg = cfg or PRESET_CONFIG
    if not a.beats:
        return None
    s = a.structure
    total = s.end_beat if s else len(a.beats)
    if preset == "full" or s is None:
        return RangeResult("full", beat_to_ms(a, 1), beat_to_ms(a, total), 1, total,
                           "" if s else "no phrase data; full length")
    drops = drop_blocks(a, cfg)
    if preset in ("one_drop", "two_drop"):
        if not drops:
            r = preset_range(a, "short", cfg)
            return RangeResult(preset, r.play_in_ms, r.play_out_ms, r.start_beat, r.end_beat,
                               "no chorus/drop phrase found; fell back to short") if r else None
        c = cfg[preset]
        n = 1 if preset == "one_drop" else min(2, len(drops))
        first, last = drops[0], drops[n - 1]
        last_end = last.end_beat
        cap = cfg.get("max_drop_bars")
        note = ""
        if cap and (last.end_beat - last.start_beat) / 4 > cap:
            last_end = last.start_beat + cap * 4
            note = f"drop capped at {cap} bars"
        start = max(1, first.start_beat - c["lead_in_bars"] * 4)
        end = min(total, last_end + c["tail_bars"] * 4)
        if preset == "two_drop" and len(drops) < 2:
            note = (note + "; " if note else "") + "only one drop; two_drop == one_drop"
        return RangeResult(preset, beat_to_ms(a, start), beat_to_ms(a, end), start, end, note)
    if preset == "short":
        c = cfg["short"]
        non_intro = [p for p in s.phrases if p.label != "intro"]
        outro = [p for p in s.phrases if p.label == "outro"]
        first_body = non_intro[0].beat if non_intro else 1
        outro_start = outro[0].beat if outro else total
        start = max(1, first_body - c["intro_keep_bars"] * 4)
        end = min(total, outro_start + c["outro_keep_bars"] * 4)
        return RangeResult("short", beat_to_ms(a, start), beat_to_ms(a, end), start, end)
    raise ValueError(f"unknown preset {preset}")


def describe(a: AnlzFile) -> str:
    """One-line human summary used in reports / the panel."""
    s = a.structure
    if not s:
        return "phrases: none"
    bl = blocks(s.phrases, s.end_beat)
    return f"mood={s.mood_name} " + " ".join(f"{b.label}[{b.bars:.0f}]" for b in bl)
