# Third-party notices

The distributed device file (`TuneScope_x.y.z.amxd`) bundles the following third-party software.

## essentia.js

- Version: 0.1.3
- Copyright: Music Technology Group, Universitat Pompeu Fabra
- License: GNU Affero General Public License v3.0 (AGPL-3.0)
- Source: https://github.com/MTG/essentia.js

essentia.js (and the Essentia C++ library it is compiled from) is bundled into the
analysis worker inside `analyzer.js` of the frozen device. Because of this, the
TuneScope device as distributed is licensed under AGPL-3.0 as a whole (see `LICENSE`).
The complete corresponding source of TuneScope is this directory of the repository;
the essentia.js source is available at the URL above.

## Build-time only (not distributed)

| Package | License | Use |
|---|---|---|
| esbuild | MIT | Bundles the analysis worker into a single file |
| ffmpeg-static (FFmpeg) | GPL-3.0 (binary) | Decodes audio for the offline accuracy evaluation in `tools/` |
