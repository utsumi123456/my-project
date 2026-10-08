"""An improved version of the DJ's playlist, at an intervention level the DJ picks.

Set Agent does not edit the DJ's playlist. What it can offer is a *new*
playlist next to it, written into rekordbox's "Set Agent" folder. How far that
version may stray from the original is the DJ's call, because track selection
is the DJ's craft, not ours ("余計なお世話" is the failure mode):

  light     same tracks. Only rough transitions (key / BPM jumps) are smoothed
            by swapping with a nearby track.
  standard  light + land on the target length: remove the tracks the set
            misses least, or add library tracks that chain by BPM/key (and,
            as a tie-breaker, that the DJ has played after the previous one).
  bold      rebuild the order along the energy curve and the harmonic chain,
            then land on the target length.

At every level a locked or milestone track keeps its place, and nothing is
invented: added tracks come from the DJ's own library through the same
engines the agent uses. Deterministic -- no LLM needed.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field

from setagent.agent.changeset import snapshot
from setagent.agent.recommend import _energy_of, key_distance
from setagent.analysis.phrases import preset_range
from setagent.analysis.removal import removal_candidates
from setagent.analysis.timing import compute, fmt
from setagent.domain.draft import SetDraft, TrackEntry
from setagent.rekordbox.library import PhraseStatus

LEVELS = ("light", "standard", "bold")
LEVEL_LABEL = {"light": "light", "standard": "standard", "bold": "bold"}
LEVEL_HELP = {"light": "曲はそのまま。つなぎだけ整える",
              "standard": "目標の尺に合わせて足し引きする",
              "bold": "展開に合わせて組み直す"}

ROUGH_KEY = 3            # Camelot steps that count as a clash
ROUGH_BPM = 0.08         # 8% apart in original tempo
WINDOW = 4               # light: how far a swap may reach


@dataclass
class Change:
    kind: str            # add | remove | move
    track_id: str
    title: str
    detail: str = ""


@dataclass
class Improved:
    level: str
    source_name: str
    track_ids: list[str]
    changes: list[Change] = field(default_factory=list)
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    note: str = ""

    @property
    def counts(self) -> dict:
        c = {"add": 0, "remove": 0, "move": 0}
        for ch in self.changes:
            c[ch.kind] += 1
        return c

    @property
    def unchanged(self) -> bool:
        return not self.changes

    def to_json(self) -> dict:
        return {"level": self.level, "label": LEVEL_LABEL.get(self.level, self.level),
                "source": self.source_name, "tracks": len(self.track_ids), "track_ids": list(self.track_ids),
                "counts": self.counts, "changes": [asdict(c) for c in self.changes],
                "before": self.before, "after": self.after, "note": self.note}


# ------------------------------------------------------------------ helpers

def _fixed(e: TrackEntry) -> bool:
    return e.is_milestone or e.locked("position")


def _info(lib, tid: str, anlz: dict):
    t = lib.track(tid)
    return t.bpm, t.key, _energy_of(anlz.get(tid) or (lib.analysis(tid).anlz))


def transition_cost(a, b) -> float:
    """0 = seamless. Key clash and tempo jump dominate; energy cliffs add a bit."""
    (ba, ka, ea), (bb, kb, eb) = a, b
    cost = 0.0
    kd = key_distance(ka, kb)
    if kd is not None:
        cost += {0: 0.0, 1: 0.1, 2: 0.35}.get(kd, 0.7 + 0.1 * (kd - 3))
    else:
        cost += 0.3
    if ba > 0 and bb > 0:
        cost += min(abs(ba - bb) / max(ba, 1) / ROUGH_BPM, 2.0) * 0.5
    if ea is not None and eb is not None:
        cost += max(abs(ea - eb) - 0.25, 0.0)
    return cost


def is_rough(a, b) -> bool:
    (ba, ka, _), (bb, kb, _) = a, b
    kd = key_distance(ka, kb)
    return (kd is not None and kd >= ROUGH_KEY) or (ba > 0 and bb > 0 and abs(ba - bb) / max(ba, 1) > ROUGH_BPM)


def rough_count(ids: list[str], info: dict) -> int:
    return sum(1 for a, b in zip(ids, ids[1:]) if is_rough(info[a], info[b]))


def draft_with(base: SetDraft, ids: list[str], lib, preset: str, cfg: dict) -> SetDraft:
    """The base draft's constraints and per-track intent, over a new track list.
    New tracks get the same Mix assumption (preset range) as at load."""
    d = SetDraft(name=base.name, constraints=copy.deepcopy(base.constraints))
    old = {e.track_id: e for e in base.tracks}
    for tid in ids:
        if tid in old:
            d.tracks.append(copy.deepcopy(old[tid]))
            continue
        e = TrackEntry(tid, preset=preset if preset != "full" else "full")
        if preset != "full":
            ta = lib.analysis(tid)
            if ta.phrase_status is PhraseStatus.PRESENT and ta.anlz:
                r = preset_range(ta.anlz, preset, cfg)
                if r:
                    e.play_in_ms, e.play_out_ms = r.play_in_ms, r.play_out_ms
        d.tracks.append(e)
    return d


def _metrics(d: SetDraft, lib, anlz: dict, curve, info: dict) -> dict:
    tl = compute(d, lib)
    sn = snapshot(d, lib, anlz, curve, timeline=tl)
    ids = [e.track_id for e in d.tracks]
    return {"total_s": round(tl.total_s, 1), "total": fmt(tl.total_s),
            "delta_s": None if tl.delta_s is None else round(tl.delta_s, 1),
            "within": tl.within_target, "rough": rough_count(ids, info),
            "peak": fmt(sn.peak_time_s) if sn.peak_time_s is not None else None,
            "deviation_s": round(sn.deviation_s, 1), "tracks": len(ids)}


# ------------------------------------------------------------------ passes

def smooth(ids: list[str], fixed: set[int], info: dict, window: int = WINDOW,
           max_swaps: int | None = None) -> list[str]:
    """Swap the track after a rough seam with a nearby one, best gain first,
    while that lowers the cost of every seam it touches. Fixed positions never
    move. max_swaps keeps the light level light."""
    ids = list(ids)

    def local(pos_list):
        tot = 0.0
        for p in sorted(set(pos_list)):
            if 0 <= p < len(ids) - 1:
                tot += transition_cost(info[ids[p]], info[ids[p + 1]])
        return tot

    swaps = 0
    while max_swaps is None or swaps < max_swaps:
        best, best_gain = None, 1e-6
        for i in range(len(ids) - 1):
            if not is_rough(info[ids[i]], info[ids[i + 1]]) or (i + 1) in fixed:
                continue
            for j in range(i + 2, min(len(ids), i + 2 + window)):
                if j in fixed:
                    continue
                touched = [i, i + 1, j - 1, j]
                before = local(touched)
                ids[i + 1], ids[j] = ids[j], ids[i + 1]
                gain = before - local(touched)
                ids[i + 1], ids[j] = ids[j], ids[i + 1]
                if gain > best_gain:
                    best, best_gain = (i + 1, j), gain
        if best is None:
            break
        a, b = best
        ids[a], ids[b] = ids[b], ids[a]
        swaps += 1
    return ids


def light_cap(n: int) -> int:
    """At most one swap per ~10 tracks, and never fewer than 2."""
    return max(2, n // 10)


def rebuild(ids: list[str], fixed: set[int], info: dict, curve, total_hint: int) -> list[str]:
    """bold: fill the free slots greedily along the curve and the chain, then
    one pass of local smoothing. Fixed positions are anchors."""
    n = len(ids)
    slots: list[str | None] = [ids[i] if i in fixed else None for i in range(n)]
    pool = [ids[i] for i in range(n) if i not in fixed]
    if not pool:
        return list(ids)
    # a free first slot starts from the track whose energy is lowest (the set opens, then builds)
    for i in range(n):
        if slots[i] is not None:
            continue
        prev = slots[i - 1] if i > 0 else None
        want = curve.at(i / max(n - 1, 1)) if curve else None

        def score(t):
            s = transition_cost(info[prev], info[t]) if prev else 0.0
            e = info[t][2]
            if want is not None and e is not None:
                s += abs(e - want) * 1.2
            elif prev is None and e is not None:
                s += e                                    # open low when there is no curve
            nxt = slots[i + 1] if i + 1 < n else None
            if nxt is not None:
                s += transition_cost(info[t], info[nxt])
            return s

        pick = min(pool, key=score)
        pool.remove(pick)
        slots[i] = pick
    return smooth([s for s in slots if s is not None], fixed, info)


# ------------------------------------------------------------------ main

def improve(tools, level: str, preset: str = "full") -> Improved:
    """tools: an AgentTools over the DJ's (unchanged) draft."""
    if level not in LEVELS:
        raise ValueError(f"unknown level {level}")
    base: SetDraft = tools.draft
    lib, anlz, curve, cfg = tools.lib, tools.anlz, tools.curve, tools.cfg
    ids0 = [e.track_id for e in base.tracks]
    info = {tid: _info(lib, tid, anlz) for tid in ids0}
    fixed = {i for i, e in enumerate(base.tracks) if _fixed(e)}
    out = Improved(level, base.name, list(ids0))
    out.before = _metrics(base, lib, anlz, curve, info)
    if not ids0:
        out.note = "empty playlist"
        return out

    if level == "bold":
        ids = rebuild(ids0, fixed, info, curve, len(ids0))
    else:
        ids = smooth(ids0, fixed, info, max_swaps=light_cap(len(ids0)))

    if level in ("standard", "bold"):
        ids = _fit(tools, base, ids, info, preset, cfg)

    out.track_ids = ids
    d_after = draft_with(base, ids, lib, preset, cfg)
    for tid in ids:
        if tid not in info:
            info[tid] = _info(lib, tid, anlz)
    out.after = _metrics(d_after, lib, anlz, curve, info)
    out.changes = _diff(ids0, ids, tools, info)
    if out.unchanged:
        out.note = "nothing to fix"
    return out


