"""The app icon: rekordbox's own icon with its black background turned orange.

  python -m tools.make_icon [out_dir]        # default: build/icon
  python -m tools.make_icon assets/icon      # on a Mac with rekordbox: fix it for every build (CI too)

Set Agent lives beside rekordbox, so its icon is rekordbox's icon, read at
build time from the rekordbox installed on the building machine (no rekordbox
artwork is kept in this repository). The design is left as it is; only the
black background becomes orange, so the two apps sit side by side in the Dock
and the prototype is told apart at a glance (user decision 2026-10-09: no
PROTO lettering, no other change).

The recolour is a straight map from black to orange: rekordbox's icon is black
and white only, so every pixel is a mix of the two, and the same mix of orange
and white keeps the mark's antialiased edges exactly as drawn.

Where no rekordbox is installed (a CI runner, a Windows PC: rekordbox.exe's
icon is not readable with Pillow), a drawn stand-in is used: an orange square
with a white record. SETAGENT_ICON_SRC=<image> overrides the source.

Writes SetAgent.png (1024), SetAgent.icns and SetAgent.ico; prints which
source was used.
"""
from __future__ import annotations

import glob
import os
import plistlib
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
ORANGE = (255, 80, 0)        # #ff5000, the DJ's chosen icon (assets/icon)
WHITE = (255, 255, 255)


# ------------------------------------------------------------------ source

def rekordbox_icon() -> tuple[Image.Image | None, str]:
    """rekordbox's icon on this machine, or (None, why)."""
    env = os.environ.get("SETAGENT_ICON_SRC")
    if env:
        return Image.open(env), env
    if sys.platform == "darwin":
        apps = sorted(glob.glob("/Applications/rekordbox*/rekordbox.app")
                      + glob.glob("/Applications/rekordbox.app"), reverse=True)
        for app in apps:
            res = Path(app) / "Contents" / "Resources"
            name = None
            try:
                with open(Path(app) / "Contents" / "Info.plist", "rb") as f:
                    name = plistlib.load(f).get("CFBundleIconFile")
            except Exception:
                pass
            cands = ([res / name, res / f"{name}.icns"] if name else []) + sorted(res.glob("*.icns"))
            for c in cands:
                if c.is_file():
                    try:
                        im = Image.open(c)
                        if "icns" in c.suffix:
                            # the largest representation the file has
                            im.size = max(im.info.get("sizes", {im.size}), key=lambda s: s[0] * s[-1])
                            im.load()
                        return im, str(c)
                    except Exception:
                        continue
        return None, "rekordbox.app not found"
    return None, "rekordbox's icon is only read on macOS"


# ------------------------------------------------------------------ drawing

def orange_background(src: Image.Image) -> Image.Image:
    """Black -> orange, white stays white, alpha (the icon's outline) untouched."""
    src = src.convert("RGBA")
    if src.size != (SIZE, SIZE):
        src = src.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    t = src.convert("L")                                   # 0 = black, 255 = white
    out = Image.composite(Image.new("RGB", src.size, WHITE), Image.new("RGB", src.size, ORANGE), t)
    # only the opaque body: a soft shadow baked into the transparent margin (Big Sur
    # style icons have one) stays black instead of turning into an orange glow
    alpha = src.getchannel("A")
    body = alpha.point(lambda a: max(0, min(255, (a - 64) * 255 // 191)))
    out = Image.composite(out, src.convert("RGB"), body).convert("RGBA")
    out.putalpha(alpha)
    return out


def _stand_in() -> Image.Image:
    """No rekordbox to start from: an orange macOS-grid square holding a white record."""
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = 100                                  # Apple's icon grid: 824px body on 1024
    d.rounded_rectangle((m, m, SIZE - m, SIZE - m), radius=185, fill=ORANGE)
    c, r = SIZE // 2, 270
    d.ellipse((c - r, c - r, c + r, c + r), fill=WHITE)
    d.ellipse((c - 90, c - 90, c + 90, c + 90), fill=ORANGE)
    d.ellipse((c - 30, c - 30, c + 30, c + 30), fill=WHITE)
    return im


def make(src: Image.Image | None) -> Image.Image:
    return orange_background(src) if src is not None else _stand_in()


def write(out_dir: Path) -> tuple[dict[str, Path], str]:
    src, origin = rekordbox_icon()
    im = make(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"png": out_dir / "SetAgent.png", "icns": out_dir / "SetAgent.icns", "ico": out_dir / "SetAgent.ico"}
    im.save(paths["png"])
    im.save(paths["icns"])
    im.save(paths["ico"], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return paths, (f"from {origin}" if src is not None else f"stand-in ({origin})")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "build" / "icon"
    paths, how = write(out)
    print(f"icon {how}: {paths['png'].parent}")
