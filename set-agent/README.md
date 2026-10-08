# Set Agent — rekordbox companion (prototype)

Reads a rekordbox 6/7 library on any PC (auto-detects `%APPDATA%\Pioneer\rekordbox\master.db`),
decrypts it read-only without pyrekordbox (including the `-wal`, so edits made while
rekordbox is open are visible), parses ANLZ beat grids and phrase analysis, and shows the
DJ what a playlist adds up to: **predicted set length** against a target, energy
development, milestones and section budgets, and an advisory agent that proposes range
trims and removal candidates. It follows edits made in rekordbox automatically.

Read-only by default. The one write (2026-10-08) is **「rekordbox へ書き込む」**: on the
DJ's button it puts the set's track order into rekordbox as a playlist inside a root
folder named **Set Agent** — never anything else (tracks, cues, analysis and every
other playlist stay untouched), only while rekordbox is closed (or "write when it
quits" / "quit → write → relaunch"), always after a backup and followed by a read-back
that restores the backup on any mismatch. The agent can only propose that write.

The panel **docks to rekordbox's window** (beside it, inside its right edge, or
side by side with rekordbox resized), stays above rekordbox only while rekordbox is
the active app, and can collapse to a strip showing the predicted length. The agent
also reads the DJ's **history** (sessions, what was played after what) — the
rekordbox-mcp tool surface, reimplemented read-only. Design:
`docs/rekordbox_integration_2026-10-08.md`.

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
