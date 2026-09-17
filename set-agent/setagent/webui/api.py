"""The JS <-> Python bridge (pywebview js_api).

Every method returns a plain dict and never raises into the view: on a failure it
returns {"error": ...} with a sentence the DJ can act on. The first run on someone
else's PC is the case that matters -- it must say what it could not find and what
to do next, not disappear.

Editing still goes through Command/History, exactly as the Canvas UI did.
"""
from __future__ import annotations

import io

import base64

import functools
import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from setagent.agent.advisor import Advisor, Intervention
from setagent.agent.changeset import ProposalLog
from setagent.agent.llm import (LLMAgent, LLMConfig, cli_status, find_claude,
                                forget_cli_status, open_login_console)
from setagent.agent.tools import AgentTools
from setagent.analysis.curve import TEMPLATE_LABELS, TargetCurve, template
from setagent.analysis.phrases import PRESET_CONFIG, preset_range
from setagent.analysis.removal import pick_removals, removal_candidates
from setagent.analysis.timing import fmt
from setagent.domain.draft import (History, LockedError, Move, SetBpmChange, SetDraft,
                                   SetLock, SetMilestone, SetRange, SetSetBpm,
                                   SetTargetLength, SetTempo, TrackEntry)
from setagent.rekordbox import xml_export
from setagent.rekordbox.library import (Library, LibraryNotFound, PhraseStatus,
                                        rekordbox_running)
from setagent.settings import Settings
from setagent.webui import state as viewstate

# pywebview dispatches each js_api call on its own thread, and the decrypted
# master.db is a SQLite connection that may only be used on the thread that
# created it. Rather than reach into setagent.rekordbox (out of scope for the UI
# work), every bridge call is funnelled onto one worker thread. The view stays
# responsive because the JS side is promise-based either way.
_SERIAL = ("boot", "load", "state", "select", "set_curve", "set_milestone",
           "set_preset", "set_range", "set_tempo", "set_lock", "move", "set_target",
           "undo", "redo", "rescan", "set_set_bpm", "set_bpm_change",
           "move_curve_point", "add_curve_point", "remove_curve_point",
           "export_preview", "export_xml", "llm_status", "set_llm",
           "agent_status", "set_level", "ask", "insert_candidate",
           "set_item_approved", "apply_pending", "reject_pending",
           "restart_rekordbox", "artwork")


def median_bpm(bpms) -> float | None:
    """The BPM a playlist is most naturally played at: the median of the tracks'
    own BPMs, rounded to a whole number. None when nothing has a BPM."""
    xs = sorted(b for b in bpms if b and b > 0)
    if not xs:
        return None
    n = len(xs)
    m = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    return float(round(m))


