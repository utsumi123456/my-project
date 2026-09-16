import os
import tempfile
import unittest
from pathlib import Path

from setagent.rekordbox.library import find_master_db
from setagent.rekordbox.masterdb import Track


class LibraryTests(unittest.TestCase):
    def test_find_master_db_env_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "master.db"; p.write_bytes(b"x")
            os.environ["SETAGENT_MASTER_DB"] = str(p)
            try:
                self.assertEqual(find_master_db(), p)
            finally:
                del os.environ["SETAGENT_MASTER_DB"]

    def test_find_master_db_explicit_missing(self):
        with self.assertRaises(FileNotFoundError):
            find_master_db("/nonexistent/master.db")

    def test_cloud_detection(self):
        base = dict(id="1", title="t", artist="", bpm=160.0, length_s=1, key="", analysis_path=None, analysed=0)
        self.assertTrue(Track(**base, folder_path="/contents_123/x/y.mp3").is_cloud)
        self.assertTrue(Track(**base, folder_path="spotify:track:abc", file_type=25).is_cloud)
        self.assertFalse(Track(**base, folder_path="C:/Users/me/Music/y.mp3", file_type=1).is_cloud)


if __name__ == "__main__":
    unittest.main()
