"""Set Agent — command-line companion (v0). No LLM, no overlay: time + phrases only.

  python -m setagent.cli playlists
  python -m setagent.cli phrases  "<playlist>"
  python -m setagent.cli timeline "<playlist>" --target 15:00 --preset one_drop [--cap 32]
  python -m setagent.cli rescan
Options: --db <master.db> (default: auto-detect on this PC)  --share <share dir>
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from setagent.analysis.phrases import PRESET_CONFIG, describe, preset_range
from setagent.analysis.timing import compute, fmt
from setagent.domain.draft import History, SetDraft, SetRange, SetTargetLength, TrackEntry
from setagent.rekordbox.library import Library, PhraseStatus


def parse_mmss(s: str) -> int:
    m, sec = s.split(":"); return int(m) * 60 + int(sec)


def open_lib(a) -> Library:
    lib = Library.open(master_db=a.db, cache_dir=a.cache, plain_db=a.plain)
    if a.share:
        lib.share_dir = Path(a.share)
    return lib


def build_draft(lib: Library, name: str, preset: str, cfg: dict) -> tuple[SetDraft, History, list[str]]:
    pl = lib.db.playlist_by_name(name)
    d = SetDraft(name=name, tracks=[TrackEntry(i) for i in pl.track_ids])
    h = History(d)
    notes = []
    if preset != "full":
        for e in d.tracks:
            ta = lib.analysis(e.track_id)
            if ta.phrase_status != PhraseStatus.PRESENT or not ta.anlz:
                notes.append(f"{ta.track.title[:30]}: kept full ({ta.phrase_status.value})")
                continue
            r = preset_range(ta.anlz, preset, cfg)
            if r:
                h.run(SetRange(e.track_id, r.play_in_ms, r.play_out_ms, preset))
                if r.note:
                    notes.append(f"{ta.track.title[:30]}: {r.note}")
    return d, h, notes


def main(argv=None):
    # Japanese Windows consoles default to cp932, which cannot encode "—" or "○".
    # Reconfigure rather than dumbing the output down.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["playlists", "phrases", "timeline", "rescan", "export", "agent", "doctor"])
    p.add_argument("playlist", nargs="?")
    p.add_argument("--db"); p.add_argument("--share"); p.add_argument("--cache"); p.add_argument("--plain")
    p.add_argument("--target"); p.add_argument("--preset", default="full")
    p.add_argument("--cap", type=int, help="max drop bars for one_drop/two_drop")
    p.add_argument("--out", help="output path for export (rekordbox XML)")
    p.add_argument("--dry-run", action="store_true", help="show what the write-back carries, then stop")
    p.add_argument("--ask", help="question for the agent")
    p.add_argument("--level", default="passive", choices=["off", "passive", "proactive"])
    a = p.parse_args(argv)

    if a.cmd == "doctor":                       # must run before open_lib: it diagnoses that
        from setagent.diagnostics import run
        rep = run(a.db)
        print(rep.text())
        return 1 if rep.failed else 0

    lib = open_lib(a)
    for w in getattr(lib, "warnings", []):
        print(f"! {w}")
    cfg = copy.deepcopy(PRESET_CONFIG)
    if a.cap: cfg["max_drop_bars"] = a.cap

    if a.cmd == "playlists":
        for pl in lib.playlists():
            s = lib.phrase_summary(list(pl.track_ids))
            print(f"{pl.name:28s} {len(pl.track_ids):3d} tracks  phrases: {s[PhraseStatus.PRESENT]} present / "
                  f"{s[PhraseStatus.ABSENT]} absent / {s[PhraseStatus.NO_ANALYSIS]} no-analysis")
        return
    if a.cmd == "rescan":
        lib.rescan(); print("rescanned"); return

    pl = lib.db.playlist_by_name(a.playlist)
    if a.cmd == "phrases":
        for tid in pl.track_ids:
            ta = lib.analysis(tid); t = ta.track
            tag = ta.phrase_status.value + (" (cloud)" if t.is_cloud else "")
            print(f"{t.title[:34]:34s} {t.bpm:6.1f} {fmt(t.length_s):>6} [{tag}] {describe(ta.anlz) if ta.anlz else ''}"[:160])
        return

    d, h, notes = build_draft(lib, a.playlist, a.preset, cfg)
    if a.target:
        h.run(SetTargetLength(parse_mmss(a.target), 60))

    if a.cmd == "export":
        from setagent.rekordbox.xml_export import build_xml, describe_preview, export_preview
        print(describe_preview(export_preview(d, lib)))       # S5-2: say it before doing it
        print()
        if a.dry_run:
            return
        xml, meta = build_xml(d, lib)
        out = a.out or f"SetAgent_{a.playlist}.xml"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(xml)
        print(f"wrote {out}: {meta['included']} tracks, {len(meta['skipped'])} skipped (cloud/no local file)")
        for title, why in meta["skipped"][:8]:
            print(f"  skip: {title[:40]} — {why}")
        print("Import in rekordbox:")
        print("  1. Preferences > Advanced > Database > rekordbox xml > Imported Library -> select this file")
        print("  2. RESTART rekordbox (it reads the imported library only at launch)")
        print("  3. In the browser's left icon rail, turn ON 'Display rekordbox xml'")
        print("     (Preferences > View > Layout > 'rekordbox xml' only puts the icon in the rail)")
        return

    if a.cmd == "agent":
        from setagent.agent.advisor import Advisor, Intervention
        from setagent.agent.llm import LLMAgent
        from setagent.agent.tools import AgentTools
        tools = AgentTools(draft=d, lib=lib, anlz={i: lib.analysis(i).anlz for i in
                                                   (e.track_id for e in d.tracks)
                                                   if lib.analysis(i).anlz}, cfg=cfg)
        agent = LLMAgent(tools, Advisor(tools, level=Intervention(a.level)))
        print(agent.status())
        if a.ask:
            r = agent.ask(a.ask)
            print(r.text)
            if r.used_tools:
                print("tools:", ", ".join(dict.fromkeys(r.used_tools)))
            return
        print("(--ask \"質問\" で質問できます)")
        return

    tl = compute(d, lib)
    print(f"== {a.playlist}: {len(d.tracks)} tracks, preset={a.preset}, est. total {fmt(tl.total_s)}"
          + (f", target {a.target} (delta {fmt(tl.delta_s)})" if a.target else ""))
    for pobj, e in zip(tl.placements, d.tracks):
        st = lib.analysis(e.track_id).phrase_status.value[:3]
        print(f"  {pobj.index:2d} {fmt(pobj.start_s):>6}-{fmt(pobj.end_s):>6} {fmt(pobj.play_s):>5} {pobj.original_bpm:6.1f} [{e.preset:8s}|{st}] {pobj.title[:40]} {' '.join(pobj.warnings)}")
    if tl.warnings: print("warnings:", *tl.warnings, sep="\n  - ")
    if notes: print("notes:", *notes, sep="\n  - ")


if __name__ == "__main__":
    main()
