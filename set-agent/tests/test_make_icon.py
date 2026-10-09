"""The app icon: rekordbox's icon with only its black background turned orange."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from tools import make_icon as M


def rekordbox_like():
    """Black rounded square with a white mark, and a faint shadow in the margin."""
    im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((100, 930, 924, 960), fill=(0, 0, 0, 40))          # baked-in shadow
    d.rounded_rectangle((100, 100, 924, 924), radius=185, fill=(0, 0, 0, 255))
    d.ellipse((312, 282, 712, 682), fill=(255, 255, 255, 255))
    return im


class IconTests(unittest.TestCase):
    def test_only_the_black_background_turns_orange(self):
        im = M.make(rekordbox_like())
        self.assertEqual(im.size, (1024, 1024))
        self.assertEqual(im.getpixel((200, 200)), M.ORANGE + (255,))   # background
        self.assertEqual(im.getpixel((512, 482)), M.WHITE + (255,))    # the mark, untouched
        self.assertEqual(im.getpixel((20, 20))[3], 0)                  # margin stays transparent
        self.assertEqual(im.getpixel((512, 945)), (0, 0, 0, 40))        # the shadow is not recoloured

    def test_stand_in_without_rekordbox(self):
        im = M.make(None)
        self.assertEqual(im.getpixel((150, 300))[:3], M.ORANGE)
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
