"""The agent's tool surface (spec E-6).

Every tool returns plain JSON-able data. Ten of the eleven are read-only; the
last one, `set.propose_changes`, builds a Change Set and hands it to the user —
it never applies anything. An LLM that can only call these tools cannot make up
a number and cannot edit the set behind the DJ's back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from setagent.agent.changeset import ChangeSet, Proposal, Rejected, build_change_set
from setagent.agent.recommend import Slot, candidates
from setagent.analysis.curve import TargetCurve, deviation, flat_segments
from setagent.analysis.energy import set_energy_curve
from setagent.analysis.phrases import PRESET_CONFIG, blocks, preset_range
from setagent.analysis.sections import milestones, sections
from setagent.analysis.timing import compute, fmt, simulate, trim_candidates
from setagent.domain.draft import SetDraft
from setagent.rekordbox.library import PhraseStatus


@dataclass
class AgentTools:
    draft: SetDraft
    lib: Any
    anlz: dict = field(default_factory=dict)
    curve: TargetCurve | None = None
    cfg: dict = field(default_factory=lambda: dict(PRESET_CONFIG))
    on_proposal: Callable[[ChangeSet], None] | None = None

    # -------------------------------------------------------------- helpers
    def _timeline(self):
        return compute(self.draft, self.lib)

    def _points(self, tl=None):
        return set_energy_curve(tl or self._timeline(), self.anlz)

    def title_of(self, ref: str) -> str:
        try:
            return self.lib.track(ref).title
        except Exception:
            try:
                return self.lib.track(self.draft.tracks[self.draft.find(ref)].track_id).title
            except Exception:
                return ref

    # ---------------------------------------------------------------- tools
    def get_draft(self) -> dict:
        """set.get_draft — the editable state, as the DJ left it."""
        return {
            "name": self.draft.name,
            "constraints": {
                "target_length": fmt(self.draft.constraints.target_length_s)
                if self.draft.constraints.target_length_s else None,
                "tolerance_s": self.draft.constraints.tolerance_s,
                "default_overlap_bars": self.draft.constraints.default_overlap_bars,
            },
            "tracks": [{
                "index": i, "track_id": e.track_id, "title": self.title_of(e.track_id),
                "preset": e.preset, "tempo": e.tempo,
                "play_in_ms": e.play_in_ms, "play_out_ms": e.play_out_ms,
                "is_milestone": e.is_milestone,
                "target_time": fmt(e.target_time_s) if e.target_time_s is not None else None,
                "locks": sorted(e.locks),
            } for i, e in enumerate(self.draft.tracks)],
        }

    def get_set_summary(self) -> dict:
        """analysis.get_set_summary — total, slack, per-track clock, peak, warnings."""
        tl = self._timeline()
        pts = self._points(tl)
        known = [p for p in pts if p.known]
        peak = max(known, key=lambda p: p.energy) if known else None
        return {
            "total": fmt(tl.total_s),
            "total_s": round(tl.total_s, 1),
            "target": fmt(tl.target_s) if tl.target_s else None,
            "delta": fmt(tl.delta_s) if tl.delta_s is not None else None,
            "within_target": tl.within_target,
            "peak_at": fmt(peak.time_s) if peak else None,
            "phrase_coverage": f"{len(known)}/{len(pts)} sample points have phrase data",
            "warnings": list(tl.warnings),
            "tracks": [{
                "index": p.index, "title": p.title, "start": fmt(p.start_s), "end": fmt(p.end_s),
                "play": fmt(p.play_s), "bpm": round(p.original_bpm, 1),
                "set_tempo": round(p.set_tempo, 1), "warnings": list(p.warnings),
            } for p in tl.placements],
        }

    def get_energy_curve(self, resolution_s: int = 60) -> dict:
        """analysis.get_energy_curve — measured vs intended, and where they part."""
        tl = self._timeline()
        pts = self._points(tl)
        total = max(tl.total_s, 1.0)
        sampled = []
        t = 0.0
        while t <= total:
            near = min(pts, key=lambda p: abs(p.time_s - t)) if pts else None
            sampled.append({
                "at": fmt(t),
                "actual": round(near.energy, 2) if near and near.known else None,
                "target": round(self.curve.at_time(t, total), 2) if self.curve else None,
            })
            t += resolution_s
        return {
            "resolution_s": resolution_s,
            "has_target_curve": self.curve is not None,
            "points": sampled,
            "deviation": [{"from": fmt(s.start_s), "to": fmt(s.end_s), "kind": s.kind,
                           "amount": round(s.value, 2)}
                          for s in (deviation(pts, self.curve, total) if self.curve else [])],
            "flat": [{"from": fmt(s.start_s), "to": fmt(s.end_s), "range": round(s.value, 2)}
                     for s in flat_segments(pts)],
        }

    def get_sections(self) -> dict:
        """analysis.get_sections — the budget between milestones."""
        tl = self._timeline()
        return {
            "milestones": [{"index": m.index, "title": m.title, "at": fmt(m.actual_s),
                            "target": fmt(m.target_s) if m.target_s is not None else None,
                            "delta": fmt(m.delta_s) if m.delta_s is not None else None}
                           for m in milestones(self.draft, tl)],
            "sections": [{"index": s.index, "from": s.start_title, "to": s.end_title or "END",
                          "tracks": s.track_count, "actual": fmt(s.actual_s),
                          "target": fmt(s.target_s) if s.target_s is not None else None,
                          "delta": fmt(s.delta_s) if s.delta_s is not None else None,
                          "room_for_tracks": s.room_for_tracks}
                         for s in sections(self.draft, tl)],
        }

    def get_track_structure(self, track_ref: str) -> dict:
        """analysis.get_track_structure — phrases, BPM, key, and whether we know them."""
        idx = None
        try:
            idx = self.draft.find(track_ref)
            tid = self.draft.tracks[idx].track_id
        except Exception:
            tid = track_ref
        ta = self.lib.analysis(tid)
        t = ta.track
        out = {
            "track_id": t.id, "title": t.title, "artist": t.artist,
            "bpm": t.bpm, "key": t.key, "length": fmt(t.length_s),
            "index_in_set": idx,
            "phrase_status": ta.phrase_status.value,
            "note": ta.reason,
            "phrases": [],
        }
        if ta.phrase_status == PhraseStatus.PRESENT and ta.anlz and ta.anlz.structure:
            s = ta.anlz.structure
            out["phrases"] = [{"label": b.label, "start_bar": round(b.start_beat / 4, 1),
                               "bars": round(b.bars, 1)} for b in blocks(s.phrases, s.end_beat)]
        return out

    def simulate(self, operations: list[dict]) -> dict:
        """analysis.simulate — what-if. The draft is not touched."""
        try:
            p = Proposal.from_dict({"reason": "simulate", "operations": operations})
            cmds = [o.to_command() for o in p.operations]
        except Rejected as ex:
            return {"error": str(ex)}
        tl = simulate(self.draft, self.lib, cmds)
        before = self._timeline()
        return {
            "total_before": fmt(before.total_s), "total_after": fmt(tl.total_s),
            "delta_after": fmt(tl.delta_s) if tl.delta_s is not None else None,
            "within_target": tl.within_target,
            "warnings": list(tl.warnings),
        }

    def get_trim_candidates(self, limit: int = 8) -> list[dict]:
        """analysis.get_trim_candidates — where the time could come from."""
        presets = {}
        for e in self.draft.tracks:
            if e.preset == "one_drop":
                continue
            ta = self.lib.analysis(e.track_id)
            if ta.phrase_status == PhraseStatus.PRESENT and ta.anlz:
                r = preset_range(ta.anlz, "one_drop", self.cfg)
                if r:
                    presets[e.track_id] = (r.play_in_ms, r.play_out_ms)
        return [{"track_id": c.track_id, "title": c.title, "action": c.action,
                 "saves": fmt(c.saves_s)}
                for c in trim_candidates(self.draft, self.lib, presets)[:limit]]

    def search(self, text: str = "", bpm_min: float | None = None, bpm_max: float | None = None,
               key: str = "", playlist: str = "", limit: int = 20) -> list[dict]:
        """lib.search — the DJ's own library, nothing else."""
        ids = None
        if playlist:
            try:
                ids = list(self.lib.db.playlist_by_name(playlist).track_ids)
            except Exception:
                return []
        rows = [self.lib.track(i) for i in ids] if ids is not None else self.lib.db.tracks()
        text = text.lower()
        out = []
        for t in rows:
            if text and text not in t.title.lower() and text not in t.artist.lower():
                continue
            if bpm_min is not None and t.bpm < bpm_min: continue
            if bpm_max is not None and t.bpm > bpm_max: continue
            if key and t.key != key: continue
            out.append({"track_id": t.id, "title": t.title, "artist": t.artist,
                        "bpm": t.bpm, "key": t.key, "length": fmt(t.length_s),
                        "cloud": t.is_cloud})
            if len(out) >= limit:
                break
        return out

    def get_play_history(self, track_ref: str = "") -> dict:
        """lib.get_play_history — not wired up yet; says so rather than guessing."""
        return {"available": False,
                "note": "再生履歴はまだ読んでいない。共起統計は使えない"}

    def recommend_candidates(self, duration: str, target_energy: float | None = None,
                             after_index: int | None = None, playlist: str = "",
                             limit: int = 5) -> list[dict]:
        """recommend.candidates — real tracks that fit a gap (B-9 stage 1)."""
        from setagent.agent.changeset import parse_mmss
        secs = parse_mmss(duration) or 0
        bpm = key = None
        if after_index is not None and 0 <= after_index < len(self.draft.tracks):
            tl = self._timeline()
            prev = tl.placements[after_index]
            bpm = prev.set_tempo
            key = self.lib.track(prev.track_id).key
        pool = None
        if playlist:
            try:
                pool = list(self.lib.db.playlist_by_name(playlist).track_ids)
            except Exception:
                pool = None
        slot = Slot(duration_s=secs, target_energy=target_energy, bpm=bpm, key=key or "")
        used = {e.track_id for e in self.draft.tracks}
        return [{"track_id": c.track.id, "title": c.track.title, "artist": c.track.artist,
                 "bpm": c.track.bpm, "key": c.track.key, "in_slot": fmt(c.play_s),
                 "score": c.score, "reason": c.reason}
                for c in candidates(self.lib, slot, pool=pool, exclude=used, limit=limit)]

    def propose_changes(self, reason: str, operations: list[dict], title: str = "") -> dict:
        """set.propose_changes — build a Change Set and show it. Applies nothing."""
        try:
            p = Proposal.from_dict({"reason": reason, "operations": operations, "title": title})
            cs = build_change_set(self.draft, self.lib, self.anlz, p, self.curve)
        except Rejected as ex:
            return {"accepted": False, "reason": str(ex)}
        except Exception as ex:                        # malformed params from the model
            return {"accepted": False, "reason": f"提案を組み立てられない: {ex}"}
        if self.on_proposal:
            self.on_proposal(cs)
        return {"accepted": True, "diff": cs.diff_lines,
                "operations": [i.op.describe(self.title_of) for i in cs.items],
                "note": "ユーザーに提示した。適用するかはユーザーが決める"}

    # ------------------------------------------------------------ dispatch
    def call(self, name: str, args: dict | None = None) -> Any:
        args = args or {}
        fn = TOOL_DISPATCH.get(name)
        if fn is None:
            return {"error": f"unknown tool '{name}'"}
        try:
            return fn(self, **args)
        except TypeError as ex:
            return {"error": f"bad arguments for {name}: {ex}"}
        except Exception as ex:
            return {"error": f"{name} failed: {ex}"}


