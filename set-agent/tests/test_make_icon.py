"""The app icon: two-tone in the panel's colours with a PROTO strip, from any source."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from tools import make_icon as M


def dark_icon():
    """A stand-in for rekordbox's icon: a dark rounded square with a light mark."""
    im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((100, 100, 924, 924), radius=185, fill=(20, 20, 24))
    d.ellipse((312, 282, 712, 682), fill=(240, 240, 240))
    return im


class IconTests(unittest.TestCase):
    def test_recoloured_from_a_source(self):
        im = M.make(dark_icon())
        self.assertEqual(im.size, (1024, 1024))
        self.assertEqual(im.getpixel((200, 200))[:3], M.AMBER)        # dark body -> amber
        self.assertEqual(im.getpixel((512, 482))[:3], M.CARBON)       # light mark -> carbon
        self.assertEqual(im.getpixel((512, 900))[:3], M.CARBON)       # the PROTO strip at the foot
        self.assertEqual(im.getpixel((20, 20))[3], 0)                 # the margin stays transparent

    def test_stand_in_without_rekordbox(self):
        im = M.make(None)
        self.assertEqual(im.getpixel((150, 300))[:3], M.AMBER)
        self.assertEqual(im.getpixel((20, 20))[3], 0)

    def test_writes_every_format(self):
        with tempfile.TemporaryDirectory() as t:
            paths, _ = M.write(Path(t))
            for k in ("png", "icns", "ico"):
                self.assertTrue(paths[k].stat().st_size > 1000, k)
            with Image.open(paths["ico"]) as ico:
                self.assertIn((256, 256), ico.info["sizes"])


if __name__ == "__main__":
    unittest.main()