def _fit(tools, base: SetDraft, ids: list[str], info: dict, preset: str, cfg: dict) -> list[str]:
    from setagent.agent.fillplan import plan_fill
    from setagent.agent.tools import AgentTools
    lib, anlz, curve = tools.lib, tools.anlz, tools.curve
    d = draft_with(base, ids, lib, preset, cfg)
    tl = compute(d, lib)
    if tl.delta_s is None:
        return ids
    tol = tl.tolerance_s
    # over: drop what the set misses least, re-ranking after each drop
    guard = 0
    while tl.delta_s > tol and guard < len(ids):
        guard += 1
        cands = removal_candidates(d, lib, anlz, curve, tl)
        if not cands:
            break
        c = cands[0]
        d.tracks.pop(c.index)
        tl = compute(d, lib)
    # under: fill from the library, chained by BPM/key (and the DJ's own history)
    if tl.delta_s < -tol:
        t2 = AgentTools(draft=d, lib=lib, anlz=anlz, curve=curve, cfg=cfg)
        t2._history, t2._history_db = tools._history, tools._history_db
        plan = plan_fill(t2, per_section_limit=40)
        for p in sorted(plan.picks, key=lambda p: p.at_index):
            d.tracks.insert(min(p.at_index, len(d.tracks)), TrackEntry(p.track_id, preset=preset))
            info.setdefault(p.track_id, _info(lib, p.track_id, anlz))
    return [e.track_id for e in d.tracks]


