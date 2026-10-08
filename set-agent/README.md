# Set Agent — rekordbox companion (prototype)

Reads a rekordbox 6/7 library on any PC (auto-detects `%APPDATA%\Pioneer\rekordbox\master.db`),
decrypts it read-only without pyrekordbox (including the `-wal`, so edits made while
rekordbox is open are visible), parses ANLZ beat grids and phrase analysis, and shows the
DJ what a playlist adds up to: **predicted set length** against a target, energy
development, milestones and section budgets, and an advisory agent that proposes range
trims and removal candidates. It follows edits made in rekordbox automatically.

It follows the playlist selected in rekordbox (read through the OS accessibility
API, `setagent/rekordbox/selection.py`) and never edits it. On request it builds an
**improved version** at an intervention level the DJ picks (light / standard / bold,
`setagent/agent/improve.py`) and writes it into rekordbox's **Set Agent** folder as a
new playlist -- only while rekordbox is closed, after a backup, verified by read-back.
The panel docks to rekordbox's window. The agent chat (model picker; Opus 5.5 by
default) is the deeper layer: taste analysis from history/imports, concept-matched
playlists, tag edits (proposed, written only on approval). Design:
`docs/redesign_2026-10-09.md`, `docs/rekordbox_integration_2026-10-08.md`.

## Run

    python run_setagent.py                        # the panel (WebView2)
    python run_setagent.py --doctor               # environment check
    python -m setagent.cli doctor                 # same, on the console
    python -m setagent.cli playlists
    python -m setagent.cli timeline "acid" --target 60:00 --preset one_drop --cap 32
    python -m setagent.cli agent    "acid" --ask "バランスどう？"

Requires Python 3.11+, `cryptography`, `pywebview` and `Pillow`; `pyrekordbox` (optional)
enables the write-back. Tests: `python -m unittest discover -s tests -q`.
UI against a real Api in a browser (use a *copy* of the library):
`SETAGENT_MASTER_DB=/path/to/copy/master.db python -m tools.webui_live acid`.

## Build the distributable

    python build.py            # tests -> exe -> dist/SetAgent.exe + readme

## Layout

    setagent/analysis/   timing, energy, phrases, target curve, milestone sections
    setagent/domain/     Set Draft + Command/History (every edit is reversible)
    setagent/agent/      tools, change sets, deterministic advisor, recommender, optional LLM
    setagent/rekordbox/  master.db (+WAL replay), ANLZ, library discovery,
                         insights (history/stats), writeback + publisher (the one write)
    setagent/webui/      the panel: index.html, JS<->Python bridge, entry point, dock
    setagent/gui/        the old tkinter workbench (fallback, --classic)
    tools/               decryptor, WebView2 probes (verification without screenshots)

The optional LLM front end is off unless `SETAGENT_LLM_KEY` is set; everything
works without it. See `HANDOFF.md` for project state and `dist_readme/` for what
the team receives.
