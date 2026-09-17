import os
import tempfile
import unittest

from setagent.diagnostics import Report, run


class ReportTests(unittest.TestCase):
    def test_marks_and_failure_list(self):
        r = Report()
        r.add("good", True, "fine")
        r.add("bad", False, "broken")
        r.add("unknown", None, "cannot tell")
        self.assertEqual([c.name for c in r.failed], ["bad"])
        text = r.text()
        self.assertIn("OK  ", text)
        self.assertIn("NG  ", text)
        self.assertIn("--  ", text)

    def test_clean_report_says_so(self):
        r = Report()
        r.add("good", True)
        self.assertIn("致命的な問題はありません", r.text())


class RunTests(unittest.TestCase):
    def setUp(self):
        # the decrypted cache now lives under SETAGENT_HOME; a still-open SQLite
        # handle keeps the file locked on Windows until it is collected
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.saved_home = os.environ.get("SETAGENT_HOME")
        self.saved_db = os.environ.pop("SETAGENT_MASTER_DB", None)
        os.environ["SETAGENT_HOME"] = self.dir.name

    def tearDown(self):
        if self.saved_home is None:
            os.environ.pop("SETAGENT_HOME", None)
        else:
            os.environ["SETAGENT_HOME"] = self.saved_home
        if self.saved_db is not None:
            os.environ["SETAGENT_MASTER_DB"] = self.saved_db
        import gc
        gc.collect()
        self.dir.cleanup()

    def test_missing_library_is_reported_not_raised(self):
        rep = run(master_db=str(os.path.join(self.dir.name, "nope.db")))
        self.assertTrue(rep.failed)
        self.assertIn("master.db", rep.text())
        self.assertTrue(rep.hints)

    def test_unreadable_file_is_reported_not_raised(self):
        junk = os.path.join(self.dir.name, "master.db")
        with open(junk, "wb") as fh:
            fh.write(b"not an encrypted database")
        rep = run(master_db=junk)
        self.assertTrue(rep.failed)
        self.assertIn("復号", rep.text())


if __name__ == "__main__":
    unittest.main()
