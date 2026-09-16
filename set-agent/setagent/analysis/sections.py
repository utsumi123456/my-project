"""Milestones and the skeleton view (spec B-4 / stories S3-1..S3-4).

A DJ builds from the bones: "this track at 45 minutes, that one to close".
Milestones are those bones. Everything between two milestones is a *section*
with its own budget — how long it is meant to run, how long it actually runs,
and roughly how many more tracks fit in the gap.

Deterministic; the agent reads these numbers, it does not invent them.
"""
from __future__ import annotations

from dataclasses import dataclass

from setagent.analysis.timing import Timeline, fmt
from setagent.domain.draft import SetDraft


@dataclass(frozen=True)
class MilestoneStatus:
    index: int
    track_id: str
    title: str
    actual_s: float
    target_s: int | None

    @property
    def delta_s(self) -> float | None:
        """Positive = later than intended."""
        return None if self.target_s is None else self.actual_s - self.target_s

    def label(self) -> str:
        if self.target_s is None:
            return f"{self.title[:24]} @ {fmt(self.actual_s)}"
        d = self.delta_s or 0.0
        sign = "+" if d >= 0 else "-"
        return f"{self.title[:24]} @ {fmt(self.actual_s)} (目標 {fmt(self.target_s)} / {sign}{fmt(abs(d))})"


@dataclass(frozen=True)
class Section:
    index: int
    start_title: str            # the milestone that opens the section
    end_title: str | None       # the next milestone, or None for the tail
    first_track: int            # placement index range, inclusive
    last_track: int
    start_s: float
    end_s: float
    target_start_s: int | None
    target_end_s: int | None
    avg_play_s: float

    @property
    def actual_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def target_s(self) -> float | None:
        if self.target_start_s is None or self.target_end_s is None:
            return None
        return float(self.target_end_s - self.target_start_s)

    @property
    def delta_s(self) -> float | None:
        """Positive = the section runs longer than its budget."""
        t = self.target_s
        return None if t is None else self.actual_s - t

    @property
    def track_count(self) -> int:
        return self.last_track - self.first_track + 1

    @property
    def room_for_tracks(self) -> int | None:
        """How many more tracks fit in the remaining budget (negative = must cut)."""
        d = self.delta_s
        if d is None or self.avg_play_s <= 0:
            return None
        return int(-d // self.avg_play_s) if d < 0 else -int(d // self.avg_play_s)


def milestones(draft: SetDraft, timeline: Timeline) -> list[MilestoneStatus]:
    out: list[MilestoneStatus] = []
    for i, (e, p) in enumerate(zip(draft.tracks, timeline.placements)):
        if e.is_milestone:
            out.append(MilestoneStatus(i, e.track_id, p.title, p.start_s, e.target_time_s))
    return out


def sections(draft: SetDraft, timeline: Timeline) -> list[Section]:
    """Split the set at its milestones. The stretch before the first milestone
    is section 0 ("開始"); the stretch after the last one runs to the end."""
    ps = timeline.placements
    if not ps:
        return []
    marks = [i for i, e in enumerate(draft.tracks) if e.is_milestone]
    bounds = sorted(set([0] + marks))
    avg = timeline.total_s / len(ps) if ps else 0.0
    out: list[Section] = []
    for n, start_i in enumerate(bounds):
        end_i = bounds[n + 1] - 1 if n + 1 < len(bounds) else len(ps) - 1
        if end_i < start_i:
            continue
        nxt = bounds[n + 1] if n + 1 < len(bounds) else None
        start_title = ps[start_i].title if start_i in marks else "開始"
        end_title = ps[nxt].title if nxt is not None else None
        t_start = draft.tracks[start_i].target_time_s if start_i in marks else (0 if start_i == 0 else None)
        t_end = draft.tracks[nxt].target_time_s if nxt is not None else draft.constraints.target_length_s
        out.append(Section(
            index=n, start_title=start_title, end_title=end_title,
            first_track=start_i, last_track=end_i,
            start_s=ps[start_i].start_s, end_s=ps[end_i].end_s,
            target_start_s=t_start, target_end_s=t_end, avg_play_s=avg,
        ))
    return out


def skeleton(draft: SetDraft, timeline: Timeline) -> list[MilestoneStatus]:
    """The skeleton-only view (S3-4): milestones plus the first track, so the
    set always has a visible starting point even before any bone is set."""
    ms = milestones(draft, timeline)
    if timeline.placements and (not ms or ms[0].index != 0):
        p = timeline.placements[0]
        e = draft.tracks[0]
        ms.insert(0, MilestoneStatus(0, e.track_id, p.title, p.start_s, e.target_time_s))
    return ms


def describe(s: Section) -> str:
    head = f"[{s.index}] {s.start_title[:18]} → {(s.end_title or 'END')[:18]}"
    body = f"{s.track_count}曲 {fmt(s.actual_s)}"
    t = s.target_s
    if t is None:
        return f"{head}  {body}"
    d = s.delta_s or 0.0
    sign = "+" if d >= 0 else "-"
    room = s.room_for_tracks
    tail = "" if room is None else (f" / あと{room}曲入る" if room > 0 else
                                    (f" / {-room}曲分オーバー" if room < 0 else " / ちょうど"))
    return f"{head}  {body} (目標 {fmt(t)} / {sign}{fmt(abs(d))}){tail}"
