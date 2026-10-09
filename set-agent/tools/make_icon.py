"""The app icon: rekordbox's own icon, recoloured so it reads as a prototype.

  python -m tools.make_icon [out_dir]        # default: build/icon
  python -m tools.make_icon assets/icon      # on a Mac with rekordbox: fix it for every build (CI too)

Set Agent lives beside rekordbox, so its icon starts from rekordbox's -- read
at build time from the rekordbox installed on the building machine, so no
rekordbox artwork is kept in this repository. It is turned into a two-tone in
the panel's own state colours (dark parts amber #f5a800, light parts carbon
#0f0e12: the inverse of rekordbox's dark icon, and the "caution" amber of a
prototype) with a carbon "PROTO" strip across the foot.

Where no rekordbox is installed (a CI runner, a Windows PC: rekordbox.exe's
icon is not readable with Pillow), a drawn stand-in is used: the same amber
square with a carbon record and the same strip. SETAGENT_ICON_SRC=<image>
overrides the source.

Writes SetAgent.png (1024), SetAgent.icns and SetAgent.ico; prints which
source was used.
"""
from __future__ import annotations

import glob
import os
import plistlib
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

SIZE = 1024
AMBER = (245, 168, 0)        # --caution
CARBON = (15, 14, 18)        # --carbon
PAPER = (246, 248, 247)      # --page


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
                        if hasattr(im, "size") and "icns" in c.suffix:
                            # the largest representation the file has
                            im.size = max(im.info.get("sizes", {im.size}), key=lambda s: s[0] * s[-1])
                            im.load()
                        return im, str(c)
                    except Exception:
                        continue
        return None, "rekordbox.app not found"
    return None, "rekordbox's icon is only read on macOS"


# ------------------------------------------------------------------ drawing

def _font(px: int):
    for f in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/HelveticaNeue.ttc",
              "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, px)
            except Exception:
                pass
    try:
        return ImageFont.load_default(px)
    except TypeError:                       # Pillow < 10.1
        return ImageFont.load_default()


def _two_tone(src: Image.Image) -> Image.Image:
    """Dark -> amber, light -> carbon; the source's own alpha keeps its outline."""
    src = src.convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    body = src.getchannel("A").point(lambda a: 255 if a > 128 else 0)
    lum = ImageOps.autocontrast(src.convert("L"), cutoff=1, mask=body)   # stretch over the icon, not its margin
    out = ImageOps.colorize(lum, black=AMBER, white=CARBON).convert("RGBA")
    out.putalpha(src.getchannel("A"))
    return out


def _stand_in() -> Image.Image:
    """No rekordbox to start from: an amber macOS-grid square holding a record."""
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = 100                                  # Apple's icon grid: 824px body on 1024
    d.rounded_rectangle((m, m, SIZE - m, SIZE - m), radius=185, fill=AMBER)
    c, cy, r = SIZE // 2, 450, 250           # clear of the PROTO strip at the foot
    d.ellipse((c - r, cy - r, c + r, cy + r), fill=CARBON)
    for k in (195, 145):                     # grooves
        d.ellipse((c - k, cy - k, c + k, cy + k), outline=AMBER, width=6)
    d.ellipse((c - 60, cy - 60, c + 60, cy + 60), fill=AMBER)
    d.ellipse((c - 14, cy - 14, c + 14, cy + 14), fill=CARBON)
    return im


def _proto_strip(im: Image.Image) -> Image.Image:
    """A carbon strip with PROTO across the foot, clipped to the icon's outline.
    Flush with the bottom edge, below where an app icon's mark sits."""
    alpha = im.getchannel("A")
    box = alpha.point(lambda a: 255 if a > 128 else 0).getbbox() or (0, 0, SIZE, SIZE)
    x0, y0, x1, y1 = box
    h = round((y1 - y0) * 0.16)
    top = y1 - h
    band = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    d.rectangle((x0, top, x1, top + h), fill=CARBON + (255,))
    f = _font(round(h * 0.52))
    text = "PROTO"
    tw = d.textlength(text, font=f)
    # wide tracking, the way TE letters its labels
    track = round(h * 0.16)
    total = tw + track * (len(text) - 1)
    x = (x0 + x1 - total) / 2
    asc, desc = f.getmetrics()
    y = top + (h - (asc + desc)) / 2
    for ch in text:
        d.text((x, y), ch, font=f, fill=PAPER + (255,))
        x += d.textlength(ch, font=f) + track
    band.putalpha(ImageChops.multiply(band.getchannel("A"), alpha))
    return Image.alpha_composite(im, band)


def make(src: Image.Image | None) -> Image.Image:
    return _proto_strip(_two_tone(src) if src is not None else _stand_in())


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
