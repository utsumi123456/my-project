"""Change Set — proposals the user approves, reject-first (spec B-8).

Design principle 1 made concrete: the agent cannot change anything. It hands over
a list of operations with a reason; the user sees the before/after numbers, approves
what they want, and the approved operations go onto the same History as hand edits.

Two guards run *before* the user ever sees a proposal:
  - a locked track cannot be touched (spec B-1);
  - a proposal must not push a milestone further away from its target time (B-4).
Both return a reason string, which is what the agent gets back so it can try again.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Iterable

from setagent.analysis.curve import TargetCurve, deviation, flat_segments
from setagent.analysis.energy import set_energy_curve
from setagent.analysis.sections import milestones
from setagent.analysis.timing import Timeline, compute, fmt
from setagent.domain.draft import (Command, Insert, LockedError, Move, Remove, SetDraft,
                                   SetMilestone, SetRange, SetTempo, SetTransition)

OPS = ("set_range", "move", "insert", "remove", "set_tempo", "set_milestone", "set_transition")


class Rejected(Exception):
    """The proposal never reaches the user. The message goes back to the agent."""


def parse_mmss(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    mm, ss = str(v).split(":")
    return int(mm) * 60 + int(ss)


@dataclass
class Op:
    """One operation, in the wire shape the agent emits (spec E-6)."""
    op: str
    params: dict = field(default_factory=dict)
    reason: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Op":
        d = dict(d)
        name = d.pop("op", None)
        reason = d.pop("reason", "")
        if name not in OPS:
            raise Rejected(f"未知の操作 '{name}'。使えるのは {', '.join(OPS)}")
        return cls(name, d, reason)

    def describe(self, title_of) -> str:
        p = self.params
        ref = p.get("track_ref") or p.get("track_id") or p.get("from_ref") or ""
        name = title_of(ref) if ref else ""
        if self.op == "set_range":
            return f"{name}: 再生範囲を {p.get('preset', 'custom')} に"
        if self.op == "move":
            return f"{name}: {p.get('to_index', 0) + 1} 番目へ移動"
        if self.op == "insert":
            return f"{name}: {p.get('at_index', 0) + 1} 番目に挿入"
        if self.op == "remove":
            return f"{name}: セットから外す"
        if self.op == "set_tempo":
            return f"{name}: テンポを {p.get('bpm')} に"
        if self.op == "set_milestone":
            t = p.get("target_time")
            return f"{name}: マイルストーン{'解除' if not p.get('value', True) else ''}" + (f"（目標 {t}）" if t else "")
        if self.op == "set_transition":
            return f"{name}: 重なりを {p.get('overlap_bars')} 小節に"
        return self.op

    def to_command(self) -> Command:
        p = self.params
        if self.op == "set_range":
            return SetRange(p["track_ref"], int(p.get("play_in", 0) or 0),
                            p.get("play_out"), p.get("preset", "custom"))
        if self.op == "move":
            return Move(p["track_ref"], int(p["to_index"]))
        if self.op == "insert":
            return Insert(p["track_id"], int(p["at_index"]), p.get("preset"))
        if self.op == "remove":
            return Remove(p["track_ref"])
        if self.op == "set_tempo":
            return SetTempo(p["track_ref"], float(p["bpm"]) if p.get("bpm") is not None else None)
        if self.op == "set_milestone":
            return SetMilestone(p["track_ref"], bool(p.get("value", True)),
                                parse_mmss(p.get("target_time")))
        if self.op == "set_transition":
            return SetTransition(int(p["from_ref"]), int(p["overlap_bars"]))
        raise Rejected(f"未知の操作 '{self.op}'")


@dataclass
class Proposal:
    """What the agent emits: a reason and a list of operations."""
    reason: str
    operations: list[Op]
    title: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Proposal":
        ops = [Op.from_dict(o) for o in d.get("operations", [])]
        if not ops:
            raise Rejected("操作が空の提案は出せない")
        return cls(d.get("reason", ""), ops, d.get("title", ""))


# ------------------------------------------------------------------ snapshot

@dataclass(frozen=True)
class Snapshot:
    """The numbers a DJ actually compares before and after a change (B-8)."""
    total_s: float
    delta_s: float | None
    peak_time_s: float | None
    deviation_s: float
    flat_s: float
    warnings: int

    def diff_lines(self, other: "Snapshot") -> list[str]:
        out = [f"総尺 {fmt(self.total_s)} → {fmt(other.total_s)}"]
        if self.delta_s is not None and other.delta_s is not None:
            out.append(f"目標との差 {fmt(self.delta_s)} → {fmt(other.delta_s)}")
        if self.peak_time_s is not None and other.peak_time_s is not None and \
                abs(self.peak_time_s - other.peak_time_s) > 1:
            out.append(f"ピーク位置 {fmt(self.peak_time_s)} → {fmt(other.peak_time_s)}")
        if abs(self.deviation_s - other.deviation_s) > 1:
            out.append(f"目標カーブとの乖離 {fmt(self.deviation_s)} → {fmt(other.deviation_s)}")
        if abs(self.flat_s - other.flat_s) > 1:
            out.append(f"平坦な区間 {fmt(self.flat_s)} → {fmt(other.flat_s)}")
        return out


def snapshot(draft: SetDraft, lib, anlz: dict, curve: TargetCurve | None = None,
             timeline: Timeline | None = None) -> Snapshot:
    tl = timeline or compute(draft, lib)
    pts = set_energy_curve(tl, anlz)
    known = [p for p in pts if p.known]
    peak = max(known, key=lambda p: p.energy).time_s if known else None
    dev = sum(s.duration_s for s in deviation(pts, curve, max(tl.total_s, 1.0))) if curve else 0.0
    flat = sum(s.duration_s for s in flat_segments(pts))
    return Snapshot(tl.total_s, tl.delta_s, peak, dev, flat, len(tl.warnings))


# ---------------------------------------------------------------- change set

@dataclass
class Item:
    op: Op
    command: Command
    approved: bool = True          # cards start checked; the user unchecks what they don't want


@dataclass
class ChangeSet:
    reason: str
    items: list[Item]
    before: Snapshot
    after: Snapshot
    title: str = ""
    applied: bool = False

    @property
    def diff_lines(self) -> list[str]:
        return self.before.diff_lines(self.after)

    def approved_commands(self) -> list[Command]:
        return [copy.deepcopy(i.command) for i in self.items if i.approved]

    def preview(self, draft: SetDraft, lib) -> Timeline:
        """Ghost timeline for what is currently ticked (S4-3). Draft untouched."""
        from setagent.analysis.timing import simulate
        return simulate(draft, lib, self.approved_commands())

    def signature(self) -> tuple:
        """Identity of the proposal, so a rejected one is not shown again (B-8)."""
        return tuple(sorted((i.op.op, repr(sorted(i.op.params.items()))) for i in self.items))


def _check_locks(draft: SetDraft, cmds: Iterable[Command]) -> None:
    d = copy.deepcopy(draft)
    for c in cmds:
        try:
            c.check(d)
        except LockedError as ex:
            raise Rejected(f"ロックされた曲には触れられない（{ex}）。別の曲で組み直せ")
        except (KeyError, IndexError) as ex:
            raise Rejected(f"セットに無い曲を指している（{ex}）")
        c.apply(d)


def _check_milestones(draft: SetDraft, lib, cmds: list[Command]) -> None:
    """A proposal may not push a milestone further from its target time (B-4/B-8)."""
    from setagent.analysis.timing import simulate
    before = {m.track_id: m.delta_s for m in milestones(draft, compute(draft, lib))}
    after_tl = simulate(draft, lib, cmds)
    d = copy.deepcopy(draft)
    for c in cmds:
        c.check(d); c.apply(d)
    tol = draft.constraints.tolerance_s
    for m in milestones(d, after_tl):
        da = m.delta_s
        db = before.get(m.track_id)
        if da is None or db is None:
            continue
        if abs(da) > tol and abs(da) > abs(db) + 1:
            raise Rejected(
                f"「{m.title[:24]}」が目標時刻から {fmt(abs(da))} ずれる"
                f"（今は {fmt(abs(db))}）。マイルストーンを崩す案は出せない")


def build_change_set(draft: SetDraft, lib, anlz: dict, proposal: Proposal,
                     curve: TargetCurve | None = None) -> ChangeSet:
    """Validate and price a proposal. Raises Rejected before the user sees it."""
    cmds = [o.to_command() for o in proposal.operations]
    _check_locks(draft, cmds)
    _check_milestones(draft, lib, cmds)
    before = snapshot(draft, lib, anlz, curve)
    from setagent.analysis.timing import simulate
    after_tl = simulate(draft, lib, cmds)
    d = copy.deepcopy(draft)
    for c in cmds:
        c.check(d); c.apply(d)
    after = snapshot(d, lib, anlz, curve, timeline=after_tl)
    return ChangeSet(proposal.reason, [Item(o, c) for o, c in zip(proposal.operations, cmds)],
                     before, after, proposal.title)


# ------------------------------------------------------------------- metrics

@dataclass
class ProposalLog:
    """Rejection rate — the guardrail metric for 'is the agent being a nuisance?' (A-5)."""
    proposed: int = 0
    approved_ops: int = 0
    rejected_ops: int = 0
    dropped: int = 0                       # never shown (locks / milestones)
    seen: set = field(default_factory=set)

    def record_proposal(self, cs: ChangeSet) -> None:
        self.proposed += 1
        self.seen.add(cs.signature())

    def record_outcome(self, cs: ChangeSet) -> None:
        self.approved_ops += sum(1 for i in cs.items if i.approved)
        self.rejected_ops += sum(1 for i in cs.items if not i.approved)

    def record_drop(self) -> None:
        self.dropped += 1

    def already_seen(self, cs: ChangeSet) -> bool:
        return cs.signature() in self.seen

    @property
    def rejection_rate(self) -> float:
        total = self.approved_ops + self.rejected_ops
        return self.rejected_ops / total if total else 0.0

    def summary(self) -> str:
        return (f"提案 {self.proposed} / 承認 {self.approved_ops} / 却下 {self.rejected_ops}"
                f"（却下率 {self.rejection_rate:.0%}） 生成時に弾いた案 {self.dropped}")
