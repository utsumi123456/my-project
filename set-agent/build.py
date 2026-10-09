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
    # macOS: a real .app bundle (onedir). In onefile mode the bundle only holds a
    # launcher that unpacks Python into a temp folder and starts it as a second
    # process -- the Dock shows that process with a generic icon instead of ours,
    # and macOS can attribute the Accessibility permission (rekordbox following)
    # to it rather than to SetAgent.app. Windows keeps its single .exe.
    layout = "--onedir" if MAC else "--onefile"
    cmd = [sys.executable, "-m", "PyInstaller", layout, "--windowed", "--clean", "--noconfirm",
           "--name", "SetAgent", "--paths", ".",
           "--distpath", str(WORK), "--workpath", str(ROOT / "build" / "pyinstaller"),
           "--add-data", f"{ui}{os.pathsep}setagent/webui",
           "--hidden-import", "tools.decrypt_masterdb",
           # the phone view (webui.remote) and its QR code are imported on demand
           "--hidden-import", "setagent.webui.remote", "--hidden-import", "segno",
           # write-back (A): pyrekordbox + SQLCipher, imported only when the DJ writes.
           # The SQLAlchemy dialect is named in a URL string, so name it here too.
           "--hidden-import", "setagent.rekordbox.writeback", "--hidden-import", "setagent.rekordbox.publisher",
           "--hidden-import", "setagent.rekordbox.insights", "--hidden-import", "setagent.webui.dock",
           "--collect-all", "pyrekordbox", "--collect-all", "sqlcipher3",
           "--hidden-import", "sqlalchemy.dialects.sqlite.pysqlcipher"]
    # the icon: assets/icon/ is the DJ's chosen icon (rekordbox's with an orange
    # background, 2026-10-09) and wins; tools/make_icon.py is the fallback.
    fixed = ROOT / "assets" / "icon"
    if (fixed / "SetAgent.icns").exists() and (fixed / "SetAgent.ico").exists():
        icon = {"icns": fixed / "SetAgent.icns", "ico": fixed / "SetAgent.ico", "png": fixed / "SetAgent.png"}
        print(f"icon from {fixed}")
    else:
        from tools.make_icon import write as write_icon
        icon, how = write_icon(ROOT / "build" / "icon")
        print(f"icon {how}")
    if icon.get("png") and Path(icon["png"]).exists():    # the Dock icon the app sets at runtime
        cmd += ["--add-data", f"{icon['png']}{os.pathsep}setagent/webui"]
    if WIN:
        cmd += ["--icon", str(icon["ico"])]
    elif MAC:
        cmd += ["--icon", str(icon["icns"])]
    if WIN:
        cmd += ["--hidden-import", "webview.platforms.winforms", "--hidden-import", "clr_loader",
                # following rekordbox (selection.py): UI Automation through comtypes, imported lazily
                "--hidden-import", "comtypes.client", "--collect-submodules", "comtypes"]
    elif MAC:
        # pywebview drives WKWebView through pyobjc; PyInstaller cannot see the lazy import
        cmd += ["--hidden-import", "webview.platforms.cocoa", "--osx-bundle-identifier", BUNDLE_ID,
                # dock (B): window geometry (Quartz) and, for "split", moving rekordbox (Accessibility)
                "--hidden-import", "Quartz", "--hidden-import", "ApplicationServices",
                "--hidden-import", "PyObjCTools.AppHelper"]
    else:
        cmd += ["--hidden-import", "webview.platforms.gtk"]
    cmd.append("run_setagent.py")
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)
    if MAC:
        stable_signature(APP)


BUNDLE_ID = "jp.alphatheta.setagent"


def stable_signature(app: Path) -> None:
    """Re-sign the bundle ad hoc, but with a designated requirement that names
    only the bundle id. macOS keys the Accessibility permission (rekordbox
    following, docking's split) to that requirement; PyInstaller's default ad-hoc
    signature pins it to the code hash, so every rebuild was a new app to macOS
    and the permission silently stopped applying while the switch still showed
    on (2026-10-09, follow-check: "許可: なし"). With this, granting it once holds
    across rebuilds. No Developer ID needed."""
    req = f'=designated => identifier "{BUNDLE_ID}"'
    subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", BUNDLE_ID,
                    "--requirements", req, str(app)], check=True)
    out = subprocess.run(["codesign", "-d", "-r-", str(app)], capture_output=True, text=True)
    dr = [l for l in (out.stdout + out.stderr).splitlines() if "designated" in l]
    print("signature:", dr[0].strip() if dr else "(designated requirement not shown)")
    if not dr or BUNDLE_ID not in dr[0]:
        raise SystemExit("SetAgent.app の署名に bundle id の指定要件が入っていません（アクセシビリティの許可が保たれません）")


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
