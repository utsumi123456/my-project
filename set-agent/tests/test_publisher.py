"""When a write-back fires: now / when rekordbox quits / quit -> write -> relaunch."""
import threading
import unittest
from pathlib import Path

from setagent.rekordbox.publisher import Publisher
from setagent.rekordbox.writeback import PublishPlan, PublishResult


class FakeWriter:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []
        self.running = lambda: False

    def publish(self, master_db, plan):
        self.calls.append((master_db, plan.name))
        return PublishResult(self.ok, plan.name, tracks=len(plan.track_ids), backup_id="b1",
                             error="" if self.ok else "boom")


def plan(name="acid"):
    return PublishPlan(name, ["1", "2"])


class PublisherTests(unittest.TestCase):
    def make(self, writer=None, running=lambda: False, quit_app=None, launch=None):
        self.launched = []
        w = writer or FakeWriter()
        p = Publisher(w, lambda: Path("/x/master.db"), running=running,
                      quit_app=quit_app or (lambda force=False: {"ok": True, "action": "quit", "exe": "/rb"}),
                      launch=launch or (lambda exe=None: self.launched.append(exe) or {"ok": True}),
                      poll_s=0.01)
        return p, w

    def test_now_writes_once_and_leaves_a_notice(self):
        p, w = self.make()
        self.assertTrue(p.submit(plan(), "now")["ok"])
        self.assertTrue(p.wait(5))
        self.assertEqual(len(w.calls), 1)
        st = p.status()
        self.assertFalse(st["active"])
        self.assertTrue(st["last"]["ok"])
        self.assertIn("作成しました", p.notices[-1])

    def test_when_closed_waits_for_rekordbox_to_quit(self):
        state = {"running": True}
        p, w = self.make(running=lambda: state["running"])
        p.submit(plan(), "when_closed")
        self.assertFalse(p.wait(0.15))                 # still waiting
        self.assertEqual(w.calls, [])
        self.assertEqual(p.status()["state"], "waiting")
        state["running"] = False
        self.assertTrue(p.wait(5))
        self.assertEqual(len(w.calls), 1)

    def test_queued_job_can_be_cancelled(self):
        p, w = self.make(running=lambda: True)
        p.submit(plan(), "when_closed")
        self.assertTrue(p.cancel()["ok"])
        self.assertTrue(p.wait(2))
        self.assertEqual(w.calls, [])
        self.assertEqual(p.status()["state"], "cancelled")

    def test_quit_write_relaunch_relaunches_the_same_exe(self):
        p, w = self.make()
        p.submit(plan(), "quit_write_relaunch")
        self.assertTrue(p.wait(5))
        self.assertEqual(len(w.calls), 1)
        self.assertEqual(self.launched, ["/rb"])

    def test_refused_quit_never_writes_and_asks_for_force(self):
        p, w = self.make(quit_app=lambda force=False: {"ok": force, "action": "still_running" if not force else "quit",
                                                        "error": "dialog"})
        p.submit(plan(), "quit_write_relaunch")
        self.assertTrue(p.wait(5))
        self.assertEqual(w.calls, [])
        self.assertEqual(self.launched, [])
        self.assertTrue(p.status()["needs_force"])
        p.submit(plan(), "quit_write_relaunch", force=True)   # the second, explicit confirm
        self.assertTrue(p.wait(5))
        self.assertEqual(len(w.calls), 1)

    def test_failed_write_still_relaunches_rekordbox(self):
        p, w = self.make(writer=FakeWriter(ok=False))
        p.submit(plan(), "quit_write_relaunch")
        self.assertTrue(p.wait(5))
        self.assertEqual(self.launched, ["/rb"])
        self.assertFalse(p.status()["last"]["ok"])
        self.assertIn("できませんでした", p.notices[-1])

    def test_new_submission_replaces_a_queued_one(self):
        p, w = self.make(running=lambda: True)
        p.submit(plan("a"), "when_closed")
        p.submit(plan("b"), "now")
        self.assertTrue(p.wait(5))
        self.assertEqual([c[1] for c in w.calls], ["b"])


if __name__ == "__main__":
    unittest.main()