def _diff(old: list[str], new: list[str], tools, info: dict) -> list[Change]:
    title = tools.title_of
    out: list[Change] = []
    so, sn = set(old), set(new)
    for tid in new:
        if tid not in so:
            i = new.index(tid)
            prev = new[i - 1] if i > 0 else None
            why = []
            if prev is not None:
                kd = key_distance(info[prev][1], info[tid][1])
                if kd is not None and kd <= 1:
                    why.append("key match")
                bp, bt = info[prev][0], info[tid][0]
                if bp and bt and abs(bp - bt) / bp <= 0.03:
                    why.append("bpm close")
                times = tools.followers(prev).get(tid, 0) if hasattr(tools, "followers") else 0
                if times:
                    why.append(f"played after prev ×{times}")
            out.append(Change("add", tid, title(tid), f"#{i + 1} · " + " · ".join(why) if why else f"#{i + 1}"))
    for tid in old:
        if tid not in sn:
            out.append(Change("remove", tid, title(tid), ""))
    kept_old = [t for t in old if t in sn]
    kept_new = [t for t in new if t in so]
    if kept_old != kept_new:
        # a track "moved" only if it is outside the longest run that kept its
        # relative order -- one swap is two moves, not half the playlist
        pos_old = {t: i for i, t in enumerate(kept_old)}
        stay = _lis([pos_old[t] for t in kept_new])
        for i, t in enumerate(kept_new):
            if i not in stay:
                out.append(Change("move", t, title(t), f"#{old.index(t) + 1} → #{new.index(t) + 1}"))
    return out


def _lis(seq: list[int]) -> set[int]:
    """Indexes into `seq` of one longest increasing subsequence."""
    import bisect
    tails, tails_i, prev = [], [], [-1] * len(seq)
    for i, v in enumerate(seq):
        k = bisect.bisect_left(tails, v)
        if k == len(tails):
            tails.append(v); tails_i.append(i)
        else:
            tails[k] = v; tails_i[k] = i
        prev[i] = tails_i[k - 1] if k > 0 else -1
    out, i = set(), (tails_i[-1] if tails_i else -1)
    while i != -1:
        out.add(i)
        i = prev[i]
    return out


def from_track_ids(tools, ids: list[str], level: str = "agent", preset: str = "full") -> Improved:
    """Wrap any track list (e.g. an agent proposal) as an improved version."""
    base = tools.draft
    lib, anlz, curve, cfg = tools.lib, tools.anlz, tools.curve, tools.cfg
    ids0 = [e.track_id for e in base.tracks]
    info = {t: _info(lib, t, anlz) for t in set(ids0) | set(ids)}
    out = Improved(level, base.name, list(ids))
    out.before = _metrics(base, lib, anlz, curve, info)
    out.after = _metrics(draft_with(base, ids, lib, preset, cfg), lib, anlz, curve, info)
    out.changes = _diff(ids0, ids, tools, info)
    return out
