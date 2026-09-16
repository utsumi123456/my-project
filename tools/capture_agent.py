"""Drive the Agent Panel and capture it, so the conversation can be reviewed.

  python -m tools.capture_agent <out.png> [playlist] [curve_key] "質問1" "質問2" ...

Sends each question through the panel exactly as typing it would, then saves a
PNG of the window with the agent tab in front.
"""
from __future__ import annotations

import sys

import setagent.gui.timeline as T
from setagent.rekordbox.library import Library
from tools.winshot import settle, shoot

out = sys.argv[1] if len(sys.argv) > 1 else "agent.png"
playlist = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
curve_key = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None
questions = sys.argv[4:] or ["今のセット何分？", "バランスどう？"]

lib = Library.open()
app = T.App(lib, playlist=playlist)
app.state("zoomed")
settle(app)

if curve_key:
    from setagent.analysis.curve import TEMPLATE_LABELS
    app.curve_var.set(TEMPLATE_LABELS[curve_key])
    app.apply_template()

app.notebook.select(1)                    # the agent tab
app.sel = 0
app.refresh_selection()
settle(app)

for q in questions:
    app.chat_entry.delete(0, "end")
    app.chat_entry.insert(0, q)
    app.send_message()
    settle(app)

if app.cands:                          # show the proposal card and the ghost
    app.cand_box.selection_set(0)
    app.insert_candidate()
    settle(app)

print("proposal pending:", bool(app.pending), "| log:", app.plog.summary())
print("captured", out, *shoot(app, out))
app.destroy()
