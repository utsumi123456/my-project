# Set Agent — rekordbox companion (prototype)

Reads a rekordbox 6/7 library on any PC (auto-detects `%APPDATA%\Pioneer\rekordbox\master.db`),
decrypts it read-only without pyrekordbox, parses ANLZ beat grids and phrase analysis, and
turns a playlist into an editable **Set Draft**: length management, energy development,
milestones and section budgets, an advisory agent, and write-back as rekordbox XML.

Never writes to `master.db` or to the ANLZ files.

## Run

    python -m setagent.gui.timeline               # the workbench
    python -m setagent.gui.timeline --doctor      # environment check
    python -m setagent.cli doctor                 # same, on the console
    python -m setagent.cli playlists
    python -m setagent.cli timeline "acid" --target 60:00 --preset one_drop --cap 32
    python -m setagent.cli agent    "acid" --ask "バランスどう？"
    python -m setagent.cli export   "acid" --preset one_drop --dry-run

Requires Python 3.11+ and `cryptography`. Tests: `python -m unittest discover -s tests -q`.

## Build the distributable

    python build.py            # tests -> exe -> dist/SetAgent_<date>.zip

## Layout

    setagent/analysis/   timing, energy, phrases, target curve, milestone sections
    setagent/domain/     Set Draft + Command/History (every edit is reversible)
    setagent/agent/      tools, change sets, deterministic advisor, recommender, optional LLM
    setagent/rekordbox/  master.db, ANLZ, library discovery, XML export
    setagent/gui/        the single-window workbench
    tools/               decryptor, window capture helpers

The optional LLM front end is off unless `SETAGENT_LLM_KEY` is set; everything
works without it. See `HANDOFF.md` for project state and `dist_readme/` for what
the team receives.
