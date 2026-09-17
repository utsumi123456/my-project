"""Build the distributable the team receives.

  python build.py           build + lay out dist/
  python build.py --skip    lay out only (reuse build/exe/)

Windows: dist/SetAgent.exe  (one file, double-click) next to dist/はじめに.md.
macOS:   dist/SetAgent-macOS.zip holding SetAgent.app (PyInstaller --windowed),
         built on a Mac or by the GitHub Actions workflow (.github/workflows/build.yml).
PyInstaller's own output goes under build/ so dist/ never holds two builds.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
WORK = ROOT / "build" / "exe"
WIN = sys.platform.startswith("win")
MAC = sys.platform == "darwin"
EXE = WORK / ("SetAgent.exe" if WIN else "SetAgent")
APP = WORK / "SetAgent.app"


def build_exe() -> None:
    # index.html must ride along: it *is* the UI. webview.platforms.winforms is
    # imported lazily by pywebview, so PyInstaller cannot see it on its own.
    ui = ROOT / "setagent" / "webui" / "index.html"
    if not ui.exists():
        raise SystemExit(f"{ui} がありません。UI を同梱できません")
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--clean",
           "--name", "SetAgent", "--paths", ".",
           "--distpath", str(WORK), "--workpath", str(ROOT / "build" / "pyinstaller"),
           "--add-data", f"{ui}{os.pathsep}setagent/webui",
           "--hidden-import", "tools.decrypt_masterdb"]
    if WIN:
        cmd += ["--hidden-import", "webview.platforms.winforms", "--hidden-import", "clr_loader"]
    elif MAC:
        # pywebview drives WKWebView through pyobjc; PyInstaller cannot see the lazy import
        cmd += ["--hidden-import", "webview.platforms.cocoa", "--osx-bundle-identifier", "jp.alphatheta.setagent"]
    else:
        cmd += ["--hidden-import", "webview.platforms.gtk"]
    cmd.append("run_setagent.py")
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def package() -> Path:
    src = APP if MAC and APP.exists() else EXE
    if not src.exists():
        raise SystemExit(f"{src} がありません。--skip を外して先にビルドしてください")
    DIST.mkdir(exist_ok=True)
    for old in DIST.glob("*"):
        if old.is_file():
            old.unlink()                        # dist/ is exactly what gets handed out
    if MAC:
        # an .app is a folder; hand out a zip (ditto keeps the bundle's attributes)
        out = DIST / "SetAgent-macOS.zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(src), str(out)], check=True)
    else:
        out = DIST / src.name
        shutil.copy2(src, out)
    for f in sorted((ROOT / "dist_readme").glob("*")):
        shutil.copy2(f, DIST / f.name)
    print(f"{out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def main() -> int:
    if "--no-tests" not in sys.argv:            # CI runs them as its own step
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                           cwd=ROOT)
        if r.returncode:
            print("テストが失敗しています。配布物は作りません")
            return r.returncode
    if "--skip" not in sys.argv:
        build_exe()
    package()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
