"""build.py on macOS: what keeps the Dock icon and the Accessibility permission right.

Two regressions this guards (2026-10-09, both seen on the DJ's Mac):
  * after every rebuild, following rekordbox stopped: ad-hoc signatures pin the
    Accessibility permission to the code hash. The bundle must be re-signed with
    a designated requirement naming only the bundle id, and the build must stop
    if that did not take.
  * the Dock showed a generic icon: onefile .app bundles run a second process.
    macOS builds must be onedir, carry the chosen icon, and bundle the PNG the
    app sets as its Dock icon at runtime.
"""
import types
import unittest
from pathlib import Path
from unittest import mock

import build


def fake_run(dr_text):
    calls = []

    def run(cmd, **kw):
        calls.append(list(cmd))
        out = dr_text if cmd[:2] == ["codesign", "-d"] else ""
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="Executable=/x/SetAgent\n")
    return run, calls


class MacBuildTests(unittest.TestCase):
    def build(self, dr_text):
        run, calls = fake_run(dr_text)
        with mock.patch.object(build, "MAC", True), mock.patch.object(build, "WIN", False), \
                mock.patch.object(build.subprocess, "run", run), mock.patch("builtins.print"):
            build.build_exe()
        return calls

    def test_onedir_icon_and_stable_signature(self):
        calls = self.build('designated => identifier "jp.alphatheta.setagent"\n')
        pyi = next(c for c in calls if "PyInstaller" in c)
        self.assertIn("--onedir", pyi)
        self.assertNotIn("--onefile", pyi)
        icons = build.ROOT / "assets" / "icon"
        self.assertEqual(Path(pyi[pyi.index("--icon") + 1]), icons / "SetAgent.icns")   # Path: \\ on Windows
        self.assertTrue(any(a.startswith(str(icons / "SetAgent.png")) for a in pyi))
        sign = next(c for c in calls if c[:2] == ["codesign", "--force"])
        self.assertIn('=designated => identifier "jp.alphatheta.setagent"', sign)

    def test_build_stops_if_the_requirement_did_not_take(self):
        with self.assertRaises(SystemExit):
            self.build("designated => cdhash H\"0123abcd\"\n")


class InstallTests(unittest.TestCase):
    """build.py --install: quit, swap the bundle in, refresh the icon, start."""

    def test_quits_swaps_refreshes_and_starts(self):
        import shutil
        import tempfile
        calls = []

        def run(cmd, **kw):
            calls.append(list(cmd))
            if cmd[0] == "ditto":                         # the copy, for real
                shutil.copytree(cmd[1], cmd[2])
            rc = 1 if cmd[0] == "pgrep" else 0           # the old app has quit
            return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as d:
            src, dest = Path(d) / "new" / "SetAgent.app", Path(d) / "Applications" / "SetAgent.app"
            (src / "Contents").mkdir(parents=True)
            (src / "Contents" / "new").write_text("1")
            (dest / "Contents").mkdir(parents=True)
            (dest / "Contents" / "old").write_text("1")
            with mock.patch.object(build.subprocess, "run", run), mock.patch("builtins.print"):
                build.install_mac(src, dest)
            self.assertTrue((dest / "Contents" / "new").exists())
            self.assertFalse((dest / "Contents" / "old").exists())
            self.assertFalse(dest.with_name(".SetAgent.app.new").exists())
        order = [c[0] for c in calls]
        self.assertEqual(order[0], "osascript")                       # quit first
        self.assertLess(order.index("ditto"), order.index("killall"))
        self.assertEqual(calls[-1][0], "open")                        # start last
        self.assertIn(["killall", "Dock"], calls)


class IconAssetTests(unittest.TestCase):
    def test_the_chosen_icon_is_committed_and_found_at_runtime(self):
        from PIL import Image
        from setagent.webui.app import icon_path
        for ext in ("png", "icns", "ico"):
            self.assertTrue((build.ROOT / "assets" / "icon" / f"SetAgent.{ext}").exists(), ext)
        with Image.open(build.ROOT / "assets" / "icon" / "SetAgent.png") as im:
            self.assertEqual(im.size, (1024, 1024))
            self.assertEqual(im.getpixel((10, 10))[3], 0)               # transparent margin
            self.assertEqual(im.getpixel((130, 512)), (255, 80, 0, 255))  # orange body (left border)
        self.assertTrue(icon_path().endswith("SetAgent.png"))


if __name__ == "__main__":
    unittest.main()
