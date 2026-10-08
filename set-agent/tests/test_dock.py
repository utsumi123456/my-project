"""Docking the panel to rekordbox's window (B): geometry and the follow loop."""
import unittest

from setagent.webui.dock import Docker, Platform, Rect, plan

SCREEN = Rect(0, 25, 2560, 1415)          # work area under a menu bar
LAPTOP = Rect(0, 33, 1512, 873)


class PlanTests(unittest.TestCase):
    def test_side_when_there_is_room(self):
        p = plan(Rect(100, 50, 1600, 1000), 460, [SCREEN], "side")
        self.assertEqual(p.mode, "side")
        self.assertEqual(p.panel, Rect(1700, 50, 460, 1000))

    def test_side_goes_left_when_right_is_full(self):
        p = plan(Rect(600, 50, 1960, 1000), 460, [SCREEN], "side")
        self.assertEqual(p.panel, Rect(140, 50, 460, 1000))

    def test_side_falls_back_inside_on_a_full_width_rekordbox(self):
        p = plan(Rect(0, 33, 1512, 873), 460, [LAPTOP], "side")
        self.assertEqual(p.mode, "inside")
        self.assertEqual(p.panel, Rect(1052, 33, 460, 873))

    def test_height_is_clipped_to_the_screen(self):
        p = plan(Rect(100, 0, 1000, 2000), 400, [SCREEN], "side")
        self.assertEqual((p.panel.y, p.panel.h), (25, 1415))

    def test_split_shares_the_screen(self):
        p = plan(Rect(0, 33, 1512, 873), 460, [LAPTOP], "split")
        self.assertEqual(p.mode, "split")
        self.assertEqual(p.rekordbox, Rect(0, 33, 1052, 873))
        self.assertEqual(p.panel, Rect(1052, 33, 460, 873))

    def test_split_refuses_to_squash_rekordbox(self):
        small = Rect(0, 0, 1200, 800)
        p = plan(small, 460, [small], "split")
        self.assertEqual(p.mode, "inside")

    def test_off(self):
        self.assertIsNone(plan(Rect(0, 0, 1000, 800), 460, [SCREEN], "off"))

    def test_picks_the_screen_rekordbox_is_on(self):
        right = Rect(2560, 0, 1920, 1080)
        p = plan(Rect(2600, 0, 1200, 1000), 460, [SCREEN, right], "side")
        self.assertEqual(p.panel.x, 3800)


class FakeOS(Platform):
    def __init__(self, rb):
        self.rb = rb
        self.panel = Rect(10, 10, 460, 900)
        self.front = True
        self.top = None
        self.moved_rb = []
        self.allow_rb_move = "ok"

    def rekordbox_window(self): return self.rb
    def screens(self): return [SCREEN]
    def frontmost_is_ours(self): return self.front
    def place_panel(self, window, r): self.panel = r
    def panel_rect(self, window): return self.panel
    def set_on_top(self, window, on): self.top = on

    def move_rekordbox(self, r):
        self.moved_rb.append(r)
        if self.allow_rb_move == "ok":
            self.rb = r
        return self.allow_rb_move


class DockerTests(unittest.TestCase):
    def make(self, mode="side", rb=Rect(100, 50, 1600, 1000)):
        self.os = FakeOS(rb)
        self.undocked = []
        return Docker(object(), self.os, mode=mode, panel_w=460, on_undock=self.undocked.append)

    def test_follows_rekordbox_when_it_moves(self):
        d = self.make()
        d.tick()
        self.assertEqual(self.os.panel, Rect(1700, 50, 460, 1000))
        self.os.rb = Rect(200, 80, 1600, 900)
        for _ in range(3):
            d.tick()
        self.assertEqual(self.os.panel, Rect(1800, 80, 460, 900))
        self.assertEqual(d.status()["effective"], "side")
        self.assertEqual(self.undocked, [])

    def test_on_top_only_while_rekordbox_or_panel_is_front(self):
        d = self.make()
        d.tick()
        self.assertTrue(self.os.top)
        self.os.front = False
        d.tick()
        self.assertFalse(self.os.top)

    def test_dragging_the_panel_away_undocks(self):
        d = self.make()
        for _ in range(4):
            d.tick()
        self.os.panel = Rect(500, 300, 460, 1000)          # the DJ drags it
        d.tick()
        self.assertEqual(d.mode, "off")
        self.assertEqual(len(self.undocked), 1)
        self.assertTrue(self.os.top)                       # back to the free-floating panel

    def test_os_nudge_after_placement_is_not_a_drag(self):
        d = self.make()
        d.tick()                                           # placed at x=1700
        self.os.panel = Rect(1700, 80, 460, 970)           # the OS kept it under the menu bar
        for _ in range(4):
            d.tick()
        self.assertEqual(d.mode, "side")
        self.assertEqual(self.undocked, [])

    def test_rekordbox_gone_means_waiting(self):
        d = self.make()
        d.tick()
        self.os.rb = None
        d.tick()
        self.assertEqual(d.status()["effective"], "waiting")
        self.assertFalse(self.os.top)

    def test_split_moves_rekordbox_once(self):
        d = self.make(mode="split", rb=Rect(0, 25, 2560, 1415))
        for _ in range(4):
            d.tick()
        self.assertEqual(len(self.os.moved_rb), 1)
        self.assertEqual(self.os.rb, Rect(0, 25, 2100, 1415))
        self.assertEqual(self.os.panel, Rect(2100, 25, 460, 1415))
        self.assertEqual(d.status()["effective"], "split")

    def test_split_without_permission_says_so_and_still_docks(self):
        d = self.make(mode="split", rb=Rect(0, 25, 2560, 1415))
        self.os.allow_rb_move = "denied"
        d.tick()
        self.assertIn("アクセシビリティ", d.status()["note"])
        self.assertEqual(d.status()["effective"], "inside")
        d.tick()
        self.assertEqual(len(self.os.moved_rb), 1)         # asked once, not every tick

    def test_collapse_keeps_the_right_edge(self):
        d = self.make()
        d.tick()
        d.set_collapsed(True)
        d.tick()
        self.assertEqual(self.os.panel, Rect(1700, 50, 64, 1000))   # hugging rekordbox's right edge

    def test_collapse_inside_keeps_rekordboxs_right_edge(self):
        d = self.make(rb=Rect(0, 33, 2560, 1000))
        d.tick()
        d.set_collapsed(True)
        d.tick()
        self.assertEqual(self.os.panel, Rect(2496, 33, 64, 1000))

    def test_resizing_the_docked_panel_keeps_the_new_width(self):
        d = self.make()
        for _ in range(4):
            d.tick()
        self.os.panel = Rect(1700, 50, 560, 1000)
        for _ in range(4):
            d.tick()
        self.assertEqual(d.panel_w, 560)
        self.assertEqual(self.os.panel, Rect(1700, 50, 560, 1000))


if __name__ == "__main__":
    unittest.main()