class Api:
    def __init__(self, playlist: str | None = None):
        self.lib: Library | None = None
        self._art_cache: dict[tuple[str, int], str] = {}
        self.want_playlist = playlist
        self.cfgfile = Settings.load()
        self.draft: SetDraft | None = None
        self.history: History | None = None
        self.anlz: dict = {}
        self.curve: TargetCurve | None = None
        self.curve_key: str | None = None
        self.cfg = dict(PRESET_CONFIG)
        self.preset = self.cfgfile.preset
        self.cap32 = self.cfgfile.cap32
        self.target_s = 60 * 60
        self.set_bpm: float | None = self._parse_bpm(self.cfgfile.set_bpm)
        # 2026-09-17 feedback: a set is almost never played at each track's own
        # BPM, so there is always a target BPM. Untyped = the playlist's median.
        self.set_bpm_auto: bool = self.set_bpm is None
        self.auto_bpm: float | None = None
        self.selected: int | None = None
        self.plog = ProposalLog()
        self.tools = None
        self.advisor = None
        self.agent = None
        self.pending = None
        self.cands: list[dict] = []
        self.chat: list[dict] = []
        self._last_notice: str | None = None

        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="setagent-api")
        self._worker = self._pool.submit(threading.current_thread).result()
        for name in _SERIAL:
            setattr(self, name, self._serialized(getattr(self, name)))

    def _serialized(self, fn):
        """Run fn on the one worker thread; pass straight through if already on it."""
        @functools.wraps(fn)
        def wrap(*a, **kw):
            if threading.current_thread() is self._worker:
                return fn(*a, **kw)          # re-entrant call from another api method
            return self._pool.submit(fn, *a, **kw).result()
        return wrap

    # ------------------------------------------------------------------ boot
    def boot(self) -> dict:
        """Open the library. The one call that is allowed to fail loudly."""
        try:
            self.lib = Library.open()
        except LibraryNotFound as e:
            return {"error": str(e), "kind": "library_not_found", "fatal": True}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}", "kind": "library_error",
                    "fatal": True, "detail": traceback.format_exc()}
        names = [p.name for p in self.lib.playlists()]
        want = self.want_playlist or self.cfgfile.playlist
        return {
            "playlists": names,
            "playlist": want if want in names else (names[0] if names else None),
            "presets": list(viewstate.PRESET_LABELS),
            "preset_labels": dict(viewstate.PRESET_LABELS),
            "preset_help": dict(viewstate.PRESET_HELP),
            "curves": [{"key": k, "label": v} for k, v in TEMPLATE_LABELS.items()],
            "preset": self.preset,
            "cap32": self.cap32,
            "target_s": self.target_s,
            "set_bpm": self.set_bpm,
            "rekordbox_running": rekordbox_running(),
        }

    # ------------------------------------------------------------------ load
    def load(self, opts: dict | None = None) -> dict:
        opts = opts or {}
        if not self.lib:
            return {"error": "ライブラリが開かれていません"}
        try:
            return self._load(opts)
        except Exception as e:
            return {"error": f"読み込みに失敗した: {type(e).__name__}: {e}",
                    "fatal": True, "detail": traceback.format_exc()}

    def _load(self, opts: dict) -> dict:
        name = opts.get("playlist") or self.cfgfile.playlist
        self.preset = opts.get("preset", self.preset)
        self.cap32 = bool(opts.get("cap32", self.cap32))
        self.target_s = int(opts.get("target_s", self.target_s))

        pls = {p.name: p for p in self.lib.playlists()}
        if name not in pls:
            return {"error": f"プレイリスト「{name}」が見つかりません",
                    "playlists": sorted(pls)}
        pl = pls[name]

        d = SetDraft(name=pl.name, tracks=[TrackEntry(i) for i in pl.track_ids])
        h = History(d)
        h.run(SetTargetLength(self.target_s, 60))
        self.auto_bpm = median_bpm(self.lib.track(i).bpm for i in pl.track_ids)
        if self.set_bpm_auto:
            self.set_bpm = self.auto_bpm
        if self.set_bpm:
            h.run(SetSetBpm(self.set_bpm))

        cfg = dict(PRESET_CONFIG)
        if self.cap32:
            cfg["max_drop_bars"] = 32
        self.cfg = cfg

        self.anlz = {}
        for e in d.tracks:
            ta = self.lib.analysis(e.track_id)
            if ta.anlz:
                self.anlz[e.track_id] = ta.anlz
            if self.preset != "full" and ta.phrase_status is PhraseStatus.PRESENT and ta.anlz:
                r = preset_range(ta.anlz, self.preset, cfg)
                if r:
                    h.run(SetRange(e.track_id, r.play_in_ms, r.play_out_ms, self.preset))

        self.draft, self.history, self.selected = d, h, None
        # Loading itself runs commands (target length, preset ranges). "Edited"
        # means the DJ moved the history away from that point, either way.
        self._done_base = len(h._done)

        # The agent boundary is unchanged: it gets tools and an advisor, and can
        # only emit a Change Set. It never touches the draft.
        self.tools = AgentTools(draft=d, lib=self.lib, anlz=self.anlz,
                                curve=self.curve, cfg=cfg)
        try:
            level = Intervention(self.cfgfile.level)
        except ValueError:
            level = Intervention.PASSIVE
        self.advisor = Advisor(self.tools, log=self.plog, level=level)
        self.plog = self.advisor.log
        self.agent = LLMAgent(self.tools, self.advisor, cfg=self.llm_config())
        self.pending = None
        self._last_notice = None

        self._save_settings(pl.name)
        return self.state()

    # ----------------------------------------------------------------- state
    def state(self) -> dict:
        if not self.draft:
            return {"error": "セットが読み込まれていません"}
        try:
            s = viewstate.build(self.draft, self.lib, self.anlz,
                                curve=self.curve, cfg=self.cfg, selected=self.selected)
            s["curve_key"] = self.curve_key
            s["curve_edited"] = bool(self.curve and self.curve.name == "custom"
                                     and self.curve_key)
            s["preset"] = self.preset
            s["cap32"] = self.cap32
            s["set_bpm_auto"] = self.set_bpm_auto
            s["auto_bpm"] = self.auto_bpm
            if self.tools:                       # keep the agent's view in step
                self.tools.curve = self.curve
                self.tools.anlz = self.anlz
            self._pump_notices()
            s["agent"] = self._agent_block()
            s["reco"] = self._reco_block(s)
            return s
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}", "detail": traceback.format_exc()}

    # The list under the hero (2026-09-16 review): not the playlist -- rekordbox
    # already shows that next door -- but what to do about the gap. Over the
    # target: the DJ's own tracks ranked by how little the set would miss them
    # (analysis.removal). Under it: real tracks from outside the playlist that
    # fit the hole (agent.recommend). Both are the same engines the agent uses;
    # nothing here invents a number or a title.
    def _reco_block(self, s: dict) -> dict:
        d, tol = s.get("delta_s"), s.get("tolerance_s") or 0
        if d is None or not self.draft or not self.tools:
            return {"kind": "none", "items": []}
        try:
            if d > tol:
                cands = removal_candidates(self.draft, self.lib, self.anlz, self.curve)
                picked = pick_removals(cands, d)
                items, cum = [], 0.0
                for c in (picked or cands[:12]):
                    cum += c.saves_s
                    items.append({"i": c.index, "track_id": c.track_id, "title": c.title,
                                  "saves_s": round(c.saves_s, 2),
                                  "after_s": round(s["total_s"] - cum, 2),
                                  "reasons": list(c.reasons)})
                return {"kind": "remove", "enough": bool(picked), "need_s": round(d, 2),
                        "items": items}
            if d < -tol:
                need = -d
                # a hole shorter than a track still takes a whole track to fill
                avg = s["total_s"] / max(len(s.get("tracks") or ()), 1)
                slot = max(need, avg)
                items = self.tools.recommend_candidates(
                    fmt(slot), after_index=len(self.draft.tracks) - 1, limit=12)
                return {"kind": "add", "need_s": round(need, 2), "slot_s": round(slot, 2),
                        "items": items}
        except Exception:
            return {"kind": "none", "items": []}       # the list is advice, never a crash
        return {"kind": "ok", "items": []}

    # ----------------------------------------------------------- interaction
    def select(self, index) -> dict:
        self.selected = None if index is None else int(index)
        return {"selected": self.selected}

    def set_curve(self, key) -> dict:
        self.curve_key = key or None
        self.curve = template(key) if key else None
        return self.state()

    # The target curve is the DJ's intent, not part of the Draft, so it does not
    # go through History -- same as the Canvas UI did it.
    def move_curve_point(self, index, pos, energy) -> dict:
        if not self.curve:
            return {"error": "先に目標カーブを選んでください"}
        try:
            self.curve.move_point(int(index), float(pos), float(energy))
        except IndexError:
            return {"error": "その制御点は無い"}
        return self.state()

    def add_curve_point(self, pos, energy) -> dict:
        if not self.curve:
            return {"error": "先に目標カーブを選んでください"}
        self.curve.add_point(float(pos), float(energy))
        return self.state()

    def remove_curve_point(self, index) -> dict:
        if not self.curve:
            return {"error": "先に目標カーブを選んでください"}
        n = len(self.curve.points)
        self.curve.remove_point(int(index))
        if len(self.curve.points) == n:
            return {**self.state(), "notice": "両端の点は削除できません"}
        return self.state()

    def set_milestone(self, index, at_s) -> dict:
        """at_s: None = not a milestone; negative = milestone without a target
        time (the DJ marks the anchor first, times it later); else the target."""
        target = None if at_s is None or int(at_s) < 0 else int(at_s)
        return self._run(lambda e: SetMilestone(e.track_id, at_s is not None, target), index)

    def set_preset(self, index, name) -> dict:
        if not self.draft:
            return {"error": "セットが読み込まれていません"}
        e = self.draft.tracks[int(index)]
        if name == "full":
            return self._run(lambda _e: SetRange(_e.track_id, 0, None, "full"), index)
        ta = self.lib.analysis(e.track_id)
        if ta.phrase_status is not PhraseStatus.PRESENT or not ta.anlz:
            return {"error": "フレーズ解析がないためプリセットを適用できません", **self.state()}
        r = preset_range(ta.anlz, name, self.cfg)
        if not r:
            return {"error": f"{name} に合うドロップが見つかりません", **self.state()}
        return self._run(lambda _e: SetRange(_e.track_id, r.play_in_ms, r.play_out_ms, name), index)

    def set_range(self, index, play_in_ms, play_out_ms) -> dict:
        """Hand-trimmed play range (the edge drag). Marked 'custom', not a preset."""
        if not self.draft:
            return {"error": "セットが読み込まれていません"}
        try:
            e = self.draft.tracks[int(index)]
            src_len_ms = int((getattr(self.lib.track(e.track_id), "length_s", 0) or 0) * 1000)
        except (IndexError, TypeError, ValueError):
            return {"error": "その曲は見つかりません"}
        lo = max(0, int(play_in_ms))
        hi = None if play_out_ms is None else int(play_out_ms)
        if src_len_ms:
            lo = min(lo, src_len_ms - 1000)
            if hi is not None:
                hi = min(hi, src_len_ms)
        if hi is not None and hi - lo < 4000:        # keep a mixable minimum
            return {**self.state(), "notice": "再生範囲が短すぎる（4秒未満）"}
        return self._run(lambda _e: SetRange(_e.track_id, lo, hi, "custom"), index)

    def set_tempo(self, index, bpm) -> dict:
        v = None if bpm in (None, "") else float(bpm)
        return self._run(lambda e: SetTempo(e.track_id, v), index)

    def move(self, index, to) -> dict:
        # Move takes the track's id, not its position -- the id is what survives
        # the list being reordered under it.
        return self._run(lambda e: Move(e.track_id, int(to)), index)

    # ------------------------------------------------------------ set tempo
    # The set's BPM (2026-09-16 review). The prediction scales every track to
    # it unless the DJ typed a tempo for that track. Change points ("from this
    # track on, 170") ride on the track id, so reordering keeps them.
    @staticmethod
    def _parse_bpm(v) -> float | None:
        try:
            b = float(str(v).strip()) if v not in (None, "") else None
        except ValueError:
            return None
        return b if b and 40 <= b <= 300 else None

    def set_set_bpm(self, bpm) -> dict:
        """Empty means "back to automatic" (the playlist's median), never "each
        track at its own BPM" -- that is not how a set is played."""
        v = self._parse_bpm(bpm)
        if bpm not in (None, "") and v is None:
            return {**self.state(), "notice": "BPM は 40〜300 の数字で入力してください"}
        self.set_bpm_auto = v is None
        if v is None:
            v = self.auto_bpm
        self.set_bpm = v
        if not self.history:
            self._persist_set_bpm()
            return {"set_bpm": v}
        self.history.run(SetSetBpm(v))
        self._persist_set_bpm()
        return self.state()

    def _persist_set_bpm(self) -> None:
        """Remember the set BPM the draft actually has (undo can move it)."""
        v = self.draft.constraints.set_bpm if self.draft else self.set_bpm
        self.set_bpm = v
        if v is not None and self.auto_bpm is not None and v != self.auto_bpm:
            self.set_bpm_auto = False              # undo/redo landed on a typed value
        self.cfgfile.set_bpm = "" if (v is None or self.set_bpm_auto) else (
            str(int(v)) if v == int(v) else str(v))
        try:
            self.cfgfile.save()
        except Exception:
            pass

    def set_bpm_change(self, index, bpm) -> dict:
        v = None if bpm in (None, "") else self._parse_bpm(bpm)
        if bpm not in (None, "") and v is None:
            return {**self.state(), "notice": "BPM は 40〜300 の数字で入力してください"}
        return self._run(lambda e: SetBpmChange(e.track_id, v), index)

    def set_target(self, seconds) -> dict:
        self.target_s = int(seconds)
        if not self.history:
            return {"target_s": self.target_s}
        self.history.run(SetTargetLength(self.target_s, 60))
        return self.state()

    def undo(self) -> dict:
        if self.history and self.history.undo():
            self._persist_set_bpm()
            return self.state()
        return {**self.state(), "notice": "これ以上戻せません"}

    def redo(self) -> dict:
        if self.history and self.history.redo():
            self._persist_set_bpm()
            return self.state()
        return {**self.state(), "notice": "これ以上やり直せません"}

    # -------------------------------------------------------------- artwork
    # rekordbox keeps a JPEG per track under share/PIONEER/Artwork (ImagePath in
    # djmdContent). The page is served by pywebview's local HTTP server, so it
    # cannot load file:// images; thumbnails go over the bridge as data URLs,
    # downscaled here so 100 rows cost a few hundred KB, not 15 MB.
    def artwork(self, track_ids: list, size: int = 56) -> dict:
        if not self.lib:
            return {}
        out: dict[str, str] = {}
        for tid in track_ids:
            key = (str(tid), int(size))
            if key not in self._art_cache:
                self._art_cache[key] = self._thumb(str(tid), int(size))
            out[str(tid)] = self._art_cache[key]
        return out

    def _thumb(self, track_id: str, size: int) -> str:
        p = self.lib.artwork_path(track_id)
        if not p:
            return ""
        try:
            from PIL import Image, ImageOps
            with Image.open(p) as im:
                im = ImageOps.fit(im.convert("RGB"), (size, size), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=72, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            return ""                                   # a bad file is not worth a broken row

    def rescan(self) -> dict:
        if not self.lib:
            return {"error": "ライブラリが開かれていません"}
        self.lib.rescan()
        return self._load({"playlist": self.draft.name if self.draft else None})

    # ------------------------------------------------------ change detection
    # Read-only loop (2026-09-16): the DJ edits in rekordbox, Set Agent follows.
    # This is deliberately not on the worker thread -- it only stats two files
    # and must answer even while a long load is running. What it reports:
    #   db   -- master.db mtime/size. Changes when rekordbox exits (checkpoint).
    #   wal  -- master.db-wal mtime/size. Changes on every edit while rekordbox
    #           is open; the decrypter replays the WAL, so this is readable too.
    #   edited -- the DJ has un-undone edits in this app, which a reload would drop.
    def library_changed(self) -> dict:
        if not self.lib:
            return {"ready": False}
        mdb = self.lib.master_db
        try:
            st = mdb.stat()
            db_sig = f"{int(st.st_mtime)}:{st.st_size}"
        except OSError:
            db_sig = ""
        wal = mdb.with_name(mdb.name + "-wal")
        try:
            ws = wal.stat()
            wal_sig = f"{int(ws.st_mtime)}:{ws.st_size}"
        except OSError:
            wal_sig = ""
        edited = bool(self.history) and \
            len(getattr(self.history, "_done", ())) != getattr(self, "_done_base", 0)
        return {"ready": True, "db": db_sig, "wal": wal_sig, "edited": edited,
                "rekordbox_running": rekordbox_running()}

    def set_lock(self, index, target, on) -> dict:
        return self._run(lambda e: SetLock(e.track_id, target, bool(on)), index)

    # ---------------------------------------------------------- xml export
    def export_preview(self) -> dict:
        """What would actually land in rekordbox, before anything is written (S5-2)."""
        if not self.draft:
            return {"error": "セットが読み込まれていません"}
        try:
            p = xml_export.export_preview(self.draft, self.lib)
            return {"preview": p, "text": xml_export.describe_preview(p)}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}", "detail": traceback.format_exc()}

    def export_xml(self, path=None) -> dict:
        if not self.draft:
            return {"error": "セットが読み込まれていません"}
        if not path:
            path = self._ask_save_path()
        if not path:
            return {"notice": "書き出しを取りやめた"}
        try:
            xml, info = xml_export.build_xml(self.draft, self.lib,
                                             playlist_name=self.draft.name)
            out = Path(path)
            out.write_text(xml, encoding="utf-8")
            self.cfgfile.last_export_dir = str(out.parent)
            try:
                self.cfgfile.save()
            except Exception:
                pass
            return {"path": str(out), "info": info,
                    "notice": f"{out.name} に書き出した。rekordbox 側の取り込み手順はこのあと表示する"}
        except Exception as e:
            return {"error": f"書き出しに失敗した: {type(e).__name__}: {e}",
                    "detail": traceback.format_exc()}

    def _ask_save_path(self) -> str | None:
        w = getattr(self, "_window", None)
        if not w:
            return None
        try:
            import webview
            start = self.cfgfile.last_export_dir or str(Path.home())
            name = re.sub(r'[\\/:*?"<>|]', "_", self.draft.name or "SetAgent") + ".xml"
            r = w.create_file_dialog(webview.SAVE_DIALOG, directory=start,
                                     save_filename=name)
            if isinstance(r, str):
                return r
            return r[0] if r else None
        except Exception:
            return None

    def restart_rekordbox(self, force=False) -> dict:
        """Quit and relaunch rekordbox so it re-reads the exported XML at startup.

        Never forces past an unsaved-changes prompt on its own: force=True comes
        only from the UI's second, explicit confirm. Remembers the exe path for
        next time so a relaunch works even when rekordbox is currently closed.
        """
        from setagent.webui import rbrestart
        remembered = getattr(self.cfgfile, "rekordbox_exe", "") or None
        r = rbrestart.restart(remembered, force=bool(force))
        exe = r.get("exe")
        if exe and exe != remembered:
            try:
                self.cfgfile.rekordbox_exe = exe
                self.cfgfile.save()
            except Exception:
                pass
        return r

    # ----------------------------------------------------------------- llm
    def llm_config(self) -> LLMConfig:
        """Settings first, environment second. Neither is required: with no
        Claude Code sign-in and no key the deterministic Advisor answers."""
        cfg = LLMConfig.from_env()
        k = self.cfgfile.llm_key_plain()
        if k:
            cfg.api_key = k
        if self.cfgfile.llm_model:
            cfg.model = self.cfgfile.llm_model
        if self.cfgfile.llm_backend:
            cfg.backend = self.cfgfile.llm_backend
        if self.cfgfile.claude_exe:
            cfg.claude_exe = self.cfgfile.claude_exe
        return cfg

    def llm_status(self, refresh=False) -> dict:
        """How the agent will reach Claude: Claude Code sign-in (cli), API key
        (api), or neither (advisor). `refresh` re-runs `claude auth status`."""
        cfg = self.llm_config()
        exe = find_claude(cfg.claude_exe) if cfg.backend in ("auto", "cli") else ""
        cli = cli_status([exe], refresh=bool(refresh)) if exe else {
            "found": False, "logged_in": False, "subscription": "", "org": "",
            "version": "", "error": "", "exe": ""}
        if cfg.backend == "off":
            mode = "advisor"
        elif cli["logged_in"] and cfg.backend in ("auto", "cli"):
            mode = "cli"
        elif cfg.available and cfg.backend in ("auto", "api"):
            mode = "api"
        else:
            mode = "advisor"
        from_settings = bool(self.cfgfile.llm_key_plain())
        stored = ("dpapi" if self.cfgfile.llm_key.startswith("dpapi:")
                  else "plain" if self.cfgfile.llm_key else "")
        return {
            "mode": mode,
            "backend": cfg.backend,
            "cli": cli,
            "configured": bool(cfg.api_key),
            "source": "settings" if from_settings else ("env" if cfg.api_key else ""),
            "stored": stored,
            "model": cfg.model,
            "cli_model": cfg.cli_model,
            "api_model": cfg.api_model,
            "masked": (cfg.api_key[:7] + "…" + cfg.api_key[-4:]) if len(cfg.api_key) > 14 else "",
            "status": self.agent.status() if self.agent else "",
            # The invariant, stated where the DJ can read it (spec B-7).
            "note": "Claude に接続できなくても全機能が動きます。そのときは決定的アドバイザで動作します",
        }

    def set_llm(self, key=None, model=None, backend=None, claude_exe=None) -> dict:
        how = self.cfgfile.set_llm_key(key) if key is not None else None
        if model is not None:
            self.cfgfile.llm_model = (model or "").strip()
        if backend is not None:
            self.cfgfile.llm_backend = (backend or "").strip()
        if claude_exe is not None:
            self.cfgfile.claude_exe = (claude_exe or "").strip()
        saved = self.cfgfile.save()
        forget_cli_status()
        if self.agent:                                  # pick the new backend up at once
            self.agent = LLMAgent(self.tools, self.advisor, cfg=self.llm_config())
        s = self.llm_status()
        s["saved"] = saved
        if how == "plain":
            s["warning"] = ("この PC では暗号化できませんでした（DPAPI が使えません）。"
                            "キーは settings.json に平文で保存されます")
        if not saved:
            s["warning"] = "設定ファイルに書き込めませんでした。次回起動時には残りません"
        return s

    # Not on the worker thread: it only starts a console for the DJ to sign in.
    def claude_login(self) -> dict:
        cfg = self.llm_config()
        exe = find_claude(cfg.claude_exe)
        if not exe:
            return {"ok": False, "error": "Claude Code が見つかりません。Claude Desktop をインストールしてください"}
        forget_cli_status()
        ok = open_login_console([exe])
        return {"ok": ok, "error": "" if ok else "ログイン用のコンソールを開けませんでした"}

    # --------------------------------------------------------------- agent
    # The boundary from spec B-8 is intact here: the agent proposes a Change Set,
    # the DJ ticks what they want, and only then does it go through History.
    def _agent_block(self) -> dict:
        if not self.agent:
            return {"ready": False}
        cs = self.pending
        ghost = None
        if cs:
            try:
                tl = cs.preview(self.draft, self.lib)
                ghost = {"total_s": round(tl.total_s, 2),
                         "tracks": [{"start_s": round(p.start_s, 2),
                                     "end_s": round(p.end_s, 2),
                                     "title": p.title} for p in tl.placements]}
            except Exception:
                ghost = None                      # a bad preview must not break the view
        return {
            "ready": True,
            "status": self.agent.status(),
            "level": self.advisor.level.value,
            "levels": [i.value for i in Intervention],
            "chat": self.chat[-60:],
            "candidates": self.cands,
            "log": self.plog.summary() if self.plog.proposed else "",
            "pending": None if not cs else {
                "title": cs.title,
                "reason": cs.reason,
                "items": [{"i": n, "text": it.op.describe(self.tools.title_of),
                           "approved": it.approved}
                          for n, it in enumerate(cs.items)],
                "diff": list(cs.diff_lines),
            },
            "ghost": ghost,
        }

    def _say(self, who: str, text: str) -> None:
        self.chat.append({"who": who, "text": text})

    def _pump_notices(self) -> None:
        """B-10: at most one unsolicited notice per turn, and only when asked for
        by the intervention level. Silent at 'off' and 'passive'."""
        if not self.advisor or self.advisor.level is not Intervention.PROACTIVE:
            return
        try:
            notices = self.advisor.notices()
        except Exception:
            return
        for n in notices[:1]:
            if n != self._last_notice:
                self._last_notice = n
                self._say("meta", f"[気づいたこと] {n}")

    def agent_status(self) -> dict:
        return self._agent_block()

    def set_level(self, level) -> dict:
        if not self.advisor:
            return {"error": "セットが読み込まれていません"}
        try:
            self.advisor.level = Intervention(level)
        except ValueError:
            return {"error": f"未知の介入度 '{level}'"}
        self.cfgfile.level = self.advisor.level.value
        try:
            self.cfgfile.save()
        except Exception:
            pass
        return self.state()

    def ask(self, text) -> dict:
        if not self.agent:
            return {"error": "セットが読み込まれていません"}
        text = (text or "").strip()
        if not text:
            return self.state()
        self._say("you", text)
        if self.selected is not None:
            try:
                t = self.draft.tracks[self.selected]
                self._say("meta", f"文脈: {self.selected + 1}. {self.lib.track(t.track_id).title}")
            except Exception:
                pass
        try:
            reply = self.agent.ask(text, self.selected)
        except Exception as e:
            self._say("meta", f"エージェントが落ちた: {type(e).__name__}: {e}")
            return self.state()
        self._say("agent", reply.text)
        if reply.used_tools:
            self._say("meta", "tools: " + ", ".join(dict.fromkeys(reply.used_tools)))
        self.cands = reply.candidates or []
        if reply.change_set:
            self.pending = reply.change_set
        return self.state()

    def insert_candidate(self, track_id, at=None) -> dict:
        if not self.advisor:
            return {"error": "セットが読み込まれていません"}
        if at is None:
            at = (self.selected + 1) if self.selected is not None else len(self.draft.tracks)
        try:
            r = self.advisor.insert_candidate(track_id, int(at))
        except Exception as e:
            return {**self.state(), "error": f"{type(e).__name__}: {e}"}
        self._say("agent", r.text)
        self.pending = r.change_set
        return self.state()

    def set_item_approved(self, index, approved) -> dict:
        if not self.pending:
            return {"error": "提案がありません"}
        try:
            self.pending.items[int(index)].approved = bool(approved)
        except (IndexError, TypeError, ValueError):
            return {"error": "その項目は見つかりません"}
        return self.state()

    def apply_pending(self) -> dict:
        cs = self.pending
        if not cs:
            return {"error": "提案がありません"}
        cmds = cs.approved_commands()
        if not cmds:
            return {**self.state(), "notice": "承認された操作がありません"}
        try:
            self.history.run_all(cmds)
        except LockedError as ex:
            return {**self.state(), "notice": f"適用できない（ロック: {ex}）"}
        except Exception as e:
            return {**self.state(), "error": f"{type(e).__name__}: {e}"}
        self.plog.record_outcome(cs)
        self.pending = None
        self._say("meta", f"適用しました（{len(cmds)}件）。「元に戻す」で戻せます")
        return self.state()

    def reject_pending(self) -> dict:
        cs = self.pending
        if not cs:
            return {"error": "提案がありません"}
        for i in cs.items:
            i.approved = False
        self.plog.record_outcome(cs)
        self.pending = None
        self._say("meta", "却下しました。同じ案は出しません")
        return self.state()

    # --------------------------------------------------------------- helpers
    def _run(self, make_cmd, index) -> dict:
        if not self.draft or not self.history:
            return {"error": "セットが読み込まれていません"}
        try:
            e = self.draft.tracks[int(index)]
        except (IndexError, TypeError, ValueError):
            return {"error": "その曲は見つかりません"}
        try:
            self.history.run(make_cmd(e))
        except LockedError as ex:
            return {**self.state(), "notice": f"ロックされているため変更できない: {ex}"}
        except Exception as ex:
            return {**self.state(), "error": f"{type(ex).__name__}: {ex}"}
        return self.state()

    def _save_settings(self, playlist: str) -> None:
        try:                                   # best-effort: never block the app
            self.cfgfile.playlist = playlist
            self.cfgfile.preset = self.preset
            self.cfgfile.cap32 = self.cap32
            self.cfgfile.save()
        except Exception:
            pass
