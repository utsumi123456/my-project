"""The panel comes back where the DJ left it -- unless that place is gone."""
import unittest
from types import SimpleNamespace

from setagent.settings import Settings
from setagent.webui.app import DEFAULT, MIN_SIZE, saved_geometry

MAIN = SimpleNamespace(x=0, y=0, width=1920, height=1200)
SIDE = SimpleNamespace(x=1920, y=0, width=1280, height=1024)


def cfg(window: str) -> Settings:
    s = Settings()
    s.window = window
    return s


class SavedGeometryTest(unittest.TestCase):
    def test_nothing_saved_gives_default_size_and_no_position(self):
        self.assertEqual(saved_geometry(cfg(""), [MAIN]), DEFAULT)

    def test_garbage_is_ignored(self):
        self.assertEqual(saved_geometry(cfg("a,b"), [MAIN]), DEFAULT)
        self.assertEqual(saved_geometry(cfg("1,2,3"), [MAIN]), DEFAULT)

    def test_on_screen_geometry_is_restored(self):
        self.assertEqual(saved_geometry(cfg("1400,80,460,940"), [MAIN]),
                         dict(x=1400, y=80, width=460, height=940))

    def test_second_monitor_counts_while_connected(self):
        g = dict(x=2100, y=100, width=460, height=900)
        self.assertEqual(saved_geometry(cfg("2100,100,460,900"), [MAIN, SIDE]), g)
        self.assertEqual(saved_geometry(cfg("2100,100,460,900"), [MAIN]), DEFAULT)

    def test_mostly_off_screen_falls_back(self):
        self.assertEqual(saved_geometry(cfg("1800,1150,460,940"), [MAIN]), DEFAULT)
        self.assertEqual(saved_geometry(cfg("-400,100,460,940"), [MAIN]), DEFAULT)

    def test_size_never_below_minimum(self):
        g = saved_geometry(cfg("100,100,200,200"), [MAIN])
        self.assertEqual((g["width"], g["height"]), MIN_SIZE)
