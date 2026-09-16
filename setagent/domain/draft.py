"""Set Draft — the single editable object at the centre of Set Agent (spec B-1).

Every mutation goes through a Command so that manual edits and agent-proposed
Change Sets share one history (undo/redo/checkpoints). The agent never touches
a draft directly; it only produces Commands that the user approves (spec B-8).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

Preset = Literal["full", "one_drop", "two_drop", "short", "custom"]
LockTarget = Literal["position", "range", "tempo", "all"]


@dataclass
class TrackEntry:
    track_id: str
    play_in_ms: int = 0            # source-time range; 0..source length
    play_out_ms: int | None = None # None = to the end of the track
    tempo: float | None = None     # set BPM; None = original
    preset: Preset = "full"
    is_milestone: bool = False
    target_time_s: int | None = None
    locks: set[str] = field(default_factory=set)
    note: str = ""

    def locked(self, target: LockTarget) -> bool:
        return "all" in self.locks or target in self.locks


@dataclass
class Transition:
    from_index: int
    overlap_bars: int = 8          # spec default; marked as estimate when defaulted
    explicit: bool = False


@dataclass
class Constraints:
    target_length_s: int | None = None
    tolerance_s: int = 60
    preset: Preset = "full"
    theme: str = ""
    default_overlap_bars: int = 8


@dataclass
class SetDraft:
    name: str = "untitled"
    tracks: list[TrackEntry] = field(default_factory=list)
    transitions: dict[int, Transition] = field(default_factory=dict)
    constraints: Constraints = field(default_factory=Constraints)

    def transition_after(self, i: int) -> Transition:
        return self.transitions.get(i, Transition(i, self.constraints.default_overlap_bars, False))

    def find(self, track_ref: str) -> int:
        """track_ref = track_id or '#<index>'."""
        if track_ref.startswith("#"):
            return int(track_ref[1:])
        for i, t in enumerate(self.tracks):
            if t.track_id == track_ref:
                return i
        raise KeyError(track_ref)


# ------------------------------------------------------------------ commands

class LockedError(Exception):
    pass


class Command:
    """Reversible edit. Subclasses implement apply(); undo restores a snapshot."""
    def __init__(self):
        self._before: SetDraft | None = None

    def describe(self) -> str:
        return type(self).__name__

    def check(self, d: SetDraft) -> None:  # raise LockedError if not permitted
        pass

    def apply(self, d: SetDraft) -> None:
        raise NotImplementedError

    def execute(self, d: SetDraft) -> None:
        self.check(d)
        self._before = copy.deepcopy(d)
        self.apply(d)

    def undo(self, d: SetDraft) -> None:
        assert self._before is not None
        d.__dict__.update(copy.deepcopy(self._before).__dict__)


class Insert(Command):
    def __init__(self, track_id: str, at: int, preset: Preset | None = None):
        super().__init__(); self.track_id, self.at, self.preset = track_id, at, preset
    def apply(self, d):
        d.tracks.insert(self.at, TrackEntry(self.track_id, preset=self.preset or d.constraints.preset))


class Remove(Command):
    def __init__(self, ref: str): super().__init__(); self.ref = ref
    def check(self, d):
        if d.tracks[d.find(self.ref)].locked("position"): raise LockedError(self.ref)
    def apply(self, d): d.tracks.pop(d.find(self.ref))


class Move(Command):
    def __init__(self, ref: str, to: int): super().__init__(); self.ref, self.to = ref, to
    def check(self, d):
        if d.tracks[d.find(self.ref)].locked("position"): raise LockedError(self.ref)
    def apply(self, d):
        t = d.tracks.pop(d.find(self.ref)); d.tracks.insert(self.to, t)


class SetRange(Command):
    def __init__(self, ref: str, play_in_ms: int, play_out_ms: int | None, preset: Preset = "custom"):
        super().__init__(); self.ref, self.pin, self.pout, self.preset = ref, play_in_ms, play_out_ms, preset
    def check(self, d):
        if d.tracks[d.find(self.ref)].locked("range"): raise LockedError(self.ref)
    def apply(self, d):
        t = d.tracks[d.find(self.ref)]; t.play_in_ms, t.play_out_ms, t.preset = self.pin, self.pout, self.preset


class SetTempo(Command):
    def __init__(self, ref: str, bpm: float | None): super().__init__(); self.ref, self.bpm = ref, bpm
    def check(self, d):
        if d.tracks[d.find(self.ref)].locked("tempo"): raise LockedError(self.ref)
    def apply(self, d): d.tracks[d.find(self.ref)].tempo = self.bpm


class SetMilestone(Command):
    def __init__(self, ref: str, value: bool, target_time_s: int | None = None):
        super().__init__(); self.ref, self.value, self.target = ref, value, target_time_s
    def apply(self, d):
        t = d.tracks[d.find(self.ref)]; t.is_milestone = self.value; t.target_time_s = self.target if self.value else None


class SetTransition(Command):
    def __init__(self, from_index: int, overlap_bars: int): super().__init__(); self.i, self.bars = from_index, overlap_bars
    def apply(self, d): d.transitions[self.i] = Transition(self.i, self.bars, True)


class SetLock(Command):
    def __init__(self, ref: str, target: LockTarget, on: bool): super().__init__(); self.ref, self.target, self.on = ref, target, on
    def apply(self, d):
        t = d.tracks[d.find(self.ref)]
        (t.locks.add if self.on else t.locks.discard)(self.target)


class SetTargetLength(Command):
    def __init__(self, seconds: int | None, tolerance_s: int | None = None):
        super().__init__(); self.s, self.tol = seconds, tolerance_s
    def apply(self, d):
        d.constraints.target_length_s = self.s
        if self.tol is not None: d.constraints.tolerance_s = self.tol


# ------------------------------------------------------------------ history

class History:
    def __init__(self, draft: SetDraft):
        self.draft = draft
        self._done: list[Command] = []
        self._undone: list[Command] = []
        self._checkpoints: dict[str, SetDraft] = {}

    def run(self, cmd: Command) -> None:
        cmd.execute(self.draft)
        self._done.append(cmd); self._undone.clear()

    def run_all(self, cmds: list[Command]) -> None:
        """Apply a Change Set atomically: all commands are lock-checked first."""
        for c in cmds: c.check(self.draft)
        for c in cmds: self.run(c)

    def undo(self) -> bool:
        if not self._done: return False
        c = self._done.pop(); c.undo(self.draft); self._undone.append(c); return True

    def redo(self) -> bool:
        if not self._undone: return False
        c = self._undone.pop(); c.execute(self.draft); self._done.append(c); return True

    def checkpoint(self, name: str) -> None:
        self._checkpoints[name] = copy.deepcopy(self.draft)

    def restore(self, name: str) -> None:
        self.draft.__dict__.update(copy.deepcopy(self._checkpoints[name]).__dict__)
        self._done.clear(); self._undone.clear()
