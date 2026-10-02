# my-project

Prototypes, one folder each. Every prototype is self-contained: its own README,
tests, build script and handoff notes live inside its folder.

| Folder | What it is | Status |
|---|---|---|
| [`set-agent/`](set-agent/) | **Set Agent** — a read-only rekordbox companion that shows a DJ the predicted length and energy shape of a playlist while they edit it in rekordbox, and proposes what to trim or drop. Python + WebView2, Windows. | prototype in team trial (2026-09) |
| [`tunescope/`](tunescope/) | **TuneScope** — a Max for Live audio effect that detects BPM and key in real time (Camelot / Open Key, tempo sync, clip tagging). Ships as a single frozen `.amxd` built without Max. AGPL-3.0 (bundles essentia.js). | v1.0.0 released (2026-10) |

Conventions for adding a prototype:

- one top-level folder in kebab-case named after the product (`set-agent/`); a Python
  package inside keeps its import name (`set-agent/setagent/`), so folder and package never share a spelling
- a `README.md` inside with how to run, test and build it
- a `HANDOFF.md` inside if the work is meant to be picked up by someone else later
- no build outputs in git (each folder carries its own `.gitignore`)

License: MIT (see [LICENSE](LICENSE)), unless a prototype's folder says otherwise.