TOOL_DISPATCH: dict[str, Callable] = {
    "set.get_draft": AgentTools.get_draft,
    "analysis.get_set_summary": AgentTools.get_set_summary,
    "analysis.get_energy_curve": AgentTools.get_energy_curve,
    "analysis.get_sections": AgentTools.get_sections,
    "analysis.get_track_structure": AgentTools.get_track_structure,
    "analysis.simulate": AgentTools.simulate,
    "analysis.get_trim_candidates": AgentTools.get_trim_candidates,
    "lib.search": AgentTools.search,
    "lib.get_play_history": AgentTools.get_play_history,
    "recommend.candidates": AgentTools.recommend_candidates,
    "set.propose_changes": AgentTools.propose_changes,
}

# JSON schema for LLM tool-calling. Kept in one place so the prompt and the
# dispatch table cannot drift apart.
TOOL_SCHEMA: list[dict] = [
    {"name": "set.get_draft", "description": "現在の Set Draft（曲順・範囲・テンポ・ロック・マイルストーン・制約）",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "analysis.get_set_summary", "description": "推定総尺・目標との過不足・曲ごとの開始/終了・ピーク位置・警告",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "analysis.get_energy_curve", "description": "展開カーブの実測と目標、乖離区間と平坦区間",
     "input_schema": {"type": "object", "properties": {"resolution_s": {"type": "integer"}}}},
    {"name": "analysis.get_sections", "description": "マイルストーン間の区間ごとの目標/現在/過不足/入る余地",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "analysis.get_track_structure", "description": "曲のフレーズ構成・BPM・Key・解析の有無",
     "input_schema": {"type": "object", "properties": {"track_ref": {"type": "string"}},
                      "required": ["track_ref"]}},
    {"name": "analysis.simulate", "description": "仮の操作を当てたときの分析結果。Draft は変わらない",
     "input_schema": {"type": "object", "properties": {"operations": {"type": "array", "items": {"type": "object"}}},
                      "required": ["operations"]}},
    {"name": "analysis.get_trim_candidates", "description": "目標尺に収めるための削り代の候補",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "lib.search", "description": "ライブラリ検索（テキスト・BPM範囲・Key・プレイリスト）",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"}, "bpm_min": {"type": "number"}, "bpm_max": {"type": "number"},
         "key": {"type": "string"}, "playlist": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "lib.get_play_history", "description": "演奏履歴と共起統計（未実装。使えないと返る）",
     "input_schema": {"type": "object", "properties": {"track_ref": {"type": "string"}}}},
    {"name": "recommend.candidates", "description": "区間に合う実在曲の候補。曲名を作ってはいけない",
     "input_schema": {"type": "object", "properties": {
         "duration": {"type": "string", "description": "mm:ss"},
         "target_energy": {"type": "number"}, "after_index": {"type": "integer"},
         "playlist": {"type": "string"}, "limit": {"type": "integer"}},
         "required": ["duration"]}},
    {"name": "set.propose_changes", "description": "変更操作と理由から Change Set を作って提示する。適用はしない",
     "input_schema": {"type": "object", "properties": {
         "reason": {"type": "string"}, "title": {"type": "string"},
         "operations": {"type": "array", "items": {"type": "object"}}},
         "required": ["reason", "operations"]}},
]
