"""Set Agent — the set-making workbench (tkinter, one window, no LLM).

Covers stories S1-2/S1-4/S1-5/S1-6, S2-1..S2-7, S3-1..S3-6.

  TRACKS    blocks on a time axis; drag to reorder, drag an edge to trim
  SECTIONS  the budget between milestones: target / actual / slack / room
  ENERGY    the measured curve from phrase analysis, the DJ's target curve
            (draggable, four templates), drift bands and flat-stretch warnings

Every edit goes through a Command on the shared History, so Undo/Redo works the
same for a hand edit as it will for an agent proposal (spec B-8). Nothing here
calls an LLM; every number on screen comes from the analysis engines.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from setagent.agent.advisor import Advisor, Intervention
from setagent.agent.changeset import ChangeSet, ProposalLog
from setagent.agent.llm import LLMAgent
from setagent.agent.tools import AgentTools
from setagent.analysis.curve import (TEMPLATE_LABELS, TargetCurve, deviation,
                                     flat_segments, template)
from setagent.analysis.energy import set_energy_curve
from setagent.analysis.phrases import PRESET_CONFIG, preset_range
from setagent.analysis.sections import describe as describe_section
from setagent.analysis.sections import milestones, sections, skeleton
from setagent.analysis.timing import compute, fmt, simulate, trim_candidates
from setagent.domain.draft import (History, LockedError, Move, SetDraft, SetLock,
                                   SetMilestone, SetRange, SetTargetLength, SetTempo,
                                   TrackEntry)
from setagent.rekordbox.library import Library, LibraryNotFound, PhraseStatus
from setagent.settings import Settings

def _enable_dpi_awareness() -> None:
    """Windows: draw at the monitor's real pixel density.

    Without this the OS bitmap-stretches a 1280x800 render onto a 1920x1200
    screen (150% scaling, DPI 144): every glyph and every hairline comes out
    blurred, and the time axis silently loses a third of its resolution.
    Must run before the first Tk() exists, so it lives at import time.
    Best-effort -- a failure here must never stop the app from starting.
    """
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor aware
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()        # older Windows
    except Exception:
        pass                                                 # not Windows: fine


_enable_dpi_awareness()

BG = "#14171c"; PANEL = "#1c2128"; INK = "#e6edf3"; MUTE = "#8b949e"
GRID = "#2d333b"; ACCENT = "#58a6ff"; WARN = "#f0a35e"
PRESENT = "#3fb950"; ABSENT = "#6e7681"; TARGET = "#f778ba"
SEL = "#ffd866"; MILE = "#58a6ff"; OVER = "#8a4a2a"; UNDER = "#25415e"; FLAT = "#5a4a20"
PRESETS = ("full", "one_drop", "two_drop", "short")
EDGE_PX = 6          # grab zone for range trimming


class App(tk.Tk):
    def __init__(self, lib: Library, playlist: str | None = None):
        super().__init__()
        self.lib = lib
        self.want_playlist = playlist
        self.title("Set Agent — Workbench")
        self.geometry("1440x860"); self.configure(bg=BG)
        try: self.after(80, lambda: self.state("zoomed"))
        except Exception: pass

        self.cfgfile = Settings.load()
        self.target_s = 60 * 60
        self.preset = tk.StringVar(value=self.cfgfile.preset)
        self.cap = tk.BooleanVar(value=self.cfgfile.cap32)
        self.skeleton_only = tk.BooleanVar(value=False)
        self.curve = TargetCurve()
        self.sel: int | None = None
        self.drag: dict | None = None
        self.anlz: dict = {}
        self.history: History | None = None
        self.pending: ChangeSet | None = None
        self.cands: list[dict] = []
        self.plog = ProposalLog()
        self.status = tk.StringVar(value="")

        self._build_controls()
        body = tk.Frame(self, bg=BG); body.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self._build_inspector(body)
        tk.Label(self, textvariable=self.status, bg=BG, fg=MUTE, anchor="w",
                 font=("Segoe UI", 9)).pack(fill="x", padx=14, pady=(0, 8))

        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", self.on_double)
        self.canvas.bind("<Button-3>", self.on_right)
        self.bind("<Control-z>", lambda e: self.do_undo())
        self.bind("<Control-y>", lambda e: self.do_redo())
        self.bind("<Control-Z>", lambda e: self.do_redo())
        self.bind("m", lambda e: self.toggle_milestone())

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.curve_var.get() != "(none)":
            self.apply_template()

        self.playlists = [p for p in lib.playlists() if p.track_ids]
        if not self.playlists:
            self.status.set("プレイリストが1つも無い。rekordbox でプレイリストを作って Rescan しろ")
            return
        names = [f"{p.name} ({len(p.track_ids)})" for p in self.playlists]
        self.pl_combo["values"] = names
        wanted = playlist or self.cfgfile.playlist
        pick = next((i for i, p in enumerate(self.playlists) if wanted and p.name == wanted), None)
        if pick is None:
            pick = max(range(len(self.playlists)), key=lambda i: len(self.playlists[i].track_ids))
        self.pl_combo.current(pick)
        self.load()
        for w in getattr(lib, "warnings", []):
            self.warn_box.insert(0, f"! {w}")
            self.say("meta", f"[注意] {w}")

    # ------------------------------------------------------------- chrome
    def _build_controls(self):
        bar = tk.Frame(self, bg=PANEL); bar.pack(fill="x", padx=12, pady=(12, 8))

        def label(t, pad=(10, 4)):
            tk.Label(bar, text=t, bg=PANEL, fg=MUTE).pack(side="left", padx=pad)

        label("Playlist")
        self.pl_combo = ttk.Combobox(bar, width=20, state="readonly")
        self.pl_combo.pack(side="left"); self.pl_combo.bind("<<ComboboxSelected>>", lambda e: self.load())

        label("Target", (16, 4))
        self.target_entry = tk.Entry(bar, width=7, bg=BG, fg=INK, insertbackground=INK, relief="flat")
        self.target_entry.insert(0, self.cfgfile.target); self.target_entry.pack(side="left")
        self.target_entry.bind("<Return>", lambda e: self.load())

        label("Mix", (16, 4))
        pc = ttk.Combobox(bar, width=9, state="readonly", textvariable=self.preset, values=list(PRESETS))
        pc.pack(side="left"); pc.bind("<<ComboboxSelected>>", lambda e: self.load())
        tk.Checkbutton(bar, text="cap 32bar", variable=self.cap, bg=PANEL, fg=MUTE, selectcolor=BG,
                       activebackground=PANEL, activeforeground=INK, command=self.load).pack(side="left", padx=(10, 0))

        label("Curve", (16, 4))
        self.curve_var = tk.StringVar(value=self.cfgfile.curve)
        cc = ttk.Combobox(bar, width=16, state="readonly", textvariable=self.curve_var,
                          values=["(none)"] + [TEMPLATE_LABELS[k] for k in TEMPLATE_LABELS])
        cc.pack(side="left"); cc.bind("<<ComboboxSelected>>", lambda e: self.apply_template())

        tk.Checkbutton(bar, text="骨組みのみ", variable=self.skeleton_only, bg=PANEL, fg=MUTE, selectcolor=BG,
                       activebackground=PANEL, activeforeground=INK,
                       command=self.redraw).pack(side="left", padx=(16, 0))

        tk.Button(bar, text="Undo", command=self.do_undo, bg=PANEL, fg=INK, relief="flat",
                  activebackground=GRID).pack(side="left", padx=(16, 2))
        tk.Button(bar, text="Redo", command=self.do_redo, bg=PANEL, fg=INK, relief="flat",
                  activebackground=GRID).pack(side="left", padx=2)
        tk.Button(bar, text="Rescan", command=self.do_rescan, bg=PANEL, fg=INK, relief="flat",
                  activebackground=GRID).pack(side="left", padx=(10, 2))
        tk.Button(bar, text="XMLへ書き出し", command=self.export_xml, bg=PANEL, fg=ACCENT,
                  relief="flat", activebackground=GRID).pack(side="left", padx=2)

        self.readout = tk.Label(bar, text="", bg=PANEL, fg=INK, font=("Segoe UI", 12, "bold"))
        self.readout.pack(side="right", padx=12)

    def _build_inspector(self, parent):
        # The widest content here is a Consolas-9 line in SECTIONS / 警告.
        # Measure it instead of hard-coding 360px, so 100/125/150% scaling all
        # get a panel that fits its text rather than one that truncates it.
        import tkinter.font as tkfont
        col = tkfont.Font(family="Consolas", size=9).measure("0")
        outer = tk.Frame(parent, bg=PANEL, width=max(360, col * 56 + 48))
        outer.pack(side="right", fill="y", padx=(12, 0)); outer.pack_propagate(False)
        nb = ttk.Notebook(outer); nb.pack(fill="both", expand=True)
        p = tk.Frame(nb, bg=PANEL)
        agent = tk.Frame(nb, bg=PANEL)
        nb.add(p, text="セット"); nb.add(agent, text="エージェント")
        self.notebook = nb
        self._build_agent_tab(agent)

        def head(t):
            tk.Label(p, text=t, bg=PANEL, fg=MUTE, anchor="w",
                     font=("Segoe UI", 8, "bold")).pack(fill="x", padx=12, pady=(12, 4))

        head("SELECTED TRACK")
        self.sel_title = tk.Label(p, text="—", bg=PANEL, fg=INK, anchor="w", justify="left",
                                  wraplength=300, font=("Segoe UI", 10, "bold"))
        self.sel_title.pack(fill="x", padx=12)
        self.sel_meta = tk.Label(p, text="", bg=PANEL, fg=MUTE, anchor="w", justify="left",
                                 wraplength=300, font=("Segoe UI", 8))
        self.sel_meta.pack(fill="x", padx=12, pady=(2, 6))

        row = tk.Frame(p, bg=PANEL); row.pack(fill="x", padx=12, pady=2)
        tk.Label(row, text="Preset", bg=PANEL, fg=MUTE, width=8, anchor="w").pack(side="left")
        self.sel_preset = tk.StringVar(value="full")
        c = ttk.Combobox(row, width=10, state="readonly", textvariable=self.sel_preset, values=list(PRESETS))
        c.pack(side="left"); c.bind("<<ComboboxSelected>>", lambda e: self.apply_track_preset())

        row = tk.Frame(p, bg=PANEL); row.pack(fill="x", padx=12, pady=2)
        tk.Label(row, text="Tempo", bg=PANEL, fg=MUTE, width=8, anchor="w").pack(side="left")
        self.sel_tempo = tk.Entry(row, width=8, bg=BG, fg=INK, insertbackground=INK, relief="flat")
        self.sel_tempo.pack(side="left"); self.sel_tempo.bind("<Return>", lambda e: self.apply_tempo())

        self.sel_mile = tk.BooleanVar(value=False)
        row = tk.Frame(p, bg=PANEL); row.pack(fill="x", padx=12, pady=2)
        tk.Checkbutton(row, text="マイルストーン", variable=self.sel_mile, bg=PANEL, fg=INK, selectcolor=BG,
                       activebackground=PANEL, activeforeground=INK,
                       command=self.apply_milestone).pack(side="left")
        tk.Label(row, text="目標", bg=PANEL, fg=MUTE).pack(side="left", padx=(10, 4))
        self.sel_mtime = tk.Entry(row, width=7, bg=BG, fg=INK, insertbackground=INK, relief="flat")
        self.sel_mtime.pack(side="left"); self.sel_mtime.bind("<Return>", lambda e: self.apply_milestone())

        row = tk.Frame(p, bg=PANEL); row.pack(fill="x", padx=12, pady=(2, 8))
        tk.Label(row, text="Lock", bg=PANEL, fg=MUTE, width=8, anchor="w").pack(side="left")
        self.locks = {}
        for t in ("position", "range", "tempo"):
            v = tk.BooleanVar(value=False); self.locks[t] = v
            tk.Checkbutton(row, text=t[:3], variable=v, bg=PANEL, fg=MUTE, selectcolor=BG,
                           activebackground=PANEL, activeforeground=INK,
                           command=lambda tt=t: self.apply_lock(tt)).pack(side="left")

        head("SECTIONS (骨組み)")
        self.sections_box = tk.Listbox(p, bg=BG, fg=INK, height=7, relief="flat",
                                       highlightthickness=0, selectbackground=GRID,
                                       font=("Consolas", 8))
        self.sections_box.pack(fill="x", padx=12)

        head("削り代候補 (what-if)")
        self.trim_box = tk.Listbox(p, bg=BG, fg=INK, height=7, relief="flat",
                                   highlightthickness=0, selectbackground=GRID,
                                   font=("Consolas", 8))
        self.trim_box.pack(fill="x", padx=12)
        self.trim_box.bind("<Double-Button-1>", lambda e: self.apply_trim())
        tk.Label(p, text="ダブルクリックで適用（Ctrl+Zで戻る）", bg=PANEL, fg=MUTE,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(2, 0))

        head("警告")
        self.warn_box = tk.Listbox(p, bg=BG, fg=WARN, height=7, relief="flat",
                                   highlightthickness=0, selectbackground=GRID,
                                   font=("Consolas", 8))
        self.warn_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # ---------------------------------------------------------- agent panel
    def _build_agent_tab(self, p):
        bar = tk.Frame(p, bg=PANEL); bar.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(bar, text="介入度", bg=PANEL, fg=MUTE).pack(side="left")
        self.level = tk.StringVar(value=self.cfgfile.level)
        lc = ttk.Combobox(bar, width=10, state="readonly", textvariable=self.level,
                          values=[i.value for i in Intervention])
        lc.pack(side="left", padx=(6, 0)); lc.bind("<<ComboboxSelected>>", lambda e: self.set_level())
        tk.Button(bar, text="履歴クリア", command=self.clear_chat, bg=PANEL, fg=MUTE,
                  relief="flat", activebackground=GRID).pack(side="right")

        self.agent_status = tk.Label(p, text="", bg=PANEL, fg=MUTE, anchor="w", justify="left",
                                     wraplength=330, font=("Segoe UI", 8))
        self.agent_status.pack(fill="x", padx=12)

        self.chat = tk.Text(p, bg=BG, fg=INK, relief="flat", height=14, wrap="word",
                            insertbackground=INK, font=("Segoe UI", 9))
        self.chat.pack(fill="both", expand=True, padx=12, pady=(6, 4))
        self.chat.tag_configure("you", foreground=SEL, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("agent", foreground=INK)
        self.chat.tag_configure("meta", foreground=MUTE, font=("Segoe UI", 8))
        self.chat.configure(state="disabled")

        row = tk.Frame(p, bg=PANEL); row.pack(fill="x", padx=12)
        self.chat_entry = tk.Entry(row, bg=BG, fg=INK, insertbackground=INK, relief="flat")
        self.chat_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.chat_entry.bind("<Return>", lambda e: self.send_message())
        tk.Button(row, text="送信", command=self.send_message, bg=PANEL, fg=INK,
                  relief="flat", activebackground=GRID).pack(side="left", padx=(6, 0))
        tk.Label(p, text="例: 今のセット何分? / バランスどう? / 60:00に収めて / 何か足したい",
                 bg=PANEL, fg=MUTE, anchor="w", wraplength=330,
                 font=("Segoe UI", 8)).pack(fill="x", padx=12, pady=(2, 6))

        tk.Label(p, text="候補（ダブルクリックで挿入案）", bg=PANEL, fg=MUTE, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=12)
        self.cand_box = tk.Listbox(p, bg=BG, fg=INK, height=5, relief="flat",
                                   highlightthickness=0, selectbackground=GRID,
                                   font=("Consolas", 8))
        self.cand_box.pack(fill="x", padx=12)
        self.cand_box.bind("<Double-Button-1>", lambda e: self.insert_candidate())

        tk.Label(p, text="提案（チェックした操作だけ適用される）", bg=PANEL, fg=MUTE, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=12, pady=(8, 2))
        self.card = tk.Frame(p, bg=BG); self.card.pack(fill="x", padx=12)
        row = tk.Frame(p, bg=PANEL); row.pack(fill="x", padx=12, pady=(4, 10))
        tk.Button(row, text="適用", command=self.apply_pending, bg=PANEL, fg=PRESENT,
                  relief="flat", activebackground=GRID).pack(side="left")
        tk.Button(row, text="却下", command=self.reject_pending, bg=PANEL, fg=WARN,
                  relief="flat", activebackground=GRID).pack(side="left", padx=6)
        self.log_label = tk.Label(row, text="", bg=PANEL, fg=MUTE, font=("Segoe UI", 8))
        self.log_label.pack(side="right")

    # --------------------------------------------------------------- model
    def load(self):
        try:
            self._load()
        except Exception as ex:                 # a broken library must not kill the window
            import traceback
            self.status.set(f"読み込みに失敗した: {type(ex).__name__}: {ex}")
            try:
                (Settings.path().parent / "error.log").write_text(traceback.format_exc(),
                                                                  encoding="utf-8")
            except Exception:
                pass

    def _load(self):
        try:
            mm, ss = self.target_entry.get().split(":"); self.target_s = int(mm) * 60 + int(ss)
        except Exception:
            self.target_s = 60 * 60
        pl = self.playlists[self.pl_combo.current()]
        d = SetDraft(name=pl.name, tracks=[TrackEntry(i) for i in pl.track_ids])
        h = History(d); h.run(SetTargetLength(self.target_s, 60))
        cfg = dict(PRESET_CONFIG)
        if self.cap.get():
            cfg["max_drop_bars"] = 32
        self.cfg = cfg
        preset = self.preset.get()
        self.anlz = {}
        for e in d.tracks:
            ta = self.lib.analysis(e.track_id)
            if ta.anlz:
                self.anlz[e.track_id] = ta.anlz
            if preset != "full" and ta.phrase_status == PhraseStatus.PRESENT and ta.anlz:
                r = preset_range(ta.anlz, preset, cfg)
                if r:
                    h.run(SetRange(e.track_id, r.play_in_ms, r.play_out_ms, preset))
        self.draft = d
        self.history = h
        self.sel = None
        self.pending: ChangeSet | None = None
        self.cands: list[dict] = []
        self.tools = AgentTools(draft=d, lib=self.lib, anlz=self.anlz, curve=None, cfg=cfg)
        self.advisor = Advisor(self.tools, log=getattr(self, "plog", None) or ProposalLog(),
                               level=Intervention(self.level.get()))
        self.plog = self.advisor.log
        self.agent = LLMAgent(self.tools, self.advisor)
        self.agent_status.config(text=self.agent.status())
        self.render_card()
        self.recompute()

        present = sum(1 for e in d.tracks
                      if self.lib.analysis(e.track_id).phrase_status is PhraseStatus.PRESENT)
        if present == 0:
            self.status.set(
                f"「{pl.name}」にフレーズ解析のある曲が1つも無い。尺の管理は使えるが、展開と"
                "再生範囲は出せない — rekordbox の 環境設定 > 解析 で「フレーズ」をオンにして"
                "再解析し、Rescan を押せ")
        else:
            self.status.set(f"{pl.name}: {len(d.tracks)}曲中 {present}曲にフレーズ解析あり")
        self.save_settings()

    def recompute(self):
        if not getattr(self, "draft", None):
            return                       # a template can be restored before a set is loaded
        self.timeline = compute(self.draft, self.lib)
        self.points = set_energy_curve(self.timeline, self.anlz)
        total = max(self.timeline.total_s, 1.0)
        self.dev = deviation(self.points, self.curve, total) if self.curve_var.get() != "(none)" else []
        self.flats = flat_segments(self.points)
        self.sections = sections(self.draft, self.timeline)
        if getattr(self, "tools", None):
            self.tools.curve = self.curve if self.curve_var.get() != "(none)" else None
            self.tools.anlz = self.anlz
        self.refresh_panels()
        self.redraw()
        self._notice()

    def run(self, cmd) -> bool:
        try:
            self.history.run(cmd)
        except LockedError as ex:
            self.status.set(f"ロックされているため変更できない: {ex}")
            return False
        self.recompute()
        return True

    def do_undo(self):
        if self.history and self.history.undo():
            self.status.set("元に戻した"); self.recompute()

    def do_redo(self):
        if self.history and self.history.redo():
            self.status.set("やり直した"); self.recompute()

    def do_rescan(self):
        self.lib.rescan(); self.status.set("ライブラリを再スキャンした"); self.load()

    # ------------------------------------------------------------- actions
    def apply_template(self):
        name = self.curve_var.get()
        key = next((k for k, v in TEMPLATE_LABELS.items() if v == name), None)
        self.curve = template(key) if key else TargetCurve()
        self.recompute()

    def apply_track_preset(self):
        if self.sel is None: return
        e = self.draft.tracks[self.sel]
        name = self.sel_preset.get()
        t = self.lib.track(e.track_id)
        if name == "full":
            self.run(SetRange(e.track_id, 0, None, "full")); return
        ta = self.lib.analysis(e.track_id)
        if ta.phrase_status != PhraseStatus.PRESENT or not ta.anlz:
            self.status.set(f"{t.title[:28]}: フレーズ解析がないためプリセットを適用できない"); return
        r = preset_range(ta.anlz, name, self.cfg)
        if not r:
            self.status.set(f"{t.title[:28]}: {name} に合うドロップが見つからない"); return
        if self.run(SetRange(e.track_id, r.play_in_ms, r.play_out_ms, name)) and r.note:
            self.status.set(f"{t.title[:28]}: {r.note}")

    def apply_tempo(self):
        if self.sel is None: return
        e = self.draft.tracks[self.sel]
        txt = self.sel_tempo.get().strip()
        try:
            self.run(SetTempo(e.track_id, float(txt) if txt else None))
        except ValueError:
            self.status.set("テンポは数値で入れろ")

    def apply_milestone(self):
        if self.sel is None: return
        e = self.draft.tracks[self.sel]
        target = None
        txt = self.sel_mtime.get().strip()
        if self.sel_mile.get() and txt:
            try:
                mm, ss = txt.split(":"); target = int(mm) * 60 + int(ss)
            except Exception:
                self.status.set("目標時刻は mm:ss で入れろ"); return
        self.run(SetMilestone(e.track_id, self.sel_mile.get(), target))

    def toggle_milestone(self):
        if self.sel is None: return
        self.sel_mile.set(not self.draft.tracks[self.sel].is_milestone)
        self.apply_milestone()

    def apply_lock(self, target: str):
        if self.sel is None: return
        e = self.draft.tracks[self.sel]
        self.run(SetLock(e.track_id, target, self.locks[target].get()))

    def apply_trim(self):
        i = self.trim_box.curselection()
        if not i or not getattr(self, "_trims", None): return
        c = self._trims[i[0]]
        if self.run(c.cmd):
            self.status.set(f"{c.title[:28]}: {c.action} を適用（-{fmt(c.saves_s)}）")

    # -------------------------------------------------------------- panels
    def refresh_panels(self):
        tl = self.timeline
        delta = tl.delta_s or 0.0
        sign = "+" if delta >= 0 else "−"
        self.readout.config(
            text=f"{fmt(tl.total_s)} / {fmt(self.target_s)}  {sign}{fmt(abs(delta))}",
            fg=(WARN if abs(delta) > tl.tolerance_s else PRESENT))

        self.sections_box.delete(0, "end")
        for s in self.sections:
            self.sections_box.insert("end", describe_section(s))

        # trim candidates (S1-6): what a shorter preset would save, per track
        presets = {}
        for e in self.draft.tracks:
            if e.preset == "one_drop":
                continue
            ta = self.lib.analysis(e.track_id)
            if ta.phrase_status == PhraseStatus.PRESENT and ta.anlz:
                r = preset_range(ta.anlz, "one_drop", self.cfg)
                if r:
                    presets[e.track_id] = (r.play_in_ms, r.play_out_ms)
        self._trims = trim_candidates(self.draft, self.lib, presets)[:12]
        self.trim_box.delete(0, "end")
        for c in self._trims:
            self.trim_box.insert("end", f"-{fmt(c.saves_s):>5}  {c.action:<14} {c.title[:22]}")

        self.warn_box.delete(0, "end")
        from setagent.analysis.curve import describe as describe_seg
        for w in tl.warnings:
            self.warn_box.insert("end", f"! {w}")
        for s in self.flats:
            self.warn_box.insert("end", f"! 平坦 {describe_seg(s)}")
        for s in self.dev:
            self.warn_box.insert("end", f"~ {describe_seg(s)}")
        for m in milestones(self.draft, self.timeline):
            d = m.delta_s
            if d is not None and abs(d) > 60:
                self.warn_box.insert("end", f"* {m.title[:20]} 目標と{fmt(abs(d))}ズレ")

        self.refresh_selection()

    def refresh_selection(self):
        if self.sel is None or self.sel >= len(self.draft.tracks):
            self.sel_title.config(text="—"); self.sel_meta.config(text="ブロックをクリックして選択")
            return
        e = self.draft.tracks[self.sel]
        p = self.timeline.placements[self.sel]
        ta = self.lib.analysis(e.track_id)
        self.sel_title.config(text=f"{self.sel + 1}. {p.title}")
        self.sel_meta.config(text=(f"{fmt(p.start_s)} → {fmt(p.end_s)}   再生 {fmt(p.play_s)}\n"
                                   f"{p.original_bpm:.1f} BPM → {p.set_tempo:.1f}   phrases: {ta.phrase_status.value}"))
        self.sel_preset.set(e.preset if e.preset in PRESETS else "full")
        self.sel_tempo.delete(0, "end")
        if e.tempo: self.sel_tempo.insert(0, f"{e.tempo:.2f}")
        self.sel_mile.set(e.is_milestone)
        self.sel_mtime.delete(0, "end")
        if e.target_time_s is not None: self.sel_mtime.insert(0, fmt(e.target_time_s))
        for t, v in self.locks.items():
            v.set(e.locked(t))

    # -------------------------------------------------------------- layout
    def geom(self):
        c = self.canvas
        W = c.winfo_width() or 1080; H = c.winfo_height() or 780
        L, R, T = 70, W - 20, 22
        lane_y, lane_h = T + 26, 96
        sec_y, sec_h = lane_y + lane_h + 26, 24
        curve_y = sec_y + sec_h + 40
        curve_h = max(140, H - curve_y - 46)
        return W, H, L, R, T, lane_y, lane_h, sec_y, sec_h, curve_y, curve_h

    def span(self):
        return max(self.timeline.total_s, self.target_s, 1)

    def grid_step_min(self) -> int:
        """Gridline spacing that keeps the ruler readable at any set length."""
        minutes = self.span() / 60
        for step in (1, 2, 5, 10, 15, 30, 60, 120, 180):
            if minutes / step <= 18:
                return step
        return 240

    def x_of(self, t):
        _, _, L, R, *_ = self.geom()
        return L + (R - L) * (t / self.span())

    def t_of(self, x):
        _, _, L, R, *_ = self.geom()
        return (x - L) / max(R - L, 1) * self.span()

    # ------------------------------------------------------------ drawing
    def redraw(self):
        c = self.canvas; c.delete("all")
        if not getattr(self, "timeline", None):
            return
        W, H, L, R, T, lane_y, lane_h, sec_y, sec_h, curve_y, curve_h = self.geom()
        tl = self.timeline
        x = self.x_of

        step = self.grid_step_min()
        m = 0
        while m * 60 <= self.span():
            gx = x(m * 60)
            c.create_line(gx, lane_y - 10, gx, curve_y + curve_h, fill=GRID)
            c.create_text(gx, curve_y + curve_h + 12, text=f"{m}m", fill=MUTE, font=("Segoe UI", 8))
            m += step
        tx = x(self.target_s)
        c.create_line(tx, T, tx, curve_y + curve_h, fill=TARGET, dash=(4, 3), width=2)
        c.create_text(tx, T - 4, text="target", fill=TARGET, font=("Segoe UI", 8), anchor="s")

        self._draw_tracks(c, lane_y, lane_h)
        self._draw_sections(c, sec_y, sec_h, lane_y)
        self._draw_energy(c, curve_y, curve_h, L, R)
        self._draw_legend(c, L, curve_y + curve_h + 26)

        if getattr(self, "pending", None):
            self._draw_ghost(c, lane_y, lane_h)
        if self.drag and self.drag.get("kind") == "reorder" and self.drag.get("drop_x") is not None:
            dx = self.drag["drop_x"]
            c.create_line(dx, lane_y - 8, dx, lane_y + lane_h + 8, fill=SEL, width=3)

    def _draw_tracks(self, c, lane_y, lane_h):
        c.create_text(self.x_of(0), lane_y - 16, text="TRACKS", fill=MUTE, anchor="w",
                      font=("Segoe UI", 8, "bold"))
        skel = self.skeleton_only.get()
        keep = {m.index for m in skeleton(self.draft, self.timeline)} if skel else None
        for i, p in enumerate(self.timeline.placements):
            x0, x1 = self.x_of(p.start_s), self.x_of(p.end_s)
            e = self.draft.tracks[i]
            if skel and i not in keep:
                c.create_rectangle(x0 + 1, lane_y + lane_h * 0.38, max(x1 - 1, x0 + 2), lane_y + lane_h * 0.62,
                                   fill="#232830", outline="")
                continue
            has = self.lib.analysis(p.track_id).phrase_status == PhraseStatus.PRESENT
            col = PRESENT if has else ABSENT
            out = SEL if i == self.sel else BG
            c.create_rectangle(x0 + 1, lane_y, max(x1 - 1, x0 + 2), lane_y + lane_h,
                               fill=col, outline=out, width=2 if i == self.sel else 1)
            if x1 - x0 > 34:
                c.create_text(x0 + 6, lane_y + 8, text=p.title[:18], fill="#0d1117", anchor="nw",
                              font=("Segoe UI", 8, "bold"))
                c.create_text(x0 + 6, lane_y + lane_h - 30, text=f"{p.original_bpm:.0f}", fill="#0d1117",
                              anchor="nw", font=("Segoe UI", 8))
                c.create_text(x0 + 6, lane_y + lane_h - 16, text=e.preset, fill="#0d1117",
                              anchor="nw", font=("Segoe UI", 7))
            if e.locks:
                c.create_text(max(x1 - 6, x0 + 8), lane_y + 8, text="🔒", anchor="ne", font=("Segoe UI", 8))
            if e.is_milestone:
                c.create_polygon(x0, lane_y - 6, x0 - 6, lane_y - 16, x0 + 6, lane_y - 16, fill=MILE)
                if e.target_time_s is not None:
                    gx = self.x_of(e.target_time_s)
                    c.create_line(gx, lane_y - 16, gx, lane_y + lane_h, fill=MILE, dash=(2, 2))
                    c.create_line(x0, lane_y - 11, gx, lane_y - 11, fill=MILE, width=1)
            if p.warnings:
                c.create_text(x0 + 3, lane_y + lane_h * 0.55, text="!", fill=WARN, anchor="w",
                              font=("Segoe UI", 11, "bold"))

    def _draw_sections(self, c, sec_y, sec_h, lane_y):
        for s in self.sections:
            x0, x1 = self.x_of(s.start_s), self.x_of(s.end_s)
            c.create_rectangle(x0 + 1, sec_y, max(x1 - 1, x0 + 2), sec_y + sec_h,
                               fill=PANEL, outline=GRID)
            if s.target_s is not None:
                gx = self.x_of(s.start_s + s.target_s)
                c.create_line(gx, sec_y, gx, sec_y + sec_h, fill=TARGET, width=2)
            if x1 - x0 > 90:
                d = s.delta_s
                txt = f"{s.track_count}曲 {fmt(s.actual_s)}"
                if d is not None:
                    txt += f"  {'+' if d >= 0 else '−'}{fmt(abs(d))}"
                    r = s.room_for_tracks
                    if r: txt += f"  ({'+' if r > 0 else ''}{r}曲)"
                c.create_text(x0 + 6, sec_y + sec_h / 2, text=txt, fill=MUTE, anchor="w",
                              font=("Segoe UI", 8))

    def _draw_energy(self, c, y0, h, L, R):
        c.create_text(L, y0 - 16, text="ENERGY — 実測（フレーズ解析）と目標カーブ", fill=MUTE, anchor="w",
                      font=("Segoe UI", 8, "bold"))
        c.create_rectangle(L, y0, R, y0 + h, outline=GRID)
        base = y0 + h
        def ey(v): return base - v * h

        for s in self.flats:
            c.create_rectangle(self.x_of(s.start_s), y0, self.x_of(s.end_s), base,
                               fill=FLAT, outline="", stipple="gray25")
        for s in self.dev:
            c.create_rectangle(self.x_of(s.start_s), y0, self.x_of(s.end_s), base,
                               fill=(OVER if s.kind == "over" else UNDER), outline="", stipple="gray50")

        run: list[tuple[float, float]] = []
        def flush(run):
            if len(run) >= 2:
                poly = [run[0][0], base]
                for px, py in run: poly += [px, py]
                poly += [run[-1][0], base]
                c.create_polygon(poly, fill="#16324d", outline="")
                for i in range(1, len(run)):
                    c.create_line(run[i - 1][0], run[i - 1][1], run[i][0], run[i][1], fill=ACCENT, width=2)
        prev_unknown = None
        for pt in self.points:
            px, py = self.x_of(pt.time_s), ey(pt.energy)
            if pt.known:
                prev_unknown = None
                run.append((px, py))
            else:
                if run: flush(run); run = []
                uy = ey(0.12)
                if prev_unknown is not None:
                    c.create_line(prev_unknown[0], uy, px, uy, fill=ABSENT, width=1, dash=(3, 3))
                prev_unknown = (px, uy)
        flush(run)

        known = [p for p in self.points if p.known]
        if known:
            pk = max(known, key=lambda p: p.energy)
            c.create_line(self.x_of(pk.time_s), y0, self.x_of(pk.time_s), base, fill=WARN, dash=(2, 2))
            px = self.x_of(pk.time_s)    # inside the plot: the strip above is the title's
            near_right = px > (L + R) / 2
            c.create_text(px + (-4 if near_right else 4), y0 + 4, text=f"peak {fmt(pk.time_s)}",
                          fill=WARN, anchor="ne" if near_right else "nw", font=("Segoe UI", 8))

        # target curve — over the set length, with grab handles.
        # Not drawn until the DJ picks a template or draws one: a flat default
        # line would read as "your target is flat", which is a lie.
        if self.curve_var.get() == "(none)":
            return
        total = max(self.timeline.total_s, 1.0)
        prev = None
        for i in range(0, 101):
            pos = i / 100
            px = self.x_of(pos * total); py = ey(self.curve.at(pos))
            if prev: c.create_line(prev[0], prev[1], px, py, fill=TARGET, width=2, dash=(6, 3))
            prev = (px, py)
        for i, (pos, en) in enumerate(self.curve.points):
            px, py = self.x_of(pos * total), ey(en)
            c.create_oval(px - 5, py - 5, px + 5, py + 5, fill=TARGET, outline=BG, width=2, tags=f"cp{i}")

    def _draw_legend(self, c, L, y):
        items = [(PRESENT, "フレーズ解析あり"), (ABSENT, "解析なし（フル尺）"),
                 (TARGET, "目標カーブ／目標時刻"), (OVER, "目標より高い"), (UNDER, "目標より低い"), (FLAT, "平坦")]
        x = L
        for col, label in items:
            c.create_rectangle(x, y, x + 14, y + 10, fill=col, outline="")
            tid = c.create_text(x + 19, y + 5, text=label, fill=MUTE, anchor="w",
                                font=("Segoe UI", 8))
            x = c.bbox(tid)[2] + 26      # measured, not guessed: survives any DPI
        c.create_text(L, y + 34, anchor="w", fill=MUTE, font=("Segoe UI", 8),
                      text="ブロック: ドラッグで並べ替え／端をドラッグで再生範囲　M キーでマイルストーン　"
                           "カーブ: 点をドラッグ、ダブルクリックで追加、右クリックで削除　Ctrl+Z / Ctrl+Y")

    # --------------------------------------------------------------- input
    def hit_track(self, x, y):
        _, _, _, _, _, lane_y, lane_h, *_ = self.geom()
        if not (lane_y <= y <= lane_y + lane_h):
            return None, None
        for i, p in enumerate(self.timeline.placements):
            x0, x1 = self.x_of(p.start_s), self.x_of(p.end_s)
            if x0 <= x <= x1:
                if x - x0 <= EDGE_PX: return i, "in"
                if x1 - x <= EDGE_PX: return i, "out"
                return i, "body"
        return None, None

    def hit_curve(self, x, y):
        _, _, L, R, _, _, _, _, _, curve_y, curve_h = self.geom()
        if not (curve_y <= y <= curve_y + curve_h):
            return None
        total = max(self.timeline.total_s, 1.0)
        pos = self.t_of(x) / total
        en = (curve_y + curve_h - y) / curve_h
        i, d = self.curve.nearest_point(pos, en, aspect=(R - L) / max(curve_h, 1))
        px = self.x_of(self.curve.points[i][0] * total)
        py = curve_y + curve_h - self.curve.points[i][1] * curve_h
        return i if abs(px - x) <= 8 and abs(py - y) <= 8 else None

    def on_press(self, ev):
        if not getattr(self, "timeline", None): return
        ci = self.hit_curve(ev.x, ev.y)
        if ci is not None:
            self.drag = {"kind": "curve", "index": ci}; return
        i, where = self.hit_track(ev.x, ev.y)
        if i is None:
            self.sel = None; self.refresh_selection(); self.redraw(); return
        self.sel = i; self.refresh_selection()
        e = self.draft.tracks[i]
        if where in ("in", "out"):
            if e.locked("range"):
                self.status.set("range がロックされている"); self.drag = None; self.redraw(); return
            t = self.lib.track(e.track_id)
            self.drag = {"kind": "range", "index": i, "edge": where, "x0": ev.x,
                         "pin": e.play_in_ms,
                         "pout": e.play_out_ms if e.play_out_ms is not None else t.length_s * 1000,
                         "scale": (self.timeline.placements[i].set_tempo / t.bpm) if t.bpm else 1.0,
                         "len_ms": t.length_s * 1000}
        else:
            if e.locked("position"):
                self.status.set("position がロックされている"); self.drag = None; self.redraw(); return
            self.drag = {"kind": "reorder", "index": i, "drop_x": None, "to": i}
        self.redraw()

    def on_motion(self, ev):
        if not self.drag: return
        k = self.drag["kind"]
        if k == "curve":
            _, _, _, _, _, _, _, _, _, curve_y, curve_h = self.geom()
            total = max(self.timeline.total_s, 1.0)
            self.curve.move_point(self.drag["index"], self.t_of(ev.x) / total,
                                  (curve_y + curve_h - ev.y) / curve_h)
            self.curve_var.set("(custom)")
            self.dev = deviation(self.points, self.curve, total)
            self.redraw()
        elif k == "reorder":
            t = self.t_of(ev.x)
            to = len(self.timeline.placements) - 1
            for i, p in enumerate(self.timeline.placements):
                if t < (p.start_s + p.end_s) / 2:
                    to = i; break
            self.drag["to"] = to
            self.drag["drop_x"] = self.x_of(self.timeline.placements[to].start_s)
            self.redraw()
        elif k == "range":
            d = self.drag
            dt = (ev.x - d["x0"]) / max(self.x_of(60) - self.x_of(0), 1e-6) * 60      # set-seconds
            dms = int(dt * 1000 * d["scale"])
            if d["edge"] == "out":
                d["preview_out"] = max(d["pin"] + 30_000, min(d["len_ms"], d["pout"] + dms))
            else:
                d["preview_in"] = max(0, min(d["pout"] - 30_000, d["pin"] + dms))
            self.status.set("範囲: " + fmt((d.get("preview_out", d["pout"]) - d.get("preview_in", d["pin"])) / 1000))

    def on_release(self, ev):
        if not self.drag: return
        d, self.drag = self.drag, None
        if d["kind"] == "reorder" and d["to"] != d["index"]:
            e = self.draft.tracks[d["index"]]
            self.sel = d["to"]
            self.run(Move(f"#{d['index']}", d["to"]))
            self.status.set(f"{d['index'] + 1} 番目を {d['to'] + 1} 番目に移した")
        elif d["kind"] == "range" and ("preview_in" in d or "preview_out" in d):
            e = self.draft.tracks[d["index"]]
            self.run(SetRange(e.track_id, d.get("preview_in", d["pin"]),
                              d.get("preview_out", d["pout"]), "custom"))
        else:
            self.redraw()

    def on_double(self, ev):
        _, _, _, _, _, _, _, _, _, curve_y, curve_h = self.geom()
        if curve_y <= ev.y <= curve_y + curve_h:
            total = max(self.timeline.total_s, 1.0)
            self.curve.add_point(self.t_of(ev.x) / total, (curve_y + curve_h - ev.y) / curve_h)
            self.curve_var.set("(custom)")
            self.recompute()

    def on_right(self, ev):
        ci = self.hit_curve(ev.x, ev.y)
        if ci is not None:
            self.curve.remove_point(ci); self.curve_var.set("(custom)"); self.recompute(); return
        i, _ = self.hit_track(ev.x, ev.y)
        if i is not None:
            self.sel = i; self.refresh_selection(); self.toggle_milestone()


    def save_settings(self):
        c = self.cfgfile
        try:
            c.playlist = self.playlists[self.pl_combo.current()].name
        except Exception:
            pass
        c.target = self.target_entry.get().strip() or c.target
        c.preset = self.preset.get()
        c.cap32 = bool(self.cap.get())
        c.curve = self.curve_var.get()
        c.level = self.level.get()
        c.save()

    def on_close(self):
        self.save_settings()
        self.destroy()

    # -------------------------------------------------------------- export
    def export_xml(self):
        """S5-2: say what survives the round trip before writing anything."""
        from setagent.rekordbox.xml_export import build_xml, describe_preview, export_preview
        text = describe_preview(export_preview(self.draft, self.lib))

        win = tk.Toplevel(self); win.title("rekordbox に書き戻す"); win.configure(bg=BG)
        win.geometry("760x560"); win.transient(self); win.grab_set()
        box = tk.Text(win, bg=BG, fg=INK, relief="flat", wrap="word", font=("Segoe UI", 9))
        box.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        box.insert("1.0", text); box.configure(state="disabled")
        row = tk.Frame(win, bg=BG); row.pack(fill="x", padx=14, pady=(0, 14))

        def write():
            from tkinter import filedialog, messagebox
            path = filedialog.asksaveasfilename(
                parent=win, defaultextension=".xml", filetypes=[("rekordbox XML", "*.xml")],
                initialfile=f"SetAgent_{self.draft.name}.xml")
            if not path:
                return
            xml, meta = build_xml(self.draft, self.lib)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml)
            win.destroy()
            self.status.set(f"書き出した: {path}（{meta['included']}曲、{len(meta['skipped'])}曲スキップ）")
            messagebox.showinfo("書き出し完了",
                                f"{meta['included']}曲を書き出した。\n\n"
                                "rekordbox 側の手順:\n"
                                "1. Preferences > Advanced > Database > rekordbox xml > Imported Library で"
                                "このファイルを指定\n"
                                "2. rekordbox を再起動\n"
                                "3. ブラウザ左のアイコンレールで「Display rekordbox xml」をオン")

        tk.Button(row, text="書き出す", command=write, bg=PANEL, fg=PRESENT, relief="flat",
                  activebackground=GRID).pack(side="left")
        tk.Button(row, text="やめる", command=win.destroy, bg=PANEL, fg=MUTE, relief="flat",
                  activebackground=GRID).pack(side="left", padx=8)

    # --------------------------------------------------------------- agent
    def set_level(self):
        self.advisor.level = Intervention(self.level.get())
        if self.advisor.level is Intervention.OFF:
            self.pending = None; self.render_card(); self.redraw()
        self.say("meta", f"介入度: {self.level.get()}")

    def say(self, tag: str, text: str):
        self.chat.configure(state="normal")
        self.chat.insert("end", text.rstrip() + "\n", tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def clear_chat(self):
        self.chat.configure(state="normal"); self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self.agent.reset()

    def send_message(self):
        text = self.chat_entry.get().strip()
        if not text:
            return
        self.chat_entry.delete(0, "end")
        self.say("you", f"> {text}")
        if self.sel is not None:
            self.say("meta", f"   文脈: {self.sel + 1}. {self.timeline.placements[self.sel].title[:28]}")
        reply = self.agent.ask(text, self.sel)
        self.say("agent", reply.text)
        if reply.used_tools:
            self.say("meta", "   tools: " + ", ".join(dict.fromkeys(reply.used_tools)))
        self.cands = reply.candidates
        self.cand_box.delete(0, "end")
        for c in self.cands:
            self.cand_box.insert("end", f"{c['title'][:26]:26s} {c['bpm']:6.1f} {c['key']:>4} {c['in_slot']:>6}")
        if reply.change_set:
            self.pending = reply.change_set
        self.render_card(); self.redraw()

    def insert_candidate(self):
        i = self.cand_box.curselection()
        if not i or not self.cands:
            return
        at = (self.sel + 1) if self.sel is not None else len(self.draft.tracks)
        r = self.advisor.insert_candidate(self.cands[i[0]]["track_id"], at)
        self.say("agent", r.text)
        self.pending = r.change_set
        self.render_card(); self.redraw()

    def render_card(self):
        for w in self.card.winfo_children():
            w.destroy()
        cs = self.pending
        if not cs:
            tk.Label(self.card, text="（提案なし）", bg=BG, fg=MUTE,
                     font=("Segoe UI", 8)).pack(anchor="w", padx=6, pady=4)
            self.log_label.config(text=self.plog.summary() if self.plog.proposed else "")
            return
        self._card_vars = []
        for item in cs.items:
            v = tk.BooleanVar(value=item.approved)
            self._card_vars.append((v, item))
            tk.Checkbutton(self.card, text=item.op.describe(self.tools.title_of), variable=v,
                           bg=BG, fg=INK, selectcolor=PANEL, anchor="w", justify="left",
                           wraplength=310, activebackground=BG, activeforeground=INK,
                           font=("Segoe UI", 8),
                           command=self.sync_card).pack(fill="x", padx=4)
        for line in cs.diff_lines:
            tk.Label(self.card, text="  " + line, bg=BG, fg=MUTE, anchor="w",
                     font=("Consolas", 8)).pack(fill="x", padx=4)
        self.log_label.config(text=self.plog.summary())

    def sync_card(self):
        for v, item in getattr(self, "_card_vars", []):
            item.approved = v.get()
        self.redraw()

    def apply_pending(self):
        cs = self.pending
        if not cs:
            return
        cmds = cs.approved_commands()
        if not cmds:
            self.say("meta", "承認された操作がない"); return
        try:
            self.history.run_all(cmds)
        except LockedError as ex:
            self.say("meta", f"適用できない（ロック: {ex}）"); return
        self.plog.record_outcome(cs)
        self.say("meta", f"適用した（{len(cmds)}件）。Ctrl+Z で戻せる")
        self.pending = None
        self.render_card(); self.recompute()

    def reject_pending(self):
        cs = self.pending
        if not cs:
            return
        for i in cs.items:
            i.approved = False
        self.plog.record_outcome(cs)
        self.pending = None
        self.say("meta", "却下した。同じ案はもう出さない")
        self.render_card(); self.redraw()

    def _notice(self):
        if not getattr(self, "advisor", None):
            return
        for n in self.advisor.notices()[:1]:
            if n != getattr(self, "_last_notice", None):
                self._last_notice = n
                self.say("meta", f"[気づいたこと] {n}")

    def _draw_ghost(self, c, lane_y, lane_h):
        """S4-3: the proposal drawn over the set, before anything is applied."""
        try:
            ghost = self.pending.preview(self.draft, self.lib)
        except Exception:
            return
        y = lane_y + lane_h + 4
        c.create_text(self.x_of(0) - 6, y + 7, text="提案後", fill=SEL, anchor="e",
                      font=("Segoe UI", 8, "bold"))
        for p in ghost.placements:
            c.create_rectangle(self.x_of(p.start_s) + 1, y, max(self.x_of(p.end_s) - 1,
                               self.x_of(p.start_s) + 2), y + 14, outline=SEL, dash=(3, 2))
        c.create_line(self.x_of(ghost.total_s), y - 3, self.x_of(ghost.total_s), y + 17,
                      fill=SEL, width=2)


def open_library(explicit: str | None = None, cache: str | None = None,
                 plain: str | None = None) -> Library | None:
    """Find the library, or ask the DJ where it is. Returns None if they give up.

    On a teammate's PC the first run is the only run that matters: if this fails
    silently they will never open the app again.
    """
    from tkinter import filedialog, messagebox
    cfg = Settings.load()
    for candidate in (explicit, cfg.master_db or None, None):
        try:
            lib = Library.open(master_db=candidate, cache_dir=cache, plain_db=plain)
            if candidate and candidate != cfg.master_db:
                cfg.master_db = candidate; cfg.save()
            return lib
        except LibraryNotFound:
            continue
        except Exception as ex:
            root = tk.Tk(); root.withdraw()
            messagebox.showerror("Set Agent",
                                 f"rekordbox のライブラリを読めなかった。\n\n{type(ex).__name__}: {ex}\n\n"
                                 "コマンドプロンプトで `SetAgent --doctor` を実行すると"
                                 "原因の切り分けができる")
            root.destroy()
            return None

    root = tk.Tk(); root.withdraw()
    go = messagebox.askokcancel(
        "Set Agent",
        "rekordbox の master.db が自動で見つからなかった。\n\n"
        "rekordbox 6 / 7 をインストールして一度起動していれば、通常は\n"
        "  %APPDATA%\\Pioneer\\rekordbox\\master.db\n"
        "にある。場所が違う場合は、次の画面で master.db を指定しろ。")
    if not go:
        root.destroy(); return None
    path = filedialog.askopenfilename(title="master.db を選ぶ",
                                      filetypes=[("rekordbox database", "master.db"),
                                                 ("すべてのファイル", "*.*")])
    root.destroy()
    if not path:
        return None
    try:
        lib = Library.open(master_db=path, cache_dir=cache, plain_db=plain)
    except Exception as ex:
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("Set Agent", f"そのファイルは読めなかった。\n\n{type(ex).__name__}: {ex}")
        root.destroy()
        return None
    cfg.master_db = path; cfg.save()
    return lib


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db"); ap.add_argument("--share"); ap.add_argument("--cache"); ap.add_argument("--plain")
    ap.add_argument("--playlist", help="open this playlist instead of the largest one")
    ap.add_argument("--doctor", action="store_true", help="環境診断だけ実行する")
    a = ap.parse_args(argv)

    if a.doctor:
        from setagent.diagnostics import run
        rep = run(a.db)
        print(rep.text())
        try:                                   # a --noconsole build has nowhere to print
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showinfo("Set Agent 診断", rep.text())
            root.destroy()
        except Exception:
            pass
        return 1 if rep.failed else 0

    lib = open_library(a.db, a.cache, a.plain)
    if lib is None:
        return 1
    if a.share:
        from pathlib import Path
        lib.share_dir = Path(a.share)
    App(lib, playlist=a.playlist).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
