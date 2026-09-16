# Set Agent — rekordbox companion (prototype)

Reads a rekordbox 6/7 library on any PC (auto-detects `%APPDATA%\Pioneer\rekordbox\master.db`),
decrypts it read-only without pyrekordbox (including the `-wal`, so edits made while
rekordbox is open are visible), parses ANLZ beat grids and phrase analysis, and shows the
DJ what a playlist adds up to: **predicted set length** against a target, energy
development, milestones and section budgets, and an advisory agent that proposes range
trims and removal candidates. It follows edits made in rekordbox automatically.

Read-only by design: never writes to `master.db`, the ANLZ files, or rekordbox itself.
All editing happens in rekordbox.

## Run

    python run_setagent.py                        # the panel (WebView2)
    python run_setagent.py --doctor               # environment check
    python -m setagent.cli doctor                 # same, on the console
    python -m setagent.cli playlists
    python -m setagent.cli timeline "acid" --target 60:00 --preset one_drop --cap 32
    python -m setagent.cli agent    "acid" --ask "バランスどう？"

Requires Python 3.11+, `cryptography`, `pywebview` and `Pillow`. Tests: `python -m unittest discover -s tests -q`.

## Build the distributable

    python build.py            # tests -> exe -> dist/SetAgent.exe + readme

## Layout

    setagent/analysis/   timing, energy, phrases, target curve, milestone sections
    setagent/domain/     Set Draft + Command/History (every edit is reversible)
    setagent/agent/      tools, change sets, deterministic advisor, recommender, optional LLM
    setagent/rekordbox/  master.db (+WAL replay), ANLZ, library discovery
    setagent/webui/      the panel: index.html, JS<->Python bridge, entry point
    setagent/gui/        the old tkinter workbench (fallback, --classic)
    tools/               decryptor, WebView2 probes (verification without screenshots)

The optional LLM front end is off unless `SETAGENT_LLM_KEY` is set; everything
works without it. See `HANDOFF.md` for project state and `dist_readme/` for what
the team receives.
