"""Fixed demo of the Agent Panel, so the screenshot is reproducible.

  python -m tools.demo_agent_shot <out.png> [playlist] [curve_key]

Questions live here rather than on the command line: a Japanese Windows console
mangles non-ASCII arguments, and this has cost enough time already.
"""
from __future__ import annotations

import sys

import setagent.gui.timeline as T
from setagent.rekordbox.library import Library
from tools.winshot import settle, shoot

QUESTIONS = ["バランスどう？", "区間の余白は？", "30分あたりが平坦だから何か足したい"]

out = sys.argv[1] if len(sys.argv) > 1 else "agent_demo.png"
playlist = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
curve_key = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None

lib = Library.open()
app = T.App(lib, playlist=playlist)
app.state("zoomed"); settle(app)

if curve_key:
    from setagent.analysis.curve import TEMPLATE_LABELS
    app.curve_var.set(TEMPLATE_LABELS[curve_key]); app.apply_template()

app.notebook.select(1)
app.sel = 0
app.refresh_selection(); settle(app)

for q in QUESTIONS:
    app.chat_entry.delete(0, "end"); app.chat_entry.insert(0, q)
    app.send_message(); settle(app)

if app.cands:                      # turn the first candidate into a proposal + ghost
    app.cand_box.selection_set(0)
    app.insert_candidate(); settle(app)

print("candidates:", len(app.cands), "| pending:", bool(app.pending))
print("log:", app.plog.summary())
print("captured", out, *shoot(app, out))
app.destroy()
