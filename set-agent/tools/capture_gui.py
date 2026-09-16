"""Render the workbench and capture its own window (see tools/winshot.py).

  python -m tools.capture_gui <out.png> [playlist] [curve_key] [index:mm:ss ...]
"""
from __future__ import annotations

import sys

import setagent.gui.timeline as T
from setagent.rekordbox.library import Library
from tools.winshot import settle, shoot

out = sys.argv[1] if len(sys.argv) > 1 else "gui_capture.png"
playlist = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
curve_key = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None
marks = sys.argv[4:]

lib = Library.open()
app = T.App(lib, playlist=playlist)
app.state("zoomed")
settle(app)

if curve_key:
    from setagent.analysis.curve import TEMPLATE_LABELS
    app.curve_var.set(TEMPLATE_LABELS[curve_key])
    app.apply_template()

for m in marks:                      # "12:45:00" -> track #12 should land at 45:00
    from setagent.domain.draft import SetMilestone
    idx, mm, ss = m.split(":")
    e = app.draft.tracks[int(idx)]
    app.history.run(SetMilestone(e.track_id, True, int(mm) * 60 + int(ss)))
if marks:
    app.sel = int(marks[0].split(":")[0])
    app.recompute()

print("captured", out, *shoot(app, out))
app.destroy()
