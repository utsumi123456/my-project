# my-project

Prototypes, one folder each. Every prototype is self-contained: its own README,
tests, build script and handoff notes live inside its folder.

| Folder | What it is | Status |
|---|---|---|
| [`setagent/`](setagent/) | **Set Agent** — a read-only rekordbox companion that shows a DJ the predicted length and energy shape of a playlist while they edit it in rekordbox, and proposes what to trim or drop. Python + WebView2, Windows. | prototype in team trial (2026-09) |

Conventions for adding a prototype:

- one top-level folder, kebab-case or the product's own name
- a `README.md` inside with how to run, test and build it
- a `HANDOFF.md` inside if the work is meant to be picked up by someone else later
- no build outputs in git (each folder carries its own `.gitignore`)

License: MIT (see [LICENSE](LICENSE)), unless a prototype's folder says otherwise.
