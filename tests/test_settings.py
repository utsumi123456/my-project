import json
import os
import tempfile
import unittest
from pathlib import Path

from setagent.settings import Settings, app_home


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.saved = os.environ.get("SETAGENT_HOME")
        os.environ["SETAGENT_HOME"] = self.dir.name

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("SETAGENT_HOME", None)
        else:
            os.environ["SETAGENT_HOME"] = self.saved
        self.dir.cleanup()

    def test_home_follows_the_override(self):
        self.assertEqual(app_home(), Path(self.dir.name))

    def test_defaults_when_nothing_is_saved(self):
        s = Settings.load()
        self.assertEqual(s.target, "60:00")
        self.assertEqual(s.preset, "one_drop")
        self.assertTrue(s.cap32)

    def test_round_trip(self):
        s = Settings(playlist="acid", target="45:00", preset="two_drop", cap32=False,
                     curve="peak_late (後半ピーク)", level="proactive")
        self.assertTrue(s.save())
        again = Settings.load()
        self.assertEqual(again.playlist, "acid")
        self.assertEqual(again.target, "45:00")
        self.assertFalse(again.cap32)
        self.assertEqual(again.level, "proactive")

    def test_corrupt_file_falls_back_to_defaults(self):
        p = Settings.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(Settings.load().target, "60:00")

    def test_unknown_and_wrongly_typed_keys_are_ignored(self):
        p = Settings.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"target": 45, "nonsense": True, "playlist": "acid"}),
                     encoding="utf-8")
        s = Settings.load()
        self.assertEqual(s.target, "60:00")      # wrong type -> default
        self.assertEqual(s.playlist, "acid")     # good value still kept
        self.assertFalse(hasattr(s, "nonsense"))

    def test_saving_into_an_unwritable_place_does_not_raise(self):
        blocked = Path(self.dir.name) / "blocked"
        blocked.write_text("I am a file, not a directory", encoding="utf-8")
        os.environ["SETAGENT_HOME"] = str(blocked)
        self.assertFalse(Settings().save())      # returns False instead of raising


if __name__ == "__main__":
    unittest.main()
